"""Updates inbox, APPLY workflow, versioned engine files and the control ledger."""
import datetime, hashlib, io, json, os, re
from pathlib import Path

import anthropic
import streamlit as st

import claude_client
import fullreport

try:
    import pymupdf as fitz
except ImportError:
    import fitz

SYSTEM = """You maintain the engine files of an FSSAI nutraceutical label audit skill and its control ledger. You are given a newly notified instrument, the current engine files and the current control ledger rows. Propose only the changes the instrument itself supports.
Rules:
1. The latest text is the only text. Replace the old wording in place. Do not leave notes about what was changed, dated history or earlier versions inside an engine file.
2. Cite as the existing engine files do: the library file and page. The instrument will be filed in the library under the library path given to you; its pages are marked '--- PDF page N ---'. Use that path and those page numbers for every provision taken from the instrument.
3. Respect in-force dates exactly as the existing files do (the in-force check and gates). If the instrument is not yet in force, record the in-force date and do not make the rule apply earlier.
4. Never invent a provision, a date or a page. If the instrument has no bearing on a nutraceutical label audit, return empty lists and say so in the summary.
5. For each skill edit, old_str must be copied exactly from the current file and occur exactly once in it; keep it as short as possible while unique. new_str is the full replacement. Prefer several small edits to one large one.
6. For the ledger, change only existing rows by sheet, row_no and column name as given, or add new rows with the same column names. No em dashes.
Return ONE JSON object only, no text outside it, with keys: "summary" (string), "relevance" ("NUTRA", "FMCG", "BOTH" or "NONE"), "in_force_date" (string, dd.mm.yyyy or empty), "skill_edits" (list of {"file","old_str","new_str","reason"}), "ledger_updates" (list of {"sheet","row_no","column","new_value","reason"}), "ledger_new_rows" (list of {"sheet","data":{column: value},"reason"}), "notes_for_advocate" (list of strings, including anything you could not settle)."""


# ------------------------------------------------------------------ helpers
def _all(sb, table, cols="*", **eq):
    out, i = [], 0
    while True:
        q = sb.table(table).select(cols)
        for k, v in eq.items():
            q = q.eq(k, v)
        got = q.range(i, i + 999).execute().data
        out += got
        if len(got) < 1000:
            return out
        i += 1000


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:80] or "file"


def pdf_pages(data):
    doc = fitz.open(stream=data, filetype="pdf")
    return [(i + 1, doc[i].get_text("text").replace("\x00", "").strip()) for i in range(len(doc))]


def lib_path(row):
    return f"99_APPLIED/{_safe(row.get('instrument_date') or 'undated')}_{_safe(row['title'])}.pdf"


def disk_texts(skill_dir):
    d = {}
    for p in Path(skill_dir).glob("*.md"):
        d[p.name] = p.read_text(encoding="utf-8", errors="ignore")
    return d


def skill_stamp(sb):
    try:
        r = sb.table("skill_versions").select("id").eq("is_current", True).order("id", desc=True).limit(1).execute().data
        return str(r[0]["id"]) if r else ""
    except Exception:
        return ""


def skill_overlay(sb):
    try:
        rows = sb.table("skill_versions").select("file_name,content").eq("is_current", True).execute().data
        return {r["file_name"]: r["content"] for r in rows}
    except Exception:
        return {}


def current_texts(sb, skill_dir):
    t = disk_texts(skill_dir)
    t.update(skill_overlay(sb))
    return t


def log_change(sb, user, update_id, action, target, summary, detail=None):
    sb.table("change_log").insert({"username": user, "update_id": update_id, "action": action,
                                   "target": target, "summary": summary, "detail": detail}).execute()


def save_version(sb, name, content, user, note, update_id=None, skill_dir="skills/fssai-label-audit"):
    last = sb.table("skill_versions").select("version").eq("file_name", name).order("version", desc=True).limit(1).execute().data
    if last:
        ver = last[0]["version"] + 1
    else:
        base = disk_texts(skill_dir).get(name)
        if base is not None:
            sb.table("skill_versions").insert({"file_name": name, "version": 1, "content": base, "created_by": "repository",
                                               "note": "Initial text from the repository", "is_current": False}).execute()
            ver = 2
        else:
            ver = 1
    new = sb.table("skill_versions").insert({"file_name": name, "version": ver, "content": content, "created_by": user,
                                             "note": note, "update_id": update_id, "is_current": True}).execute().data[0]
    sb.table("skill_versions").update({"is_current": False}).eq("file_name", name).neq("id", new["id"]).execute()
    return ver


# ------------------------------------------------------------------ ledger
def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.date().isoformat() if isinstance(v, datetime.datetime) else v.isoformat()
    return str(v).strip()


def import_ledger(sb, data, user):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    sb.table("ledger_rows").delete().neq("sheet", "__none__").execute()
    sb.table("ledger_sheets").delete().neq("sheet", "__none__").execute()
    n_rows = 0
    for pos, ws in enumerate(wb.worksheets):
        rows = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True) if any(_cell(c) for c in r)]
        if not rows:
            continue
        headers, seen = [], {}
        for i, h in enumerate(rows[0]):
            h = h or f"col{i + 1}"
            seen[h] = seen.get(h, 0) + 1
            headers.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
        sb.table("ledger_sheets").insert({"sheet": ws.title, "headers": headers, "position": pos}).execute()
        recs = [{"sheet": ws.title, "row_no": i, "data": dict(zip(headers, r))} for i, r in enumerate(rows[1:], 1)]
        for k in range(0, len(recs), 200):
            sb.table("ledger_rows").insert(recs[k:k + 200]).execute()
        n_rows += len(recs)
    log_change(sb, user, None, "LEDGER IMPORT", "control ledger", f"Imported {len(wb.worksheets)} sheets, {n_rows} rows")
    return n_rows


def export_ledger(sb):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for s in sorted(_all(sb, "ledger_sheets"), key=lambda x: x["position"] or 0):
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "_", s["sheet"])[:31])
        ws.append(s["headers"])
        for r in sorted(_all(sb, "ledger_rows", sheet=s["sheet"]), key=lambda x: x["row_no"]):
            ws.append([r["data"].get(h, "") for h in s["headers"]])
    ws = wb.create_sheet("App Change Log")
    ws.append(["When (UTC)", "User", "Update", "Action", "Target", "Summary"])
    for c in _all(sb, "change_log", "created_at,username,update_id,action,target,summary"):
        ws.append([str(c.get("created_at") or "")[:19], c.get("username"), c.get("update_id"), c.get("action"), c.get("target"), c.get("summary")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def ledger_dump(sb, cap=400_000):
    heads = {s["sheet"]: s["headers"] for s in _all(sb, "ledger_sheets")}
    lines, size = [], 0
    for r in _all(sb, "ledger_rows"):
        ln = f"[{r['sheet']}#{r['row_no']}] " + json.dumps(r["data"], ensure_ascii=False)
        size += len(ln)
        if size > cap:
            lines.append("[ledger truncated]")
            break
        lines.append(ln)
    return heads, "\n".join(lines)


# ------------------------------------------------------------------ inbox
def add_instrument(sb, title, date, routing, note, data, filename, user):
    pages = pdf_pages(data)
    text = "\n".join(f"--- PDF page {n} ---\n{t}" for n, t in pages)
    path = f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{_safe(filename)}"
    sb.storage.from_("inbox").upload(path, data, {"content-type": "application/pdf"})
    row = sb.table("updates_inbox").insert({"created_by": user, "title": title, "instrument_date": date, "routing": routing,
                                            "note": note, "file_name": filename, "storage_path": path, "text": text}).execute().data[0]
    log_change(sb, user, row["id"], "INBOX", title, f"Added to inbox, routing {routing}")
    return len("".join(t for _, t in pages))


def attach_pdf(sb, row_id, data, filename, user):
    pages = pdf_pages(data)
    text = "\n".join(f"--- PDF page {n} ---\n{t}" for n, t in pages)
    path = f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{_safe(filename)}"
    sb.storage.from_("inbox").upload(path, data, {"content-type": "application/pdf"})
    sb.table("updates_inbox").update({"storage_path": path, "file_name": filename, "text": text, "status": "pending"}).eq("id", row_id).execute()
    log_change(sb, user, row_id, "INBOX", filename, "PDF attached")
    return len("".join(t for _, t in pages))


def rescue_skipped(sb, key, user):
    r = sb.table("scan_seen").select("*").eq("key", key).execute().data
    if not r:
        return
    r = r[0]
    row = sb.table("updates_inbox").insert({"created_by": user, "title": r["title"], "instrument_date": (r.get("date_text") or "").replace("-", "."),
                                            "routing": "BOTH", "note": "Pulled in by hand from the scan's skipped list. Upload the PDF.",
                                            "status": "needs_pdf", "source_url": r.get("url")}).execute().data[0]
    sb.table("scan_seen").update({"status": "needs_pdf"}).eq("key", key).execute()
    log_change(sb, user, row["id"], "INBOX", r["title"], "Pulled in from the skipped list")


def validate(sb, prop, skill_dir):
    texts = current_texts(sb, skill_dir)
    heads = {s["sheet"]: s["headers"] for s in _all(sb, "ledger_sheets")}
    existing = {(r["sheet"], r["row_no"]) for r in _all(sb, "ledger_rows", "sheet,row_no")}
    for e in prop.get("skill_edits", []):
        t = texts.get(e.get("file", ""))
        n = t.count(e.get("old_str", "")) if t is not None and e.get("old_str") else 0
        e["_ok"] = n == 1
        e["_problem"] = "" if n == 1 else ("file not found" if t is None else "old text not found" if n == 0 else "old text not unique")
    for u in prop.get("ledger_updates", []):
        try:
            u["row_no"] = int(u.get("row_no"))
        except Exception:
            u["row_no"] = -1
        ok = (u.get("sheet"), u["row_no"]) in existing and u.get("column") in heads.get(u.get("sheet"), [])
        u["_ok"], u["_problem"] = ok, "" if ok else "row or column not found"
    for u in prop.get("ledger_new_rows", []):
        ok = u.get("sheet") in heads and isinstance(u.get("data"), dict)
        u["_ok"], u["_problem"] = ok, "" if ok else "sheet not found"
    return prop


def draft(sb, row_id, ctx):
    row = sb.table("updates_inbox").select("*").eq("id", row_id).execute().data[0]
    texts = current_texts(sb, ctx["skill_dir"])
    heads, ledger = ledger_dump(sb)
    files = "\n\n".join(f"=== FILE: {n} ===\n{t}" for n, t in sorted(texts.items()))
    prompt = (f"NEW INSTRUMENT\nTitle: {row['title']}\nDate: {row['instrument_date']}\nRouting given by the advocate's office: "
              f"{row['routing']}\nNote: {row['note'] or 'none'}\nIt will be filed in the library as: {lib_path(row)}\n\n"
              f"{(row['text'] or '')[:400000]}\n\nCURRENT ENGINE FILES\n{files}\n\nCURRENT CONTROL LEDGER\n"
              f"Sheets and columns: {json.dumps(heads, ensure_ascii=False)}\n{ledger or '(ledger not loaded)'}")
    cl = claude_client.make_client(ctx["api_key"])
    with cl.messages.stream(model=ctx["model"], max_tokens=64000, system=SYSTEM,
                            extra_body={"output_config": {"effort": "high"}},
                            messages=[{"role": "user", "content": prompt}]) as s:
        text = "".join(s.text_stream)
    prop = validate(sb, fullreport.parse_json(text), ctx["skill_dir"])
    prop.setdefault("skill_edits", [])
    prop.setdefault("ledger_updates", [])
    prop.setdefault("ledger_new_rows", [])
    prop["lib_file"] = lib_path(row)
    sb.table("updates_inbox").update({"proposal": prop}).eq("id", row_id).execute()
    return prop


def apply_update(sb, row, prop, edit_ids, led_ids, new_ids, user, note, skill_dir):
    out = []
    # 1. library
    try:
        data = sb.storage.from_("inbox").download(row["storage_path"])
        f = prop.get("lib_file") or lib_path(row)
        pages = pdf_pages(data)
        sb.table("library_pages").delete().eq("file", f).execute()
        recs = [{"file": f, "page": n, "text": t, "ocr": False} for n, t in pages]
        for k in range(0, len(recs), 50):
            sb.table("library_pages").insert(recs[k:k + 50]).execute()
        sb.table("library_files").upsert({"file": f, "folder": "99_APPLIED", "pages": len(pages), "ocr_pages": 0,
                                          "empty_pages": sum(1 for _, t in pages if len(t) < 20),
                                          "sha1": hashlib.sha1(data).hexdigest()}).execute()
        out.append(f"Filed in the library as {f} ({len(pages)} pages).")
        log_change(sb, user, row["id"], "APPLY", f, "Instrument filed in the library")
    except Exception as e:
        out.append(f"Library filing failed: {e}")
    # 2. engine files
    texts = current_texts(sb, skill_dir)
    by_file = {}
    for i in edit_ids:
        by_file.setdefault(prop["skill_edits"][i]["file"], []).append(prop["skill_edits"][i])
    for fname, edits in by_file.items():
        t, done = texts.get(fname), []
        for e in edits:
            if t is not None and t.count(e["old_str"]) == 1:
                t = t.replace(e["old_str"], e["new_str"], 1)
                done.append({k: e.get(k) for k in ("old_str", "new_str", "reason")})
            else:
                out.append(f"Skipped an edit in {fname}: the text was no longer found exactly once.")
        if done:
            ver = save_version(sb, fname, t, user, f"Update #{row['id']}: {row['title']}", row["id"], skill_dir)
            log_change(sb, user, row["id"], "APPLY", fname, f"{len(done)} edit(s), now version {ver}", {"edits": done})
            out.append(f"{fname}: {len(done)} edit(s), version {ver}.")
    # 3. ledger
    for i in led_ids:
        u = prop["ledger_updates"][i]
        r = sb.table("ledger_rows").select("data").eq("sheet", u["sheet"]).eq("row_no", u["row_no"]).execute().data
        if r:
            d = r[0]["data"]
            before = d.get(u["column"], "")
            d[u["column"]] = str(u["new_value"])
            sb.table("ledger_rows").update({"data": d}).eq("sheet", u["sheet"]).eq("row_no", u["row_no"]).execute()
            log_change(sb, user, row["id"], "APPLY", f"ledger {u['sheet']}#{u['row_no']}", f"{u['column']}: changed",
                       {"before": before, "after": str(u["new_value"]), "reason": u.get("reason")})
            out.append(f"Ledger {u['sheet']} row {u['row_no']}, {u['column']} updated.")
    for i in new_ids:
        u = prop["ledger_new_rows"][i]
        last = sb.table("ledger_rows").select("row_no").eq("sheet", u["sheet"]).order("row_no", desc=True).limit(1).execute().data
        sb.table("ledger_rows").insert({"sheet": u["sheet"], "row_no": (last[0]["row_no"] + 1) if last else 1,
                                        "data": {k: str(v) for k, v in u["data"].items()}}).execute()
        log_change(sb, user, row["id"], "APPLY", f"ledger {u['sheet']}", "New row added", {"data": u["data"], "reason": u.get("reason")})
        out.append(f"Ledger {u['sheet']}: new row added.")
    summary = " ".join(out)
    sb.table("updates_inbox").update({"status": "applied", "decided_by": user, "decided_at": datetime.datetime.utcnow().isoformat(),
                                      "decision_note": note, "applied_summary": summary}).eq("id", row["id"]).execute()
    return out


def decline(sb, row, user, note):
    sb.table("updates_inbox").update({"status": "declined", "decided_by": user, "decided_at": datetime.datetime.utcnow().isoformat(),
                                      "decision_note": note}).eq("id", row["id"]).execute()
    log_change(sb, user, row["id"], "DECLINE", row["title"], note or "Declined")


# ------------------------------------------------------------------ page
def page_updates(sb, user, ctx):
    st.subheader("Updates and control ledger")
    st.caption("Nothing reaches the library, the ledger or the engine files until it is approved here with APPLY.")
    t1, t2, t3, t4 = st.tabs(["Inbox", "Ledger", "Engine files", "Change log"])
    with t1:
        _tab_inbox(sb, user, ctx)
    with t2:
        _tab_ledger(sb, user)
    with t3:
        _tab_files(sb, user, ctx)
    with t4:
        rows = sb.table("change_log").select("id,created_at,username,update_id,action,target,summary").order("id", desc=True).limit(300).execute().data
        st.dataframe(rows, width="stretch")
        pick = st.number_input("Show detail of change log id", min_value=0, step=1, value=0)
        if pick:
            r = sb.table("change_log").select("*").eq("id", int(pick)).execute().data
            if r:
                st.json(r[0].get("detail") or {})


def _tab_inbox(sb, user, ctx):
    with st.expander("Add an instrument to the inbox"):
        up = st.file_uploader("Instrument (PDF)", type=["pdf"], key="inb_pdf")
        c1, c2, c3 = st.columns(3)
        title = c1.text_input("Title", key="inb_title")
        date = c2.text_input("Instrument date (dd.mm.yyyy)", key="inb_date")
        routing = c3.selectbox("Routing", ["NUTRA", "BOTH", "FMCG"], key="inb_route")
        note = st.text_input("Note (optional)", key="inb_note")
        if st.button("Add to inbox", disabled=not (up and title.strip())):
            try:
                n = add_instrument(sb, title.strip(), date.strip(), routing, note, up.getvalue(), up.name, user)
                if n < 200:
                    st.warning("This PDF has almost no text (scanned?). It cannot be read for a draft until it is OCR'd.")
                st.success("Added.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not add: {e}")
    cols = "id,created_at,created_by,title,instrument_date,routing,note,status,proposal,decided_by,decided_at,decision_note,applied_summary,source_url"
    rows = sb.table("updates_inbox").select(cols).order("id", desc=True).limit(150).execute().data
    needs = [r for r in rows if r["status"] == "needs_pdf"]
    if needs:
        st.markdown(f"**Needs a PDF ({len(needs)})**")
        st.caption("Found by the weekly scan, but the FSSAI list had no direct PDF link. Open the source page, download the PDF and attach it here.")
        for r in needs:
            with st.expander(f"#{r['id']} | {r['title'][:90]} | {r['instrument_date'] or ''}"):
                if r.get("source_url"):
                    st.markdown(f"Source page: {r['source_url']}")
                up2 = st.file_uploader("PDF", type=["pdf"], key=f"np{r['id']}")
                c1, c2 = st.columns(2)
                if c1.button("Attach PDF", disabled=not up2, key=f"na{r['id']}"):
                    try:
                        attach_pdf(sb, r["id"], up2.getvalue(), up2.name, user)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not attach: {e}")
                if c2.button("Dismiss", key=f"nd{r['id']}"):
                    decline(sb, r, user, "Dismissed (no PDF needed)")
                    st.rerun()
    pending = [r for r in rows if r["status"] == "pending"]
    st.markdown(f"**Pending ({len(pending)})**")
    for r in pending:
        with st.expander(f"#{r['id']} | {r['title']} | {r['routing']} | {r['created_at'][:10]}"):
            prop = r.get("proposal")
            if r.get("source_url"):
                st.caption(f"Source: {r['source_url']}")
            rt = st.selectbox("Routing", ["NUTRA", "BOTH", "FMCG"], index=["NUTRA", "BOTH", "FMCG"].index(r["routing"]) if r["routing"] in ("NUTRA", "BOTH", "FMCG") else 1, key=f"rt{r['id']}")
            if rt != r["routing"] and st.button("Save routing", key=f"rs{r['id']}"):
                sb.table("updates_inbox").update({"routing": rt}).eq("id", r["id"]).execute()
                log_change(sb, user, r["id"], "ROUTING", r["title"], f"Routing changed to {rt}")
                st.rerun()
            if r["routing"] == "FMCG":
                st.info("Routing is FMCG only. It does not go into this engine; decline it with a note.")
            if not prop:
                if r["routing"] != "FMCG" and st.button("Draft proposed changes", key=f"d{r['id']}"):
                    try:
                        with st.spinner("Reading the instrument against the engine files and the ledger. This can take several minutes."):
                            draft(sb, r["id"], ctx)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not draft: {e}")
            else:
                st.write(prop.get("summary", ""))
                st.caption(f"Relevance: {prop.get('relevance', '')} | In force from: {prop.get('in_force_date') or 'not stated'} | "
                           f"Will be filed as: {prop.get('lib_file', '')}")
                for n in prop.get("notes_for_advocate", []):
                    st.warning(n)
                ed, lu, ln = [], [], []
                for i, e in enumerate(prop["skill_edits"]):
                    on = st.checkbox(f"Edit {i + 1}: {e['file']}" + (f"  (cannot apply: {e['_problem']})" if not e["_ok"] else ""),
                                     value=e["_ok"], disabled=not e["_ok"], key=f"e{r['id']}_{i}")
                    a, b = st.columns(2)
                    a.code(e["old_str"][:1500], language=None)
                    b.code(e["new_str"][:1500], language=None)
                    st.caption(e.get("reason", ""))
                    if on:
                        ed.append(i)
                for i, u in enumerate(prop["ledger_updates"]):
                    on = st.checkbox(f"Ledger {u['sheet']} row {u['row_no']}, {u['column']} to: {str(u['new_value'])[:150]}"
                                     + (f"  (cannot apply: {u['_problem']})" if not u["_ok"] else ""),
                                     value=u["_ok"], disabled=not u["_ok"], key=f"l{r['id']}_{i}")
                    st.caption(u.get("reason", ""))
                    if on:
                        lu.append(i)
                for i, u in enumerate(prop["ledger_new_rows"]):
                    on = st.checkbox(f"New ledger row in {u['sheet']}: {json.dumps(u['data'], ensure_ascii=False)[:200]}",
                                     value=u["_ok"], disabled=not u["_ok"], key=f"n{r['id']}_{i}")
                    if on:
                        ln.append(i)
                if not (prop["skill_edits"] or prop["ledger_updates"] or prop["ledger_new_rows"]):
                    st.info("No engine or ledger change is proposed. APPLY would only file the instrument in the library.")
            note = st.text_input("Decision note", key=f"note{r['id']}")
            ok = st.checkbox("I am the approving advocate and I have read the changes above.", key=f"ok{r['id']}")
            c1, c2 = st.columns(2)
            if prop and r["routing"] != "FMCG" and c1.button("APPLY", type="primary", disabled=not ok, key=f"a{r['id']}"):
                full = sb.table("updates_inbox").select("*").eq("id", r["id"]).execute().data[0]
                try:
                    res = apply_update(sb, full, prop, ed, lu, ln, user, note, ctx["skill_dir"])
                    st.success("APPLIED. " + " ".join(res))
                    st.rerun()
                except Exception as e:
                    st.error(f"APPLY stopped part way: {e}. Check the Change log tab for what was done.")
            if c2.button("Decline", disabled=not ok, key=f"x{r['id']}"):
                decline(sb, r, user, note)
                st.rerun()
    try:
        sk = sb.table("scan_seen").select("key,title,date_text,url").eq("status", "skipped").order("first_seen", desc=True).limit(60).execute().data
    except Exception:
        sk = []
    if sk:
        with st.expander(f"Skipped by the weekly scan as not label related ({len(sk)} latest)"):
            st.caption("Check that nothing important was filtered out. 'Move to inbox' creates an inbox item you can attach a PDF to.")
            for x in sk:
                c1, c2 = st.columns([5, 1])
                c1.write(f"{x['date_text']} | {x['title'][:140]}")
                if c2.button("Move to inbox", key=f"sk{x['key'][:12]}"):
                    rescue_skipped(sb, x["key"], user)
                    st.rerun()
    done = [{k: r[k] for k in ("id", "created_at", "title", "routing", "status", "decided_by", "decided_at", "decision_note")}
            for r in rows if r["status"] not in ("pending", "needs_pdf")]
    if done:
        st.markdown("**Decided**")
        st.dataframe(done, width="stretch")


def _tab_ledger(sb, user):
    sheets = sorted(_all(sb, "ledger_sheets"), key=lambda x: x["position"] or 0)
    up = st.file_uploader("Load or replace the control ledger (xlsx). This replaces the ledger held in the app.", type=["xlsx"], key="led_up")
    if up and st.button("Import ledger"):
        try:
            n = import_ledger(sb, up.getvalue(), user)
            st.success(f"Imported {n} rows.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not import: {e}")
    if not sheets:
        st.info("No ledger loaded yet.")
        return
    pick = st.selectbox("Sheet", [s["sheet"] for s in sheets])
    rows = _all(sb, "ledger_rows", sheet=pick)
    st.dataframe([{"row_no": r["row_no"], **r["data"]} for r in sorted(rows, key=lambda x: x["row_no"])], width="stretch")
    st.download_button("Download ledger (xlsx)", export_ledger(sb), "Control_Ledger_from_app.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption("The export holds the values only (no colours or formulas). Keep the client's original workbook as the formatted master.")


def _tab_files(sb, user, ctx):
    names = sorted(current_texts(sb, ctx["skill_dir"]))
    if not names:
        st.info("No engine files found.")
        return
    f = st.selectbox("Engine file", names)
    vers = sb.table("skill_versions").select("id,version,created_at,created_by,note,is_current").eq("file_name", f).order("version", desc=True).execute().data
    if vers:
        st.dataframe(vers, width="stretch")
        opts = {f"Version {v['version']} ({v['created_at'][:16]})": v["id"] for v in vers if not v["is_current"]}
        if opts:
            pick = st.selectbox("Restore an earlier version", list(opts))
            if st.button("Restore this version"):
                old = sb.table("skill_versions").select("content,version").eq("id", opts[pick]).execute().data[0]
                ver = save_version(sb, f, old["content"], user, f"Restored version {old['version']}", None, ctx["skill_dir"])
                log_change(sb, user, None, "RESTORE", f, f"Restored version {old['version']} as version {ver}")
                st.success(f"Restored as version {ver}.")
                st.rerun()
    else:
        st.caption("No change has been applied to this file yet. It is running from the repository copy.")
    with st.expander("Show the current text"):
        st.code(current_texts(sb, ctx["skill_dir"])[f][:60000], language=None)