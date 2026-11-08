"""Full report pipeline: artwork PDF, locating findings on the label, client's report builder."""
import difflib, importlib.util, io, json, os, re
from pathlib import Path

import fitz
from PIL import Image, ImageFont, ImageOps

MATCH_MIN = 0.72
SEVS = {"critical": "Critical", "major": "Major", "minor": "Minor"}


# ------------------------------------------------------------------ artwork
def build_artwork(files, out_pdf):
    """files: list of (name, bytes). Writes one combined PDF, returns a list describing each page."""
    doc = fitz.open()
    pmap = []
    for name, data in files:
        if name.lower().endswith(".pdf"):
            src = fitz.open(stream=data, filetype="pdf")
            doc.insert_pdf(src)
            pmap.extend(f"{name} (page {i + 1})" for i in range(len(src)))
        else:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            if im.width > 2400:
                im = im.resize((2400, int(im.height * 2400 / im.width)))
            pw = 595.0
            ph = pw * im.height / im.width
            page = doc.new_page(width=pw, height=ph)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=90)
            page.insert_image(fitz.Rect(0, 0, pw, ph), stream=buf.getvalue())
            pmap.append(name)
    doc.save(out_pdf)
    return pmap


# ------------------------------------------------------------------ locating text on the label
def _norm(s):
    return re.sub(r"[^0-9a-z%]+", "", s.lower())


def page_words(page):
    """Words with boxes in PDF points: text layer if there is one, otherwise OCR."""
    words = page.get_text("words")
    if len(words) >= 8:
        return [(w[4], fitz.Rect(w[:4])) for w in words]
    try:
        import pytesseract
        dpi = 250
        pix = page.get_pixmap(dpi=dpi)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        d = pytesseract.image_to_data(im, lang=os.getenv("OCR_LANG", "eng"), output_type=pytesseract.Output.DICT)
        k = 72 / dpi
        out = []
        for t, l, tp, w, h, c in zip(d["text"], d["left"], d["top"], d["width"], d["height"], d["conf"]):
            if t.strip() and float(c) >= 30:
                out.append((t, fitz.Rect(l * k, tp * k, (l + w) * k, (tp + h) * k)))
        return out
    except Exception:
        return []


def locate(anchor, words):
    at = [t for t in (_norm(x) for x in anchor.split()) if t]
    if not at or not words:
        return 0.0, None
    wt = [_norm(w[0]) for w in words]
    target = " ".join(at)
    n = len(at)
    best, rect = 0.0, None
    for size in sorted({max(1, n - 1), n, n + 1}):
        for i in range(0, len(wt) - size + 1):
            cand = " ".join(t for t in wt[i:i + size] if t)
            if not cand:
                continue
            sc = difflib.SequenceMatcher(None, target, cand).ratio()
            if sc > best:
                best = sc
                r = fitz.Rect(words[i][1])
                for w in words[i + 1:i + size]:
                    r.include_rect(w[1])
                rect = r
    return best, rect


def _norm_box(nb, page_rect):
    try:
        x0, y0, x1, y1 = [min(max(float(v), 0.0), 1.0) for v in nb]
    except Exception:
        return None
    if x1 - x0 < 0.01 or y1 - y0 < 0.005:
        return None
    w, h = page_rect.width, page_rect.height
    return fitz.Rect(x0 * w, y0 * h, x1 * w, y1 * h)


def resolve_boxes(findings, doc):
    cache = {}

    def words(p):
        if p not in cache:
            cache[p] = page_words(doc[p - 1])
        return cache[p]

    N = len(doc)
    for f in findings:
        p = min(max(int(f.get("page") or 1), 1), N)
        f["page"] = p
        pr = doc[p - 1].rect
        anchor = str(f.get("anchor") or "").strip()
        rect, src = None, "default"
        if f.get("missing") and f.get("box_norm"):
            rect = _norm_box(f["box_norm"], pr)
            src = "estimate" if rect else src
        if rect is None and anchor:
            best = (0.0, None, p)
            for q in [p] + [q for q in range(1, N + 1) if q != p]:
                sc, r = locate(anchor, words(q))
                if sc > best[0]:
                    best = (sc, r, q)
                if sc >= 0.9:
                    break
            if best[0] >= MATCH_MIN:
                rect, src, f["page"] = best[1], "text", best[2]
                pr = doc[f["page"] - 1].rect
        if rect is None and f.get("box_norm"):
            rect = _norm_box(f["box_norm"], pr)
            src = "estimate" if rect else src
        if rect is None:
            rect = fitz.Rect(30, 30, pr.width - 30, 70)
        rect = rect & pr
        if rect.is_empty or rect.width < 8 or rect.height < 8:
            rect = fitz.Rect(rect.x0, rect.y0, rect.x0 + max(rect.width, 8), rect.y0 + max(rect.height, 8))
        f["box"] = [rect.x0, rect.y0, rect.x1, rect.y1]
        f["box_source"] = src
    return findings


# ------------------------------------------------------------------ data clean-up
def parse_json(text):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1])


def _clean(o):
    if isinstance(o, str):
        return o.replace("\u2014", " - ")
    if isinstance(o, list):
        return [_clean(x) for x in o]
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    return o


def _s(v):
    return "" if v is None else str(v)


def _rows(rows, n):
    out = []
    for r in rows or []:
        r = list(r) if isinstance(r, (list, tuple)) else [r]
        out.append([_s(x) for x in (r + [""] * n)[:n]])
    return out


def normalize(data, product, client, audit_date):
    d = _clean(data)
    d["product"] = _s(d.get("product")) or product or "Product"
    d["client"] = _s(d.get("client")) or client or ""
    d["audit_date"] = audit_date
    d["identification"] = _rows(d.get("identification"), 2)
    d["executive"] = _s(d.get("executive"))
    fl = []
    for i, f in enumerate(d.get("findings") or [], 1):
        if not isinstance(f, dict):
            continue
        sev = SEVS.get(_s(f.get("sev")).strip().lower(), "Major")
        g = {k: _s(f.get(k)) for k in ("printed", "deficiency", "prov", "fix", "remark", "anchor", "over", "side")}
        g.update(n=i, sev=sev, page=f.get("page") or 1, missing=bool(f.get("missing")),
                 box_norm=f.get("box_norm"),
                 search_terms=[_s(x) for x in (f.get("search_terms") or []) if _s(x).strip()][:3])
        if g["side"] not in ("L", "R", "T", "B"):
            g.pop("side")
        if not g["remark"]:
            g.pop("remark")
        if not g["over"]:
            g.pop("over")
        fl.append(g)
    d["findings"] = fl
    on = d.get("online") if isinstance(d.get("online"), dict) else {}
    d["online"] = {"intro": _s(on.get("intro")), "rows": [
        {k: _s(r.get(k)) for k in ("where", "shown", "defect", "sev", "fix")}
        for r in on.get("rows", []) if isinstance(r, dict)]}
    d["composition"] = {"rows": _rows((d.get("composition") or {}).get("rows"), 6)}
    rc = d.get("reconciliation") if isinstance(d.get("reconciliation"), dict) else {}
    d["reconciliation"] = {"rows": _rows(rc.get("rows"), 7), "evidence": _s(rc.get("evidence")),
                           "conclusion": _s(rc.get("conclusion"))}
    d["verification"] = _rows(d.get("verification"), 4)
    ex = d.get("exposure")
    d["exposure"] = {k: [_s(x) for x in (v if isinstance(v, list) else [v])] for k, v in ex.items()} \
        if isinstance(ex, dict) else [_s(x) for x in (ex or [])]
    d["course"] = [_s(x) for x in (d.get("course") or [])]
    panels = []
    for p in d.get("label") or []:
        if not isinstance(p, dict):
            continue
        lines = []
        for ln in p.get("lines") or []:
            if isinstance(ln, str):
                lines.append([[ln, 0, 0]])
            else:
                segs = []
                for sg in ln:
                    if isinstance(sg, str):
                        segs.append([sg, 0, 0])
                    elif isinstance(sg, (list, tuple)) and sg:
                        segs.append([_s(sg[0]), int(bool(sg[1])) if len(sg) > 1 else 0,
                                     int(bool(sg[2])) if len(sg) > 2 else 0])
                lines.append(segs)
        panels.append({"panel": _s(p.get("panel")), "lines": lines})
    d["label"] = panels
    d["sources_verified"] = _rows(d.get("sources_verified"), 2)
    d["sources_unverified"] = [_s(x) for x in (d.get("sources_unverified") or [])]
    return d


# ------------------------------------------------------------------ builder
def load_builder(skill_dir):
    p = Path(skill_dir) / "07_report_builder.py"
    spec = importlib.util.spec_from_file_location("report_builder", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = ImageFont

    class _Shim:  # use a system or default font if the DejaVu files are not installed
        @staticmethod
        def truetype(path, size=10, *a, **k):
            for cand in (path, os.path.basename(path), "DejaVuSans-Bold.ttf", "arialbd.ttf"):
                try:
                    return real.truetype(cand, size, *a, **k)
                except OSError:
                    continue
            return real.load_default(size)

    mod.ImageFont = _Shim
    return mod


def finalize(data, pdf_path, skill_dir, work, product, client, audit_date, post=None):
    doc = fitz.open(pdf_path)
    d = normalize(data, product, client, audit_date)
    if post:
        post(d)
    d["artwork"] = pdf_path
    d["pages"] = list(range(1, len(doc) + 1))
    resolve_boxes(d["findings"], doc)
    out = os.path.join(work, "report.docx")
    buildir = os.path.join(work, "_build")
    load_builder(skill_dir).build(d, out, buildir)
    marked = [os.path.join(buildir, f"marked_p{p}.png") for p in d["pages"]]
    return out, [m for m in marked if os.path.exists(m)], d


def summary_markdown(d):
    L = [f"# Label Audit Report: {d['product']}", "", f"Client: {d.get('client', '')}  |  Audit date {d['audit_date']}", "",
         "## Executive position", d["executive"], "", "## Deficiency schedule", "",
         "| Sr. | Severity | As printed | Deficiency | Provision | Correction |", "|---|---|---|---|---|---|"]
    for f in d["findings"]:
        row = [str(f["n"]), f["sev"], f["printed"], f["deficiency"], f["prov"], f["fix"]]
        L.append("| " + " | ".join(c.replace("|", "/").replace("\n", " ") for c in row) + " |")
    return "\n".join(L)