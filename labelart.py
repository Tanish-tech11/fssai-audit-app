"""Final corrected label: the original artwork with the corrected wording put in place.
Text, tables and the veg / non-veg mark are redrawn. Logos, seals, QR codes and photographs are left alone."""
import html as _html

import fitz
from PIL import Image

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


def _lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)


# ------------------------------------------------------------------ where does an edit go
def region_for(page, e, words):
    pr = page.rect
    nb = fr._norm_box(e["region_norm"], pr) if e.get("region_norm") else None
    anchor = str(e.get("anchor") or "").strip()
    if e.get("mode") == "add" or (e.get("type") == "veg_mark" and not anchor):
        return (nb, "estimate") if nb else (None, "")
    ar = None
    if anchor and words:
        sc, r = fr.locate(anchor, words)
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
        t = e.get("type") if e.get("type") in ("text", "table", "veg_mark") else "text"
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
        bg = sample_bg(img, rect, scale)
        fg = sample_fg(img, rect, scale, bg)
        jobs.append((p, page, rect, e, bg, fg, src))
        if src == "estimate" and e["mode"] == "replace":
            notes.append(f"Page {p}: \"{label}\" was placed from an estimate, check it.")
    # 1. remove what is being replaced
    done_pages = set()
    for p, page, rect, e, bg, fg, src in jobs:
        if e["mode"] == "replace" or e["type"] == "veg_mark":
            page.add_redact_annot(rect, fill=bg)
            done_pages.add(p)
    for p in done_pages:
        page = doc[p - 1]
        has_text = len(page.get_text("words")) >= 8
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE if has_text else fitz.PDF_REDACT_IMAGE_PIXELS)
    # 2. draw the new content
    placed = 0
    for p, page, rect, e, bg, fg, src in jobs:
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
            notes.append(f"Page {p}: the new text for \"{(e.get('anchor') or e.get('text') or '')[:40]}\" is too long for its space.")
        if blue:
            page.draw_rect(rect, color=BLUE if not dark_bg else LIGHT_BLUE, width=0.6, overlay=True)
    doc.save(out_pdf)
    return placed, notes


def render_pngs(pdf_path, dpi=130):
    doc = fitz.open(pdf_path)
    return [p.get_pixmap(dpi=dpi).tobytes("png") for p in doc]
