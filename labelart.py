"""Final corrected label: the original artwork with the corrected wording put in place.
Text, tables and the veg / non-veg mark are redrawn. Logos, seals, QR codes and photographs are left alone."""
import html as _html
import io

import fitz
from PIL import Image, ImageDraw, ImageFont

import fullreport as fr

BLUE = (0 / 255, 85 / 255, 200 / 255)
LIGHT_BLUE = (0.45, 0.75, 1.0)
BROWN = (0.45, 0.22, 0.05)
GREEN = (0.0, 0.55, 0.15)
SIZES = [16, 14, 12, 11, 10, 9, 8, 7.5, 7, 6.5, 6, 5.5, 5, 4.5, 4]


# ------------------------------------------------------------------ colour sampling
def _render(page, dpi=100):
    pix = page.get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), dpi / 72


def _median(px):
    return tuple(sorted(p[i] for p in px)[len(px) // 2] for i in range(3))


def _crop_px(img, rect, scale):
    x0, y0, x1, y1 = [int(v * scale) for v in rect]
    crop = img.crop((max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height)))
    return list(crop.getdata())


def sample_bg(img, rect, scale):
    """The colour that fills most of the area (text covers little of it)."""
    px = _crop_px(img, rect, scale)
    if not px:
        return (1.0, 1.0, 1.0)
    from collections import Counter
    key = Counter((p[0] >> 3, p[1] >> 3, p[2] >> 3) for p in px).most_common(1)[0][0]
    same = [p for p in px if (p[0] >> 3, p[1] >> 3, p[2] >> 3) == key]
    return tuple(v / 255 for v in _median(same))


def sample_fg(img, rect, scale, bg):
    """The colour of the existing text: the pixel that contrasts most with the background."""
    px = _crop_px(img, rect, scale)
    if not px:
        return None
    b = [v * 255 for v in bg]
    far = max(px, key=lambda p: sum((p[i] - b[i]) ** 2 for i in range(3)))
    if sum((far[i] - b[i]) ** 2 for i in range(3)) < 60 ** 2:
        return None
    return tuple(v / 255 for v in far)


def sample_ring(img, rect, scale, pad=4):
    """Background just outside an area (used when the area holds a graphic that is being removed)."""
    x0, y0, x1, y1 = [int(v * scale) for v in rect]
    W, H = img.size
    px = []
    for a_, b_, c_, d_ in ((x0, y0 - pad, x1, y0), (x0, y1, x1, y1 + pad), (x0 - pad, y0, x0, y1), (x1, y0, x1 + pad, y1)):
        a_, b_, c_, d_ = max(a_, 0), max(b_, 0), min(c_, W), min(d_, H)
        if c_ > a_ and d_ > b_:
            px += list(img.crop((a_, b_, c_, d_)).getdata())
    return tuple(v / 255 for v in _median(px)) if px else (1.0, 1.0, 1.0)


def _font(size):
    for f in ("DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def grid_images(pdf_path, width=1500, max_pages=6):
    """Each page with a labelled grid, so the model can read positions as percentages."""
    doc = fitz.open(pdf_path)
    out = []
    for page in list(doc)[:max_pages]:
        z = width / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
        W, H = im.size
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for k in range(1, 20):
            major = k % 2 == 0
            col = (255, 0, 160, 160 if major else 70)
            x, y = int(W * k / 20), int(H * k / 20)
            d.line([(x, 0), (x, H)], fill=col, width=2 if major else 1)
            d.line([(0, y), (W, y)], fill=col, width=2 if major else 1)
        im = Image.alpha_composite(im, ov)
        d = ImageDraw.Draw(im)
        f = _font(22)
        for k in range(1, 10):
            lab, x, y = str(k * 10), int(W * k / 10), int(H * k / 10)
            d.rectangle([x - 17, 0, x + 17, 27], fill=(255, 255, 255, 235))
            d.text((x - 14, 2), lab, fill=(200, 0, 120), font=f)
            d.rectangle([0, y - 14, 36, y + 14], fill=(255, 255, 255, 235))
            d.text((3, y - 13), lab, fill=(200, 0, 120), font=f)
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=80)
        out.append(buf.getvalue())
    return out


def append_to_docx(path, pngs, pngs_blue):
    """Adds the final label pages to the end of the Word report."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm
    d = Document(path)

    def pages(title, imgs, intro):
        h = d.add_heading(title, 1)
        h.paragraph_format.page_break_before = True
        d.add_paragraph(intro)
        for k, b in enumerate(imgs):
            im = Image.open(io.BytesIO(b))
            width = min(23.4, 14.2 * im.width / im.height)
            if k:
                d.add_paragraph().paragraph_format.page_break_before = True
            d.add_picture(io.BytesIO(b), width=Cm(width))
            d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    pages("Final label artwork", pngs,
          "The original artwork with the corrected wording put in place. Square brackets are figures to be taken from the "
          "formulation sheet or an analytical report. The designer checks the artwork before it goes to print.")
    pages("Final label artwork, changes in blue", pngs_blue, "The same artwork with every changed place marked in blue.")
    d.save(path)


def _lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)


# ------------------------------------------------------------------ where does an edit go
def region_for(page, e, words):
    pr = page.rect
    nb = fr._norm_box(e["region_norm"], pr) if e.get("region_norm") else None
    anchor = str(e.get("anchor") or "").strip()
    if e.get("mode") == "add" or (e.get("type") in ("veg_mark", "remove") and not anchor):
        return (nb, "estimate") if nb else (None, "")
    ar = None
    if anchor and words:
        sc, r = fr.locate(anchor, words, near=nb)
        if sc >= fr.MATCH_MIN:
            ar = r
    if ar is not None:
        rect = fitz.Rect(ar)
        if len(page.get_text("words")) >= 8:  # real text layer: take the whole text block
            for b in page.get_text("blocks"):
                if b[6] == 0 and fitz.Rect(b[:4]).intersects(ar):
                    rect.include_rect(fitz.Rect(b[:4]))
        if nb is not None and nb.contains(ar):
            rect.include_rect(nb)
        if rect.get_area() > 0.35 * pr.get_area():
            rect = fitz.Rect(ar)
        return rect, "text"
    return (nb, "estimate") if nb else (None, "")


# ------------------------------------------------------------------ drawing
def _text_html(e, color, size):
    lines = "<br>".join(_html.escape(ln) for ln in str(e.get("text", "")).split("\n"))
    return (f'<div style="font-family:sans-serif;font-size:{size}pt;color:{color};line-height:1.15;margin:0;'
            f'font-weight:{"bold" if e.get("bold") else "normal"};text-align:{e.get("align", "left")};">{lines}</div>')


def _table_html(rows, color, size):
    out = [f'<table style="border-collapse:collapse;font-family:sans-serif;font-size:{size}pt;color:{color};width:100%;">']
    for i, r in enumerate(rows):
        out.append("<tr>" + "".join(
            f'<td style="border:0.5pt solid {color};padding:1pt 2pt;font-weight:{"bold" if i == 0 else "normal"};">'
            f'{_html.escape(str(c))}</td>' for c in r) + "</tr>")
    return "".join(out) + "</table>"


def _put(page, rect, e, color, typical=None):
    hexc = _hex(color)
    n = max(1, str(e.get("text", "")).count("\n") + 1, len(e.get("rows") or []))
    bound = min(14.0, max(4.0, rect.height / n / 1.25))
    try:
        if e.get("size_pt"):
            bound = min(bound, float(e["size_pt"]))
        elif typical:
            bound = min(bound, typical * (1.25 if e.get("bold") else 1.05))
    except Exception:
        pass
    sizes = [s for s in SIZES if s <= bound] or [SIZES[-1]]
    for s in sizes:
        body = _table_html(e["rows"], hexc, s) if e.get("type") == "table" and e.get("rows") else _text_html(e, hexc, s)
        spare, _ = page.insert_htmlbox(rect, body, scale_low=1)
        if spare >= 0:
            return True
    body = _table_html(e["rows"], hexc, sizes[-1]) if e.get("type") == "table" and e.get("rows") else _text_html(e, hexc, sizes[-1])
    spare, _ = page.insert_htmlbox(rect, body, scale_low=0)
    return spare >= 0


def _veg(page, rect, variant, bg):
    side = min(rect.width, rect.height)
    c = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    sq = fitz.Rect(c.x - side / 2, c.y - side / 2, c.x + side / 2, c.y + side / 2)
    col = BROWN if variant == "non_veg" else GREEN
    page.draw_rect(sq, color=col, fill=(1, 1, 1), width=max(0.8, side * 0.06), overlay=True)
    m = side * 0.22
    if variant == "non_veg":
        page.draw_polyline([fitz.Point(c.x, sq.y0 + m), fitz.Point(sq.x1 - m, sq.y1 - m), fitz.Point(sq.x0 + m, sq.y1 - m),
                            fitz.Point(c.x, sq.y0 + m)], color=col, fill=col, closePath=True, overlay=True)
    else:
        page.draw_circle(c, side / 2 - m, color=col, fill=col, overlay=True)


def clean_edits(edits):
    out = []
    for e in edits or []:
        if not isinstance(e, dict):
            continue
        t = e.get("type") if e.get("type") in ("text", "table", "veg_mark", "remove") else "text"
        if t == "text" and not str(e.get("text", "")).strip():
            continue
        if t == "table" and not e.get("rows"):
            continue
        e = dict(e, type=t, mode="add" if e.get("mode") == "add" else "replace")
        try:
            e["page"] = int(e.get("page") or 1)
        except Exception:
            e["page"] = 1
        out.append(e)
    return out


def build_label(pdf_path, edits, out_pdf, blue=False):
    """Writes the corrected artwork. Returns (placed, notes)."""
    doc = fitz.open(pdf_path)
    renders, words, jobs, notes, typical = {}, {}, [], [], {}
    for e in clean_edits(edits):
        p = min(max(e["page"], 1), len(doc))
        page = doc[p - 1]
        if p not in renders:
            renders[p] = _render(page)
            words[p] = fr.page_words(page)
            hs = sorted(w[1].height for w in words[p])
            typical[p] = (hs[len(hs) // 2] / 1.2) if hs else None  # usual text size on this page, in points
        rect, src = region_for(page, e, words[p])
        label = (e.get("anchor") or e.get("text") or e.get("variant") or "edit")[:40]
        if rect is None:
            notes.append(f"Page {p}: could not place \"{label}\".")
            continue
        img, scale = renders[p]
        bg = sample_ring(img, rect, scale) if e["type"] == "remove" else sample_bg(img, rect, scale)
        fg = None if e["type"] == "remove" else sample_fg(img, rect, scale, bg)
        jobs.append((p, page, rect, e, bg, fg, src))
        if src == "estimate" and e["mode"] == "replace":
            notes.append(f"Page {p}: \"{label}\" was placed from an estimate, check it.")
    # 1. remove what is being replaced
    done_pages = set()
    for p, page, rect, e, bg, fg, src in jobs:
        if e["mode"] == "replace" or e["type"] in ("veg_mark", "remove"):
            try:
                page.add_redact_annot(rect, fill=bg)
                done_pages.add(p)
            except Exception as ex:
                notes.append(f"Page {p}: could not clear the old text ({ex}).")
    for p in done_pages:
        page = doc[p - 1]
        try:
            has_text = len(page.get_text("words")) >= 8
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE if has_text else fitz.PDF_REDACT_IMAGE_PIXELS)
        except Exception as ex:
            notes.append(f"Page {p}: could not clear the old text ({ex}).")
    # 2. draw the new content
    placed = 0
    for p, page, rect, e, bg, fg, src in jobs:
        name = (e.get("anchor") or e.get("text") or e.get("variant") or "edit")[:40]
        try:
            if e["type"] == "remove":
                placed += 1
                if blue:
                    page.draw_rect(rect, color=BLUE, width=0.6, dashes="[2 2] 0", overlay=True)
                continue
            if e["mode"] == "add" and e["type"] != "veg_mark":
                page.draw_rect(rect, color=None, fill=bg, overlay=True)
            if e["type"] == "veg_mark":
                _veg(page, rect, e.get("variant", "non_veg"), bg)
                placed += 1
                continue
            dark_bg = _lum(bg) < 0.45
            if blue:
                color = LIGHT_BLUE if dark_bg else BLUE
            else:
                color = fg if fg is not None else ((1, 1, 1) if dark_bg else (0.08, 0.08, 0.08))
            if _put(page, rect, e, color, typical.get(p)):
                placed += 1
            else:
                notes.append(f"Page {p}: the new text for \"{name}\" is too long for its space.")
            if blue:
                page.draw_rect(rect, color=BLUE if not dark_bg else LIGHT_BLUE, width=0.6, overlay=True)
        except Exception as ex:  # one bad edit must not stop the others
            notes.append(f"Page {p}: could not draw \"{name}\" ({ex}).")
    doc.save(out_pdf)
    return placed, notes


def render_pngs(pdf_path, dpi=130):
    doc = fitz.open(pdf_path)
    return [p.get_pixmap(dpi=dpi).tobytes("png") for p in doc]