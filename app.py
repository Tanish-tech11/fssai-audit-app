"""FSSAI Nutraceutical Label Audit - web app (Streamlit + Claude API)."""
import base64, datetime, hashlib, hmac, io, os, re, secrets as pysecrets
from pathlib import Path

import anthropic
import streamlit as st

BASE = Path(__file__).parent
SKILL_DIR = Path(os.getenv("SKILL_DIR", BASE / "skills" / "fssai-label-audit"))
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
MAX_OUT = int(os.getenv("MAX_OUTPUT_TOKENS", "64000"))
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
    st.title("FSSAI Label Audit")
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
    q = d.table("audits").select("id,created_at,username,client,product,audit_date").order("created_at", desc=True).limit(200)
    if role != "admin":
        q = q.eq("username", user)
    rows = q.execute().data
    if not rows:
        st.info("No saved audits yet.")
        return
    st.dataframe(rows, use_container_width=True)
    label = {r["id"]: f'#{r["id"]} | {r["created_at"][:16]} | {r["product"] or "-"} | {r["username"]}' for r in rows}
    pick = st.selectbox("Open a report", list(label), format_func=lambda i: label[i])
    q2 = d.table("audits").select("report,product").eq("id", pick)
    if role != "admin":
        q2 = q2.eq("username", user)
    got = q2.execute().data
    if got:
        rep = got[0]["report"]
        nm = re.sub(r"[^A-Za-z0-9_-]+", "_", got[0]["product"] or "label") + "_Label_Audit_Report"
        d1, d2 = st.columns(2)
        d1.download_button("Download Word report", md_to_docx(rep), f"{nm}.docx", DOCX_MT, key="h_docx")
        d2.download_button("Download Markdown", rep, f"{nm}.md", "text/markdown", key="h_md")
        st.divider()
        st.markdown(rep)


def page_audit(skill_text, est_tokens):
    st.subheader("New audit")
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
                                        extra_body={"output_config": {"effort": EFFORT}},
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
            if db():
                try:
                    db().table("audits").insert({
                        "username": st.session_state["user"], "client": client_name, "product": product,
                        "audit_date": audit_date.isoformat(), "files": ", ".join(f.name for f in files),
                        "report": buf}).execute()
                    st.success("Report saved to History.")
                except Exception as e:
                    st.warning(f"Report could not be saved to History: {e}")
        except anthropic.APIError as e:
            st.error(f"API error: {e}")

    if st.session_state.get("report"):
        rep, nm = st.session_state["report"], st.session_state["name"]
        d1, d2 = st.columns(2)
        d1.download_button("Download Word report", md_to_docx(rep), f"{nm}.docx", DOCX_MT)
        d2.download_button("Download Markdown", rep, f"{nm}.md", "text/markdown")
        st.divider()
        st.markdown(rep)


# ------------------------------------------------------------------ main
def main():
    st.set_page_config(page_title="FSSAI Label Audit", layout="wide")
    if not login():
        return
    user, role = st.session_state["user"], st.session_state["role"]
    skill_text, sizes = load_skill()
    est_tokens = int(len(skill_text) / 3.2)
    pages = ["New audit"]
    if db():
        pages.append("History")
        if role == "admin":
            pages.append("Users")

    with st.sidebar:
        st.write(f"Login: **{user}** ({role})")
        page = st.radio("Menu", pages)
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()
        if role == "admin":
            st.divider()
            st.caption("Admin: skill files loaded")
            for n, c in sizes:
                st.caption(f"{n}: {c:,} chars")
            st.caption(f"Approx tokens: {est_tokens:,} (limit {MAX_CTX:,})")
            st.caption(f"Model: {MODEL} | effort: {EFFORT}")
            st.caption("History and users: " + ("on" if db() else "off (Supabase not configured)"))
            if est_tokens > MAX_CTX:
                st.error("The skill files are too large. Add some files to EXCLUDE_FILES.")

    st.title("FSSAI Nutraceutical Label Audit")
    if page == "History":
        page_history()
    elif page == "Users":
        page_users()
    else:
        page_audit(skill_text, est_tokens)


main()