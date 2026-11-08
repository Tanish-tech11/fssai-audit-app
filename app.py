"""FSSAI Nutraceutical Label Audit - web app (Streamlit + Claude API)."""
import base64, datetime, hmac, io, os, re
from pathlib import Path

import anthropic
import streamlit as st

BASE = Path(__file__).parent
SKILL_DIR = Path(os.getenv("SKILL_DIR", BASE / "skills" / "fssai-label-audit"))
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
MAX_OUT = int(os.getenv("MAX_OUTPUT_TOKENS", "32000"))
MAX_CTX = int(os.getenv("MAX_CONTEXT_TOKENS", "170000"))
EXCLUDE = {x.strip() for x in os.getenv("EXCLUDE_FILES", "").split(",") if x.strip()}
SKIP_SHEETS = [x.strip().lower() for x in os.getenv("SKIP_SHEETS", "schedule").split(",") if x.strip()]
MAX_UPLOAD_MB = 30

WRAPPER = """You are the FSSAI Label Audit Engine running inside a web application. The reference files that follow are your skill (00_SKILL.md to 05_templates.md, plus reference data). Follow them for method, checklist, severity, composition rationality test, exposure and tone.

Environment overrides for this web app. These win over the skill wherever they conflict:
1. There is no file system, no Projects tool, no computer link, no OCR tool and no other skill. Ignore every Windows path and every instruction to read, save or build files. Read the label directly from the uploaded images or PDFs.
2. The legal library (the PDFs in folders 01 to 11) and the control ledger are NOT available here. Cite a provision only from the reference files given to you, with the library page numbers they carry. Anything you cannot confirm from them is marked UTV or unverified. Never cite from memory. Never invent or infer a Schedule entry.
3. Do not run 07_report_builder.py and do not produce marked or corrected artwork images. Write the report as Markdown with these sections in order: 1 Product identification; 2 Executive position; 3 Deficiency schedule (table with columns Sr., As printed, Deficiency, Provision (N22 and N16), Severity as Critical, Major or Minor, Correction); 4 Online listing findings (only if listing text was supplied); 5 Composition and rationality (ingredient table, dose reconciliation, conclusion); 6 Checklist status (every point NC, C, UTV or NA, compact table grouped by Block); 7 Unable to verify; 8 Exposure under the four heads and the forum map; 9 Recommended course; 10 Corrected wording for each finding; 11 Suggested compliant label text (changed text inside [[double square brackets]]); 12 Sources relied on, verified and unverified.
4. Never certify a label as compliant. No em dashes. Write in English. Use the audit date given by the user."""


# ------------------------------------------------------------------ skill loading
def _order(p: Path):
    m = re.match(r"(\d+)([A-Za-z]?)", p.name)
    return (int(m.group(1)), m.group(2)) if m else (999, p.name)


@st.cache_resource
def load_skill():
    parts = []
    for p in sorted(SKILL_DIR.glob("*.md"), key=_order):
        if p.name in EXCLUDE:
            continue
        parts.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
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


# ------------------------------------------------------------------ login
def users():
    d = {}
    for item in os.getenv("APP_USERS", "").split(";"):
        if ":" in item:
            u, p = item.split(":", 1)
            d[u.strip()] = p.strip()
    return d


def login():
    if st.session_state.get("user"):
        return True
    st.title("FSSAI Label Audit")
    db = users()
    if not db:
        st.error("APP_USERS is not set. The admin must add APP_USERS in the hosting environment settings.")
        return False
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Login")
    if ok:
        if u in db and hmac.compare_digest(db[u].encode(), p.encode()):
            st.session_state["user"] = u
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


# ------------------------------------------------------------------ main
def main():
    st.set_page_config(page_title="FSSAI Label Audit", layout="wide")
    if not login():
        return
    user = st.session_state["user"]
    admins = {x.strip() for x in os.getenv("ADMIN_USERS", "").split(",")}
    skill_text, sizes = load_skill()
    est_tokens = int(len(skill_text) / 3.2)

    with st.sidebar:
        st.write(f"Login: **{user}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()
        if user in admins:
            st.divider()
            st.caption("Admin: skill files loaded")
            for n, c in sizes:
                st.caption(f"{n}: {c:,} chars")
            st.caption(f"Approx tokens: {est_tokens:,} (limit {MAX_CTX:,})")
            st.caption(f"Model: {MODEL}")
            if est_tokens > MAX_CTX:
                st.error("The skill files are too large. Add some files to EXCLUDE_FILES.")

    st.title("FSSAI Nutraceutical Label Audit")
    if not skill_text.strip():
        st.error("The skills/fssai-label-audit folder is empty. Place the skill files in it.")
        return

    c1, c2 = st.columns(2)
    client_name = c1.text_input("Client / case")
    product = c2.text_input("Product name")
    audit_date = st.date_input("Audit date", datetime.date.today())
    files = st.file_uploader("Label (images or PDF). Upload all panels.",
                             type=["png", "jpg", "jpeg", "webp", "pdf"], accept_multiple_files=True)
    listing = st.text_area("Online listing text (optional): title, description, price, seller details", height=120)
    notes = st.text_area("Extra notes (optional): usage, formulation sheet figures, anything known", height=80)

    if st.button("Run audit", type="primary", disabled=not files):
        total = sum(f.size for f in files)
        if total > MAX_UPLOAD_MB * 1024 * 1024:
            st.error(f"Keep the total upload under {MAX_UPLOAD_MB} MB.")
            return
        if est_tokens > MAX_CTX:
            st.error("The skill files exceed the context limit. The admin must set EXCLUDE_FILES.")
            return
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            st.error("ANTHROPIC_API_KEY is not set.")
            return
        content = []
        for f in files:
            data = base64.standard_b64encode(f.getvalue()).decode()
            if f.name.lower().endswith(".pdf"):
                content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}})
            else:
                mt = {"png": "image/png", "webp": "image/webp"}.get(f.name.lower().rsplit(".", 1)[-1], "image/jpeg")
                content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
        content.append({"type": "text", "text": (
            f"Audit this label.\nClient: {client_name or 'not given'}\nProduct: {product or 'not given'}\n"
            f"Audit date: {audit_date.strftime('%d.%m.%Y')}\n"
            f"Online listing text:\n{listing or 'none supplied'}\n\nNotes:\n{notes or 'none'}\n\n"
            "Run Steps 1 to 4 of the skill fully and write the report in the Markdown structure set out in the environment overrides.")})
        system = [{"type": "text", "text": WRAPPER},
                  {"type": "text", "text": skill_text, "cache_control": {"type": "ephemeral"}}]
        ph = st.empty()
        buf, n = "", 0
        try:
            cl = anthropic.Anthropic(api_key=key)
            with st.spinner("Audit in progress. This can take 2 to 6 minutes."):
                with cl.messages.stream(model=MODEL, max_tokens=MAX_OUT, system=system,
                                        messages=[{"role": "user", "content": content}]) as s:
                    for t in s.text_stream:
                        buf += t
                        n += 1
                        if n % 40 == 0:
                            ph.markdown(buf)
                    final = s.get_final_message()
            ph.empty()
            if final.stop_reason == "max_tokens":
                buf += "\n\n**[The report stopped at the output limit. The admin can raise MAX_OUTPUT_TOKENS.]**"
            st.session_state["report"] = buf
            st.session_state["name"] = re.sub(r"[^A-Za-z0-9_-]+", "_", product or "label") + "_Label_Audit_Report"
        except anthropic.APIError as e:
            st.error(f"API error: {e}")

    if st.session_state.get("report"):
        rep, nm = st.session_state["report"], st.session_state["name"]
        d1, d2 = st.columns(2)
        d1.download_button("Download Word report", md_to_docx(rep), f"{nm}.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        d2.download_button("Download Markdown", rep, f"{nm}.md", "text/markdown")
        st.divider()
        st.markdown(rep)


main()