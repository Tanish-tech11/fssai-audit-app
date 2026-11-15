"""Check each finding against the real library pages stored in Supabase."""
import os

import anthropic

import claude_client
import fullreport

VERIFY_MODEL = os.getenv("VERIFY_MODEL", "claude-sonnet-5-5")
PAGE_CHARS = 5000
PER_FINDING = 5


def library_ready(sb):
    try:
        return bool(sb.table("library_files").select("file").limit(1).execute().data)
    except Exception:
        return False


def _search(sb, terms):
    seen, out = set(), []
    for t in terms:
        t = " ".join(str(t).split())
        if not t:
            continue
        rows = []
        for q in (t, " or ".join(t.split())):
            try:
                rows = sb.rpc("search_library", {"q": q, "n": 3}).execute().data
            except Exception:
                rows = []
            if rows:
                break
        for r in rows:
            k = (r["file"], r["page"])
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out[:PER_FINDING]


def _short(path):
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def verify(sb, d, api_key):
    """Adds library results to d in place. Returns a one-line summary, or '' if nothing was checked."""
    if not library_ready(sb):
        return ""
    cands, blocks, cid = {}, [], 0
    for f in d["findings"]:
        terms = f.get("search_terms") or [f["prov"][:80]]
        rows = _search(sb, terms)
        lines = [f"### Finding {f['n']}", f"Provision relied on: {f['prov']}", f"Deficiency: {f['deficiency']}", "Candidate pages:"]
        if not rows:
            lines.append("(none found)")
        for r in rows:
            cid += 1
            cands[f"C{cid}"] = r
            lines.append(f"[C{cid}] {r['file']} | PDF page {r['page']}\n{r['text'][:PAGE_CHARS]}")
        blocks.append("\n".join(lines))
    prompt = (
        "You check audit findings against pages of the official regulation library. For each finding, decide whether "
        "any candidate page itself states the requirement that the finding relies on. Be strict: a page that only "
        "mentions the topic does not verify the finding. Never invent a page; use only the candidate ids given.\n"
        'Return ONE JSON object only: {"results": [{"n": 1, "status": "verified" | "partial" | "not_found", '
        '"pages": ["C1"], "note": "one short sentence"}]}\n\n' + "\n\n".join(blocks))
    cl = claude_client.make_client(api_key)
    resp = cl.messages.create(model=VERIFY_MODEL, max_tokens=8000, messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    results = {int(r["n"]): r for r in fullreport.parse_json(text).get("results", []) if "n" in r}
    ok = part = miss = 0
    for f in d["findings"]:
        r = results.get(f["n"], {})
        st = r.get("status", "not_found")
        pages = [cands[c] for c in r.get("pages", []) if c in cands]
        cite = "; ".join(f"{_short(p['file'])}, PDF p. {p['page']}" for p in pages)
        if st == "verified" and pages:
            f["lib_status"] = "verified"
            f["prov"] += f" [Library: verified, {cite}]"
            d["sources_verified"].append([f"Finding {f['n']}: {f['prov'][:120]}", cite])
            ok += 1
        elif st == "partial" and pages:
            f["lib_status"] = "partial"
            f["prov"] += f" [Library: partly supported, {cite}]"
            d["sources_verified"].append([f"Finding {f['n']} (partly supported)", cite])
            part += 1
        else:
            f["lib_status"] = "not confirmed"
            f["prov"] += " [Library: not confirmed from the library pages]"
            d["sources_unverified"].append(f"Finding {f['n']}: provision not confirmed against the library text.")
            miss += 1
    return f"Library check: {ok} verified, {part} partly supported, {miss} not confirmed."