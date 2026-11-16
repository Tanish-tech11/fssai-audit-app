"""FSSAI Nutraceutical Label Audit - web app (Streamlit + Claude API)."""
import base64, datetime, hashlib, hmac, io, json, os, re, secrets as pysecrets, tempfile
from pathlib import Path

import anthropic
import streamlit as st

import fullreport
import labelart
import libcheck
import claude_client
import updates

BASE = Path(__file__).parent
SKILL_DIR = Path(os.getenv("SKILL_DIR", BASE / "skills" / "fssai-label-audit"))
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
MAX_OUT = int(os.getenv("MAX_OUTPUT_TOKENS", "128000" if "opus" in MODEL else "64000"))
MAX_CTX = int(os.getenv("MAX_CONTEXT_TOKENS", "800000"))
# Opus 5.5 always thinks (adaptive). Depth is set with effort: low, medium, high, xhigh, max.
EFFORT = os.getenv("AUDIT_EFFORT", "xhigh").strip().lower()
if EFFORT not in ("low", "medium", "high", "xhigh", "max"):
    EFFORT = "xhigh"
EXCLUDE = {x.strip() for x in os.getenv("EXCLUDE_FILES", "").split(",") if x.strip()}
SKIP_SHEETS = [x.strip().lower() for x in os.getenv("SKIP_SHEETS", "schedule").split(",") if x.strip()]
MAX_UPLOAD_MB = 30

WRAPPER = """You are the FSSAI Label Audit Engine running inside a web application. The reference files that follow are your skill (00_SKILL.md to 05_templates.md, plus reference data). Follow them for method, checklist, severity, composition rationality test, exposure and tone.

Environment overrides for this web app. These win over the skill wherever they conflict:
1. There is no file system, no Projects tool, no computer link, no OCR tool and no other skill. Ignore every Windows path and every instruction to read, save or build files. Read the label directly from the uploaded images or PDFs.
2. The legal library (the PDFs in folders 01 to 11) and the control ledger are NOT available here. Cite a provision only from the reference files given to you, with the library page numbers they carry. Anything you cannot confirm from them is marked UTV or unverified. Never cite from memory. Never invent or infer a Schedule entry.
3. Do not run 07_report_builder.py and do not produce marked or corrected artwork images. Write the report as Markdown with these sections in order: 1 Product identification; 2 Executive position; 3 Deficiency schedule (table with columns Sr., As printed, Deficiency, Provision (N22 and N16), Severity as Critical, Major or Minor, Correction); 4 Online listing findings (only if listing text was supplied); 5 Composition and rationality (ingredient table, dose reconciliation, conclusion); 6 Checklist status (every point NC, C, UTV or NA, compact table grouped by Block); 7 Unable to verify; 8 Exposure under the four heads and the forum map; 9 Recommended course; 10 Corrected wording for each finding; 11 Suggested compliant label text (changed text inside [[double square brackets]]); 12 Sources relied on, verified and unverified.
4. Never certify a label as compliant. No em dashes. Write in English. Use the audit date given by the user."""

JSON_SPEC = """Return ONE JSON object only, with no text before or after it and no code fences. The app builds the Word report from it, so every key below must be present (use empty strings or empty lists where nothing applies). Keys: "product" (string); "client" (string); "identification" (list of [particular, as found] pairs); "executive" (string, the executive position); "findings" (list, most serious first, one object per deficiency, each with: "page" (integer, page number of the artwork as listed in the user message), "anchor" (the exact words as printed on the label where the defect sits, copied letter for letter, 3 to 12 words; empty if the item is missing), "box_norm" ([x0, y0, x1, y1] as fractions 0 to 1 of the page width and height, read from the grid view of the page; your best estimate of the area; for a missing mandatory item the place where it should be), "missing" (true if a mandatory item is absent), "sev" ("Critical", "Major" or "Minor"), "printed" (what is printed, short), "deficiency", "prov" (provision in N22 and N16 from the reference files), "fix" (the correction), "over" (short corrected wording to show inside the blue box, optional), "search_terms" (list of 2 or 3 short phrases of 3 to 8 words that the regulation text itself would contain for the provision relied on, used to find that page in the official library)); "online" ({"intro": string, "rows": [{"where","shown","defect","sev","fix"}]}, rows only if listing text was supplied); "composition" ({"rows": [[ingredient, per unit, schedule and entry (N22; N16), permitted range, marker required, marker declared]]}); "reconciliation" ({"rows": [[ingredient, per unit, schedule, floor per day, ceiling per day, units min, units max]], "evidence": string, "conclusion": string}); "verification" (list of [point, provision, document or check required, from whom]); "exposure" (object with the keys "FSS Act, 2006", "Drugs and Magic Remedies Act, 1954", "Consumer Protection Act, 2019 and E-Commerce Rules", "Legal Metrology Act, 2009 and Rules", "Forum map", each a list of paragraph strings); "course" (list of paragraph strings, the recommended course); "label" (list of panels {"panel": name, "lines": list of lines, each line a list of [text, bold 0 or 1, changed 0 or 1] segments}, the suggested compliant label with changed text flagged 1); "sources_verified" (list of [provision, library file and page as given in the reference files]); "sources_unverified" (list of strings). Do not add a checklist table in this mode. Findings must cover every defect the checklist and composition audit produce. Keep the JSON compact so that it is not cut off: at most 30 findings (merge related ones), "printed" at most 25 words, "deficiency" and "fix" at most 45 words each, "over" at most 20 words, "prov" at most 30 words; the composition and reconciliation tables only for ingredients that matter; the suggested label only for the panels that change, with short lines."""
WRAPPER_FULL = re.sub(r"\n3\. .*?\n4\.", lambda m: "\n3. " + JSON_SPEC + "\n4.", WRAPPER, flags=re.S)

LABEL_SPEC = """You are now preparing the corrected label artwork. The user message holds the label (images or PDF), the list of artwork pages and the final audit report as JSON. Return ONE JSON object only, with no text outside it: {"edits": [...], "notes": [...]}. Each edit changes one place on the artwork so that the findings are cured.
Rules: change only what a finding supports; keep the pack's own wording where it already meets the requirement in substance; add nothing the label did not say and no finding calls for; never invent a figure, licence number, date, address, claim or certificate: write [ ] where a figure must come from the formulation sheet or an analytical report. No em dashes.
Edit fields: "type" ("text", "table", "veg_mark" or "remove"); "mode" ("replace" for text that exists on the label, "add" for a mandatory item that is missing); "page" (integer, as listed); "anchor" (for replace: the exact words printed at the start of the text block to be replaced, copied letter for letter, 3 to 12 words; empty for add); "region_norm" ([x0, y0, x1, y1] as fractions 0 to 1 of the page width and height: for replace, tight around the WHOLE text block that is replaced; for add, an empty area of the same panel big enough for the text, clear of logos, QR codes and graphics). For type text: "text" (the new wording, \n for line breaks), "bold" (true or false), "align" ("left" or "center"). For type table: "rows" (list of rows, each a list of cell strings, first row the header). For type veg_mark: "variant" ("veg" or "non_veg") and region_norm tight around the existing mark.
For type remove: "region_norm" tight around a seal, logo, claim or device that a finding says must be deleted (add "anchor" if it is printed text); use it only when a finding requires the deletion. Read every region_norm from the grid view that accompanies each page. The app cannot draw logos, seals, QR codes or photographs: do not add or change them. Put in "notes" what a designer must do by hand (for example remove a certification seal, replace a logo). Keep each new text short enough for its region, and do not rewrite paragraphs that need no change."""
WRAPPER_LABEL = re.sub(r"\n3\. .*?\n4\.", lambda m: "\n3. " + LABEL_SPEC + "\n4.", WRAPPER, flags=re.S)


APP_TITLE = os.getenv("APP_TITLE", "FSSAI NUTRACEUTICAL LABELLING PROJECT")
APP_DESC = os.getenv("APP_DESCRIPTION", "Label audit system for nutraceutical products and food supplements, to find the mistakes in their labelling.")
REVISE_EFFORT = os.getenv("REVISE_EFFORT", "medium").strip().lower()
LABEL_EFFORT = os.getenv("LABEL_EFFORT", "medium").strip().lower()
EFFORT_NAMES = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra", "max": "Max"}

CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 2.2rem; max-width: 1250px;}
.crumb {color:#6b6a68; font-size:.92rem; margin-bottom:.3rem;}
.proj-title {font-family: Georgia, 'Times New Roman', serif; font-weight:600; font-size:2.5rem;
  letter-spacing:-.02em; line-height:1.12; margin:.1rem 0 .7rem; color:#1f1e1d;}
.proj-desc {color:#5c5b58; font-size:1.05rem; margin-bottom:1.5rem; max-width:62rem;}
.hint {color:#6b6a68; font-size:1rem; margin:.1rem 0 .4rem;}
.badge {color:#4a4946; font-size:.92rem; text-align:right; padding-top:.45rem;}
.pmeta {color:#6b6a68; font-size:.88rem; margin:-.35rem 0 .3rem 1.9rem;}
.psec {color:#8a8984; font-size:.85rem; margin:1.3rem 0 .2rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius:20px; border:1px solid #e4e2d9;
  background:#ffffff; box-shadow:0 1px 10px rgba(0,0,0,.04);}
div[data-testid="stFileUploaderDropzone"] {border-radius:14px;}
.st-key-recents button {background:transparent; border:none; border-bottom:1px solid #ebe9e1; border-radius:0;
  box-shadow:none; justify-content:flex-start; text-align:left; padding:.85rem .2rem; font-size:1rem;}
.st-key-recents button:hover {background:#f1efe8;}
.st-key-recents button p {text-align:left; font-weight:400;}
.ago {color:#8a8984; font-size:.9rem; text-align:right; padding-top:.8rem;}
.st-key-panel hr {margin:.5rem 0; border-color:#ebe9e1;}
</style>
"""


def ago(iso):
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        sec = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
    except Exception:
        return ""
    if sec < 90:
        return "just now"
    if sec < 3600:
        return f"{int(sec // 60)} minutes ago"
    if sec < 86400:
        return f"{int(sec // 3600)} hours ago"
    if sec < 86400 * 14:
        return f"{int(sec // 86400)} days ago"
    return t.strftime("%d %b %Y")


def model_label():
    parts = MODEL.replace("claude-", "").split("-")
    name = parts[0].capitalize() + (" " + ".".join(parts[1:]) if len(parts) > 1 else "")
    return f"{name} {EFFORT_NAMES.get(EFFORT, EFFORT)}"


def header(big):
    st.markdown(f'<div class="crumb">Projects &nbsp;/&nbsp; {APP_TITLE}</div>', unsafe_allow_html=True)
    if big:
        st.markdown(f'<div class="proj-title">{APP_TITLE}</div><div class="proj-desc">{APP_DESC}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ skill loading
def _order(p):
    name = Path(p).name
    m = re.match(r"(\d+)([A-Za-z]?)", name)
    return (int(m.group(1)), m.group(2)) if m else (999, name)


@st.cache_resource
def load_skill(stamp=""):
    texts = {p.name: p.read_text(encoding="utf-8", errors="ignore") for p in SKILL_DIR.glob("*.md")}
    if stamp and db():
        texts.update(updates.skill_overlay(db()))  # engine files changed through APPLY
    parts = [(n, texts[n]) for n in sorted(texts, key=_order) if n not in EXCLUDE]
    xl = SKILL_DIR / "06_reference_data.xlsx"
    if xl.exists() and xl.name not in EXCLUDE:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(xl, read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                if any(s in ws.title.lower() for s in SKIP_SHEETS):
                    continue
                out.append(f"## Sheet: {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    if any(c is not None for c in row):
                        out.append(" | ".join("" if c is None else str(c) for c in row))
            parts.append(("06_reference_data.xlsx", "\n".join(out)))
        except Exception as e:  # keep app alive even if the sheet is odd
            parts.append(("06_reference_data.xlsx", f"[could not be read: {e}]"))
    text = "\n\n".join(f"=== FILE: {n} ===\n{t}" for n, t in parts)
    return text, [(n, len(t)) for n, t in parts]


# ------------------------------------------------------------------ database and login
@st.cache_resource
def db():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def hash_pw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def env_users():
    d = {}
    for item in os.getenv("APP_USERS", "").split(";"):
        if ":" in item:
            u, p = item.split(":", 1)
            d[u.strip()] = p.strip()
    return d


def authenticate(u, p):
    """Returns the role on success, else None. Database users first, APP_USERS as bootstrap."""
    d = db()
    if d:
        try:
            r = d.table("app_users").select("*").eq("username", u).execute().data
            if r:
                row = r[0]
                if row["active"] and hmac.compare_digest(hash_pw(p, row["salt"]), row["password_hash"]):
                    return row["role"]
                return None
        except Exception as e:
            st.warning(f"User database unavailable, using APP_USERS only. ({e})")
    env = env_users()
    if u in env and hmac.compare_digest(env[u].encode(), p.encode()):
        admins = {x.strip() for x in os.getenv("ADMIN_USERS", "").split(",")}
        return "admin" if u in admins else "user"
    return None


def login():
    if st.session_state.get("user"):
        return True
    st.markdown(CSS, unsafe_allow_html=True)
    header(True)
    if not db() and not env_users():
        st.error("No users configured. The admin must set APP_USERS (or the Supabase settings).")
        return False
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Login")
    if ok:
        role = authenticate(u.strip(), p)
        if role:
            st.session_state["user"], st.session_state["role"] = u.strip(), role
            st.rerun()
        else:
            st.error("Incorrect username or password.")
    return False


# ------------------------------------------------------------------ markdown -> docx
def md_to_docx(md: str) -> bytes:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt

    doc = Document()
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(11)
    s = doc.sections[0]
    s.orientation = WD_ORIENT.LANDSCAPE
    s.page_width, s.page_height = Cm(29.7), Cm(21.0)
    s.left_margin = s.right_margin = Cm(2)

    def runs(p, text, size=None):
        for k, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
            if part:
                r = p.add_run(part)
                r.bold = k % 2 == 1
                if size:
                    r.font.size = Pt(size)

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                n = max(len(r) for r in rows)
                tb = doc.add_table(rows=len(rows), cols=n)
                tb.style = "Table Grid"
                for ri, r in enumerate(rows):
                    for ci in range(n):
                        cell = tb.cell(ri, ci)
                        cell.text = ""
                        runs(cell.paragraphs[0], r[ci] if ci < len(r) else "", size=9)
                        if ri == 0:
                            for rn in cell.paragraphs[0].runs:
                                rn.bold = True
                doc.add_paragraph()
            continue
        m = re.match(r"(#{1,4})\s+(.*)", ln)
        if m:
            doc.add_heading(m.group(2).replace("**", ""), min(len(m.group(1)), 3))
        elif re.match(r"\s*[-*]\s+", ln):
            runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", ln))
        elif ln.strip():
            runs(doc.add_paragraph(), ln)
        i += 1
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ pages
DOCX_MT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def page_users():
    d = db()
    st.subheader("Users")
    rows = d.table("app_users").select("username,role,active,created_at").order("created_at").execute().data
    st.dataframe(rows, use_container_width=True)
    me = st.session_state["user"]

    with st.form("add_user", clear_on_submit=True):
        st.markdown("**Add user**")
        c1, c2, c3 = st.columns(3)
        nu = c1.text_input("Username")
        npw = c2.text_input("Password (min 8 characters)", type="password")
        nr = c3.selectbox("Role", ["user", "admin"])
        if st.form_submit_button("Add user"):
            if not nu.strip() or len(npw) < 8:
                st.error("Username required and password must be at least 8 characters.")
            elif any(r["username"] == nu.strip() for r in rows):
                st.error("That username already exists.")
            else:
                salt = pysecrets.token_hex(16)
                d.table("app_users").insert({"username": nu.strip(), "salt": salt,
                    "password_hash": hash_pw(npw, salt), "role": nr, "active": True}).execute()
                st.success("User added.")
                st.rerun()

    names = [r["username"] for r in rows]
    if not names:
        return
    with st.form("manage_user"):
        st.markdown("**Reset password, deactivate or delete**")
        pick = st.selectbox("User", names)
        newpw = st.text_input("New password (leave blank to keep)", type="password")
        act = st.selectbox("Action", ["Reset password", "Deactivate", "Activate", "Delete"])
        if st.form_submit_button("Apply"):
            t = d.table("app_users")
            if pick == me and act in ("Deactivate", "Delete"):
                st.error("You cannot deactivate or delete your own account.")
            elif act == "Reset password":
                if len(newpw) < 8:
                    st.error("New password must be at least 8 characters.")
                else:
                    salt = pysecrets.token_hex(16)
                    t.update({"salt": salt, "password_hash": hash_pw(newpw, salt)}).eq("username", pick).execute()
                    st.success("Password updated.")
            elif act == "Delete":
                t.delete().eq("username", pick).execute()
                st.success("User deleted.")
                st.rerun()
            else:
                t.update({"active": act == "Activate"}).eq("username", pick).execute()
                st.success("Updated.")
                st.rerun()


def page_history():
    d = db()
    user, role = st.session_state["user"], st.session_state["role"]
    st.subheader("Audit history")
    cols = "id,created_at,username,client,product,audit_date"
    has_path = True
    try:
        q = d.table("audits").select(cols + ",docx_path").order("created_at", desc=True).limit(200)
        if role != "admin":
            q = q.eq("username", user)
        rows = q.execute().data
    except Exception:
        has_path = False
        q = d.table("audits").select(cols).order("created_at", desc=True).limit(200)
        if role != "admin":
            q = q.eq("username", user)
        rows = q.execute().data
    if not rows:
        st.info("No saved audits yet.")
        return
    st.dataframe([{k: v for k, v in r.items() if k != "docx_path"} for r in rows], use_container_width=True)
    label = {r["id"]: f'#{r["id"]} | {r["created_at"][:16]} | {r["product"] or "-"} | {r["username"]}' for r in rows}
    ids = list(label)
    start = ids.index(st.session_state.get("open_id")) if st.session_state.get("open_id") in ids else 0
    pick = st.selectbox("Open a report", ids, index=start, format_func=lambda i: label[i])
    q2 = d.table("audits").select("report,product").eq("id", pick)
    if role != "admin":
        q2 = q2.eq("username", user)
    got = q2.execute().data
    if got:
        rep = got[0]["report"]
        nm = re.sub(r"[^A-Za-z0-9_-]+", "_", got[0]["product"] or "label") + "_Label_Audit_Report"
        d1, d2 = st.columns(2)
        stored = None
        path = next((r.get("docx_path") for r in rows if r["id"] == pick), None) if has_path else None
        if path:
            try:
                stored = d.storage.from_("reports").download(path)
            except Exception:
                stored = None
        d1.download_button("Download Word report", stored or md_to_docx(rep), f"{nm}.docx", DOCX_MT, key="h_docx")
        d2.download_button("Download Markdown", rep, f"{nm}.md", "text/markdown", key="h_md")
        st.divider()
        st.markdown(rep)


def api_key():
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip().strip("\"'")


def call_claude(system, content, ph, live, effort=None):
    cl = claude_client.make_client(api_key())
    buf, n = "", 0
    with cl.messages.stream(model=MODEL, max_tokens=MAX_OUT, system=system,
                            extra_body={"output_config": {"effort": effort or EFFORT}},
                            messages=[{"role": "user", "content": content}]) as s:
        for t in s.text_stream:
            buf += t
            n += 1
            if n % 40 == 0:
                if live:
                    ph.markdown(buf)
                else:
                    ph.caption(f"Working... {len(buf):,} characters written")
        final = s.get_final_message()
    return buf, final.stop_reason


def save_history(report, docx_bytes, product, client_name, audit_date, files):
    d = db()
    if not d:
        return
    row = {"username": st.session_state["user"], "client": client_name, "product": product,
           "audit_date": audit_date.isoformat(), "files": ", ".join(getattr(f, "name", f) for f in files), "report": report}
    try:
        if docx_bytes:
            path = f"{st.session_state['user']}/{datetime.datetime.now():%Y%m%d_%H%M%S}.docx"
            d.storage.from_("reports").upload(path, docx_bytes, {"content-type": DOCX_MT})
            row["docx_path"] = path
    except Exception:
        row.pop("docx_path", None)
    try:
        try:
            d.table("audits").insert(row).execute()
        except Exception:
            row.pop("docx_path", None)
            d.table("audits").insert(row).execute()
        st.success("Report saved to History.")
    except Exception as e:
        st.warning(f"Report could not be saved to History: {e}")


def file_blocks(blobs):
    out = []
    for name, raw in blobs:
        data = base64.standard_b64encode(raw).decode()
        if name.lower().endswith(".pdf"):
            out.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}})
        else:
            mt = {"png": "image/png", "webp": "image/webp"}.get(name.lower().rsplit(".", 1)[-1], "image/jpeg")
            out.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
    return out


def grid_blocks(pdf_path):
    try:
        imgs = labelart.grid_images(pdf_path)
    except Exception:
        return []
    out = []
    for i, raw in enumerate(imgs, 1):
        out.append({"type": "text", "text": (f"Grid view of artwork page {i}, for reading positions: thin lines every 5 percent; the numbers "
                                              "on the top edge are percent of the page width and on the left edge percent of the page height.")})
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(raw).decode()}})
    return out


def create_label(skill_text, data, meta, blobs, pdf, work):
    content = file_blocks(blobs) + grid_blocks(pdf)
    content.append({"type": "text", "text": (
        f"{meta.get('pmap', '')}FINAL AUDIT REPORT (JSON):\n{json.dumps(data, ensure_ascii=False)}\n\n"
        "Prepare the corrected label artwork edits as described.")})
    system = [{"type": "text", "text": WRAPPER_LABEL},
              {"type": "text", "text": skill_text, "cache_control": {"type": "ephemeral"}}]
    ph = st.empty()
    buf, _ = call_claude(system, content, ph, live=False, effort=LABEL_EFFORT)
    ph.empty()
    ldata, _ = parse_answer(buf)
    edits = labelart.clean_edits(ldata.get("edits"))
    notes = [str(n) for n in ldata.get("notes", [])]
    if not edits:
        raise ValueError("The model returned no usable edits for the artwork.")
    final, blue = os.path.join(work, "final.pdf"), os.path.join(work, "final_blue.pdf")
    placed, n_a = labelart.build_label(pdf, edits, final, blue=False)
    labelart.build_label(pdf, edits, blue, blue=True)
    return {"pdf": open(final, "rb").read(), "pdf_blue": open(blue, "rb").read(),
            "png": labelart.render_pngs(final), "png_blue": labelart.render_pngs(blue),
            "notes": notes + n_a, "count": len(edits), "placed": placed}


def parse_answer(buf):
    """Returns (data, warning). Raises if nothing usable."""
    try:
        return fullreport.parse_json(buf), ""
    except Exception:
        pass
    data = fullreport.repair_json(buf)
    return data, ("The model's answer was cut off at the output limit. The report holds everything that was complete; "
                  "later parts (for example the last findings or the suggested label) may be missing. "
                  "Run it again with AUDIT_EFFORT set to high, or use the Quick text report, for a complete one.")


def finish_full(data, warn, pdf, work, meta, blobs, label, skill_text=None, with_label=False):
    st.session_state.pop("label", None)
    st.session_state.pop("label_error", None)
    revnote = str(data.pop("reviser_note", "") or "")
    info = {"note": ""}

    def post(dd):
        if db():
            try:
                info["note"] = libcheck.verify(db(), dd, api_key())
            except Exception as e:
                info["note"] = f"Library check could not run: {e}"

    with st.spinner("Checking the library, marking the artwork and building the Word report..."):
        out, marked, d = fullreport.finalize(data, pdf, SKILL_DIR, work, meta["product"], meta["client"], meta["date_str"], post=post)
    plain = open(out, "rb").read()
    lab = None
    if with_label and skill_text:
        try:
            with st.spinner("Creating the final label artwork..."):
                lab = create_label(skill_text, data, meta, blobs, pdf, work)
            labelart.append_to_docx(out, lab["png"], lab["png_blue"])
        except Exception as e:
            lab = None
            st.session_state["label_error"] = f"The report is ready, but the final label could not be created: {e}"
    docx_bytes = open(out, "rb").read()
    if lab:
        st.session_state["label"] = lab
    st.session_state["pdf"] = open(pdf, "rb").read()
    st.session_state["full"] = {
        "name": re.sub(r"[^A-Za-z0-9_-]+", "_", meta["product"] or "label") + "_Label_Audit_Report",
        "docx": docx_bytes, "docx_plain": plain, "marked": [open(m, "rb").read() for m in marked], "data": data,
        "rows": [{"Sr.": f["n"], "Severity": f["sev"], "Page": f["page"], "As printed": f["printed"],
                  "Deficiency": f["deficiency"], "Provision": f["prov"], "Correction": f["fix"],
                  "Library": f.get("lib_status", ""), "Box": f["box_source"]} for f in d["findings"]],
        "executive": d["executive"], "libnote": info["note"], "warn": warn, "revnote": revnote}
    save_history(fullreport.summary_markdown(d), docx_bytes, label, meta["client"], meta["date"], [n for n, _ in blobs])


REVISE_FULL = ("The current report is the JSON object below. Apply ONLY the change the user asks for, and return the COMPLETE "
               "updated JSON object in the same schema. Leave every other field as it is; if findings are removed or added, "
               "renumber nothing yourself (the app numbers them) and keep the order. Look at the label before you agree to a change: "
               "if the user says a finding is wrong but the label shows the defect, keep it. If the user supplies a fact "
               "(for example a figure from the formulation sheet), use it and say so. Add one extra key \"reviser_note\": a "
               "short plain statement of what you changed, and what you did not change and why. Keep the JSON compact.")


def render_label(skill_text):
    r = st.session_state.get("full")
    if not r:
        return
    st.markdown("**Final label artwork**")
    st.caption("Puts the corrected wording into your original artwork: text, tables and the veg mark. Logos, seals, QR codes and "
               "photographs are not redrawn. The notes say what a designer must do by hand.")
    if st.session_state.get("label_error"):
        st.warning(st.session_state["label_error"])
    if st.button("Create final label artwork" if not st.session_state.get("label") else "Create it again", key="mk_label"):
        if not api_key():
            st.error("ANTHROPIC_API_KEY is not set.")
            return
        meta, blobs = st.session_state["meta"], st.session_state["blobs"]
        work = tempfile.mkdtemp()
        pdf = os.path.join(work, "artwork.pdf")
        open(pdf, "wb").write(st.session_state["pdf"])
        try:
            with st.spinner("Creating the final label artwork..."):
                lab = create_label(skill_text, r["data"], meta, blobs, pdf, work)
            st.session_state["label"] = lab
            st.session_state.pop("label_error", None)
            try:  # the Word report gets the label pages too
                dp = os.path.join(work, "report_label.docx")
                open(dp, "wb").write(r.get("docx_plain") or r["docx"])
                labelart.append_to_docx(dp, lab["png"], lab["png_blue"])
                st.session_state["full"]["docx"] = open(dp, "rb").read()
            except Exception:
                pass
            st.rerun()
        except anthropic.APIError as e:
            st.error(f"API error: {e}")
        except Exception as e:
            st.error(f"Could not create the final label: {e}")
    lab = st.session_state.get("label")
    if lab:
        t1, t2 = st.tabs(["Final label", "Changes in blue"])
        with t1:
            for i, img in enumerate(lab["png"], 1):
                st.image(img, caption=f"Page {i}")
            st.download_button("Download final label (PDF)", lab["pdf"], f"{r['name']}_final_label.pdf", "application/pdf", key="dl_lab")
        with t2:
            for i, img in enumerate(lab["png_blue"], 1):
                st.image(img, caption=f"Page {i}")
            st.download_button("Download with changes in blue (PDF)", lab["pdf_blue"], f"{r['name']}_final_label_blue.pdf", "application/pdf", key="dl_lab_b")
        st.caption(f"{lab['placed']} of {lab['count']} changes placed. Check the label before it goes to print.")
        if lab["notes"]:
            with st.expander(f"Notes for the designer ({len(lab['notes'])})"):
                for n in lab["notes"]:
                    st.write("- " + n)


def render_revise(skill_text):
    full, quick = st.session_state.get("full"), st.session_state.get("report")
    if not (full or quick) or not st.session_state.get("blobs"):
        return
    st.divider()
    st.markdown("**Ask for changes**")
    st.caption("Tell the app what to correct, the way you would tell a colleague. It changes only that and rebuilds the report.")
    with st.form("revise", clear_on_submit=True):
        instr = st.text_area("What should be changed?", height=100,
                             placeholder="For example: make finding 3 Minor. Remove finding 7, the veg mark is correct. "
                                         "Add a finding for the missing batch number. Shorten the executive position.")
        go_ = st.form_submit_button("Apply changes", type="primary")
    if not go_ or not instr.strip():
        return
    if not api_key():
        st.error("ANTHROPIC_API_KEY is not set.")
        return
    meta, blobs = st.session_state["meta"], st.session_state["blobs"]
    content, ph = file_blocks(blobs), st.empty()
    try:
        if full:
            content.append({"type": "text", "text": (
                f"{REVISE_FULL}\n\nCURRENT REPORT JSON:\n{json.dumps(full['data'], ensure_ascii=False)}\n\n"
                f"CHANGE REQUESTED BY THE USER:\n{instr.strip()}")})
            system = [{"type": "text", "text": WRAPPER_FULL},
                      {"type": "text", "text": skill_text, "cache_control": {"type": "ephemeral"}}]
            with st.spinner("Applying your changes..."):
                buf, stop = call_claude(system, content, ph, live=False, effort=REVISE_EFFORT)
            ph.empty()
            try:
                data, warn = parse_answer(buf)
            except Exception:
                st.error("The revised answer could not be read. Nothing was changed. Try again, or word the change more simply.")
                return
            work = tempfile.mkdtemp()
            pdf = os.path.join(work, "artwork.pdf")
            open(pdf, "wb").write(st.session_state["pdf"])
            finish_full(data, warn, pdf, work, meta, blobs, (meta["product"] or "label") + " (revised)",
                        skill_text=skill_text, with_label=bool(st.session_state.get("label")))
        else:
            content.append({"type": "text", "text": (
                f"CURRENT REPORT:\n{quick}\n\nCHANGE REQUESTED BY THE USER:\n{instr.strip()}\n\n"
                "Return the complete updated report in the same Markdown structure. Change only what the user asks. "
                "Check the label before agreeing; if the label shows the defect, keep the finding and say why at the end.")})
            system = [{"type": "text", "text": WRAPPER},
                      {"type": "text", "text": skill_text, "cache_control": {"type": "ephemeral"}}]
            with st.spinner("Applying your changes..."):
                buf, stop = call_claude(system, content, ph, live=False, effort=REVISE_EFFORT)
            ph.empty()
            st.session_state["report"] = buf
            save_history(buf, None, (meta["product"] or "label") + " (revised)", meta["client"], meta["date"], [n for n, _ in blobs])
        st.rerun()
    except anthropic.APIError as e:
        st.error(f"API error: {e}")
    except Exception as e:
        st.error(f"Could not apply the change: {e}")


def page_audit(skill_text, est_tokens):
    if not skill_text.strip():
        st.error("The skills/fssai-label-audit folder is empty. Place the skill files in it.")
        return
    with st.container(border=True):
        st.markdown(f'<div class="hint">New audit in {APP_TITLE}</div>', unsafe_allow_html=True)
        product = st.text_input("Product name", placeholder="Product name, for example Vitalmax Joint Care Capsules",
                                label_visibility="collapsed")
        files = st.file_uploader("Add the label panels (images or PDF). Upload every panel.",
                                 type=["png", "jpg", "jpeg", "webp", "pdf"], accept_multiple_files=True)
        with st.expander("More details (optional)"):
            c1, c2 = st.columns(2)
            client_name = c1.text_input("Client / case")
            audit_date = c2.date_input("Audit date", datetime.date.today())
            listing = st.text_area("Online listing text: title, description, price, seller details", height=110)
            notes = st.text_area("Extra notes: usage, formulation sheet figures, anything known", height=80)
        make_label = st.checkbox("Also create the final label artwork (the corrected label, added to the Word report)", value=True)
        b1, b2, b3 = st.columns([3, 2, 1.6])
        mode = b1.selectbox("Report type", ["Full report with marked artwork (Word)", "Quick text report"],
                            label_visibility="collapsed")
        b2.markdown(f'<div class="badge">{model_label()}</div>', unsafe_allow_html=True)
        run = b3.button("Run audit", type="primary", disabled=not files, use_container_width=True)

    if run:
        full = mode.startswith("Full")
        if sum(f.size for f in files) > MAX_UPLOAD_MB * 1024 * 1024:
            st.error(f"Keep the total upload under {MAX_UPLOAD_MB} MB.")
            return
        if est_tokens > MAX_CTX:
            st.error("The skill files exceed the context limit. The admin must set EXCLUDE_FILES.")
            return
        if not api_key():
            st.error("ANTHROPIC_API_KEY is not set.")
            return
        for k in ("report", "name", "full", "blobs", "meta", "pdf", "label", "label_error"):
            st.session_state.pop(k, None)
        blobs = [(f.name, f.getvalue()) for f in files]
        meta = {"product": product, "client": client_name, "date": audit_date, "date_str": audit_date.strftime("%d.%m.%Y")}
        work = tempfile.mkdtemp()
        pdf, pmap_text = os.path.join(work, "artwork.pdf"), ""
        try:
            content = file_blocks(blobs)
            if full:
                pmap = fullreport.build_artwork(blobs, pdf)
                pmap_text = "Artwork pages in order (page numbers for the findings):\n" + \
                    "\n".join(f"Page {i}: {t}" for i, t in enumerate(pmap, 1)) + "\n\n"
                meta["pmap"] = pmap_text
                content += grid_blocks(pdf)
        except Exception as e:
            st.error(f"Could not read the uploaded files: {e}")
            return
        task = ("Run Steps 1 to 4 of the skill fully and return the JSON object described in the environment overrides."
                if full else
                "Run Steps 1 to 4 of the skill fully and write the report in the Markdown structure set out in the environment overrides.")
        content.append({"type": "text", "text": (
            f"Audit this label.\nClient: {client_name or 'not given'}\nProduct: {product or 'not given'}\n"
            f"Audit date: {meta['date_str']}\n{pmap_text}"
            f"Online listing text:\n{listing or 'none supplied'}\n\nNotes:\n{notes or 'none'}\n\n{task}")})
        system = [{"type": "text", "text": WRAPPER_FULL if full else WRAPPER},
                  {"type": "text", "text": skill_text, "cache_control": {"type": "ephemeral"}}]
        ph = st.empty()
        try:
            with st.spinner("Audit in progress. This can take 3 to 10 minutes."):
                buf, stop = call_claude(system, content, ph, live=not full)
            ph.empty()
            st.session_state["blobs"], st.session_state["meta"] = blobs, meta
            if not full:
                if stop == "max_tokens":
                    buf += "\n\n**[The report stopped at the output limit. The admin can raise MAX_OUTPUT_TOKENS.]**"
                st.session_state["report"] = buf
                st.session_state["name"] = re.sub(r"[^A-Za-z0-9_-]+", "_", product or "label") + "_Label_Audit_Report"
                save_history(buf, None, product, client_name, audit_date, [n for n, _ in blobs])
            else:
                try:
                    data, warn = parse_answer(buf)
                except Exception:
                    with st.expander("Raw model output"):
                        st.code(buf[:20000])
                    st.error("The model's answer was not valid JSON" + (" (it hit the output limit)." if stop == "max_tokens" else ".")
                             + " Run the audit again, set AUDIT_EFFORT to high, or use the Quick text report.")
                    return
                finish_full(data, warn, pdf, work, meta, blobs, product, skill_text=skill_text, with_label=make_label)
        except anthropic.APIError as e:
            st.error(f"API error: {e}")
        except Exception as e:
            st.error(f"Could not build the report: {e}")

    if st.session_state.get("full"):
        r = st.session_state["full"]
        st.download_button("Download Word report", r["docx"], f"{r['name']}.docx", DOCX_MT, type="primary")
        if r.get("warn"):
            st.warning(r["warn"])
        if r.get("revnote"):
            st.info("About the last change: " + r["revnote"])
        st.markdown("**Executive position**")
        st.write(r["executive"])
        st.markdown("**Marked artwork**")
        for i, img in enumerate(r["marked"], 1):
            st.image(img, caption=f"Artwork page {i}")
        st.markdown("**Deficiency schedule**")
        st.caption(r.get("libnote") or "Library check not run (no library loaded).")
        st.dataframe(r["rows"], use_container_width=True)
        st.caption("Box: text = found on the label; estimate = placed from the model's estimate, check it in the Word report.")
        render_label(skill_text)
    elif st.session_state.get("report"):
        rep, nm = st.session_state["report"], st.session_state.get("name", "Label_Audit_Report")
        d1, d2 = st.columns(2)
        d1.download_button("Download Word report", md_to_docx(rep), f"{nm}.docx", DOCX_MT)
        d2.download_button("Download Markdown", rep, f"{nm}.md", "text/markdown")
        st.divider()
        st.markdown(rep)
    render_revise(skill_text)


# ------------------------------------------------------------------ project home
@st.cache_data(ttl=90)
def panel_stats():
    out, sb = {}, db()
    if not sb:
        return out
    try:
        f = sb.table("library_files").select("pages").execute().data
        out["lib_files"], out["lib_pages"] = len(f), sum(x["pages"] or 0 for x in f)
    except Exception:
        pass
    try:
        out["sheets"] = len(sb.table("ledger_sheets").select("sheet").execute().data)
        out["rows"] = sb.table("ledger_rows").select("sheet", count="exact").limit(1).execute().count or 0
    except Exception:
        pass
    try:
        r = sb.table("scan_seen").select("first_seen").order("first_seen", desc=True).limit(1).execute().data
        out["scan"] = r[0]["first_seen"] if r else None
        out["pending"] = len(sb.table("updates_inbox").select("id").in_("status", ["pending", "needs_pdf"]).execute().data)
    except Exception:
        pass
    return out


def go(menu, open_id=None):
    st.session_state["menu"] = menu
    if open_id is not None:
        st.session_state["open_id"] = open_id


def render_recents(user, role):
    if not db():
        return
    try:
        q = db().table("audits").select("id,created_at,product,client,username").order("created_at", desc=True).limit(8)
        if role != "admin":
            q = q.eq("username", user)
        rows = q.execute().data
    except Exception:
        return
    st.markdown('<div class="psec">Recents</div>', unsafe_allow_html=True)
    if not rows:
        st.caption("No audits yet. Your audits will appear here.")
        return
    try:
        box = st.container(key="recents")
    except TypeError:
        box = st.container()
    with box:
        for r in rows:
            c1, c2 = st.columns([6, 1.6])
            c1.button((r["product"] or "Untitled audit") + (f"  |  {r['client']}" if r.get("client") else ""),
                      key=f"rc{r['id']}", use_container_width=True, on_click=go, args=("History", r["id"]))
            c2.markdown(f'<div class="ago">{ago(r["created_at"])}</div>', unsafe_allow_html=True)


def render_panel(role, sizes, est_tokens):
    stt = panel_stats()
    try:
        box = st.container(key="panel")
    except TypeError:
        box = st.container()
    with box:
        st.markdown(f"**:material/description: Instructions**")
        st.markdown(f'<div class="pmeta">{len(sizes)} engine files, about {est_tokens // 1000}k tokens</div>', unsafe_allow_html=True)
        if role == "admin" and db():
            st.button("Manage", key="p_man", on_click=go, args=("Updates and ledger",))
        st.divider()
        st.markdown("**:material/folder_open: Context**")
        if "lib_files" in stt:
            st.markdown(f'<div class="pmeta">{stt["lib_files"]} library PDFs, {stt["lib_pages"]:,} pages</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="pmeta">Library not loaded</div>', unsafe_allow_html=True)
        st.divider()
        st.markdown("**:material/table_chart: Control ledger**")
        if stt.get("rows"):
            st.markdown(f'<div class="pmeta">{stt["rows"]:,} rows in {stt.get("sheets", 0)} sheets</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="pmeta">Not loaded</div>', unsafe_allow_html=True)
        st.divider()
        st.markdown("**:material/schedule: Scheduled**")
        last = ago(stt["scan"]) if stt.get("scan") else "not run yet"
        wait = f", {stt['pending']} waiting for review" if stt.get("pending") else ""
        st.markdown(f'<div class="pmeta">FSSAI weekly amendment scan, last run {last}{wait}</div>', unsafe_allow_html=True)
        if role == "admin" and db():
            st.button("Open inbox", key="p_inb", on_click=go, args=("Updates and ledger",))
        st.markdown('<div class="psec">Private</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ main
def main():
    st.set_page_config(page_title="FSSAI Label Audit", layout="wide")
    if not login():
        return
    st.markdown(CSS, unsafe_allow_html=True)
    user, role = st.session_state["user"], st.session_state["role"]
    skill_text, sizes = load_skill(updates.skill_stamp(db()) if db() else "")
    est_tokens = int(len(skill_text) / 3.2)
    pages = ["New audit"]
    if db():
        pages.append("History")
        if role == "admin":
            pages.append("Updates and ledger")
            pages.append("Users")
    if st.session_state.get("menu") not in pages:
        st.session_state["menu"] = "New audit"

    with st.sidebar:
        st.markdown(f"**{APP_TITLE.title()}**")
        page = st.radio("Menu", pages, key="menu", label_visibility="collapsed")
        st.caption(f"Signed in as {user} ({role})")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()
        if role == "admin":
            with st.expander("Admin"):
                for n, c in sizes:
                    st.caption(f"{n}: {c:,} chars")
                st.caption(f"Approx tokens: {est_tokens:,} (limit {MAX_CTX:,})")
                st.caption(f"Model: {MODEL} | effort: {EFFORT}")
                st.caption("History and users: " + ("on" if db() else "off (Supabase not configured)"))
                if db():
                    st.caption("Library loaded: " + ("yes" if libcheck.library_ready(db()) else "no"))
                if st.button("Test API key"):
                    k = os.getenv("ANTHROPIC_API_KEY") or ""
                    if not k:
                        st.error("ANTHROPIC_API_KEY is not set in the app settings.")
                    else:
                        st.caption(f"Key seen by the app: {k[:7]}...{k[-4:]}  | length {len(k)} | "
                                   f"starts with sk-ant-: {k.startswith('sk-ant-')} | has spaces or quotes: "
                                   f"{k != k.strip() or chr(34) in k or chr(39) in k or ' ' in k}")
                        try:
                            claude_client.make_client(k.strip()).messages.create(
                                model="claude-haiku-5-5", max_tokens=5, messages=[{"role": "user", "content": "Say OK"}])
                            st.success("The key works.")
                        except Exception as e:
                            st.error(f"The key was refused: {e}")
                if est_tokens > MAX_CTX:
                    st.error("The skill files are too large. Add some files to EXCLUDE_FILES.")

    header(page == "New audit")
    if page == "History":
        page_history()
    elif page == "Users":
        page_users()
    elif page == "Updates and ledger":
        updates.page_updates(db(), user, {"api_key": api_key(), "model": MODEL, "skill_dir": SKILL_DIR})
    else:
        left, right = st.columns([2.1, 1], gap="large")
        with left:
            page_audit(skill_text, est_tokens)
            render_recents(user, role)
        with right:
            render_panel(role, sizes, est_tokens)


main()