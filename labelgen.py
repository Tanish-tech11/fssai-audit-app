"""Draws a NEW label (flat carton artwork) from a label specification, when the client has no label yet.
Panels, left to right: back panel, side panel, front panel, side panel."""
import fitz

import labelart

W, H = 900, 430
NAVY = (0.05, 0.17, 0.28)
GOLD = (0.95, 0.76, 0.15)
WHITE = (1, 1, 1)
INK = (0.1, 0.1, 0.1)
CREAM = (0.98, 0.97, 0.93)
TEAL = (0.0, 0.45, 0.5)


def _c(h, default):
    try:
        h = str(h).lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except Exception:
        return default


def _lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _s(v):
    return "" if v is None else str(v)


class _Ctx:
    def __init__(self, page):
        self.page, self.warnings, self.min_size = page, [], 99.0

    def box(self, rect, text, size=8, color=INK, bold=False, align=0, rotate=0, floor=4.5, what=""):
        text = _s(text)
        if not text.strip():
            return
        fn = "hebo" if bold else "helv"
        sz = size
        while sz >= 3.0:
            if self.page.insert_textbox(fitz.Rect(*rect), text, fontsize=sz, color=color, fontname=fn, align=align, rotate=rotate) >= 0:
                self.min_size = min(self.min_size, sz)
                if sz < floor:
                    self.warnings.append(f"{what or text[:30]}: the type is very small ({sz:.1f} pt). The designer must make room or move it to another panel.")
                return
            sz -= 0.25
        self.warnings.append(f"{what or text[:30]}: the text does not fit its space and was left out. The designer must lay it out by hand.")

    def table(self, x, y, widths, rows, size, rowh):
        for i, row in enumerate(rows):
            cx = x
            for w, cell in zip(widths, list(row) + [""] * len(widths)):
                self.page.draw_rect(fitz.Rect(cx, y, cx + w, y + rowh), color=(0.4, 0.4, 0.4), width=0.4,
                                    fill=(0.88, 0.92, 0.95) if i == 0 else WHITE)
                self.box((cx + 1.5, y + 1, cx + w - 1, y + rowh), _s(cell), size, INK, bold=(i == 0), what="nutrition table")
                cx += w
            y += rowh
        return y


def render(lab):
    """Returns (pdf_bytes, warnings)."""
    lab = lab or {}
    col = lab.get("colors") or {}
    pri, acc = _c(col.get("primary"), NAVY), _c(col.get("accent"), GOLD)
    on_pri = WHITE if _lum(pri) < 0.55 else INK
    acc_text = acc if _lum(pri) < 0.55 and _lum(acc) > 0.4 else on_pri
    doc = fitz.open()
    pg = doc.new_page(width=W, height=H)
    ctx = _Ctx(pg)
    pg.draw_rect(fitz.Rect(0, 0, W, H), color=None, fill=CREAM)
    for x0, x1 in ((330, 440), (440, 780), (780, W)):
        pg.draw_rect(fitz.Rect(x0, 0, x1, H), color=None, fill=pri)
    for x in (330, 440, 780):
        pg.draw_line(fitz.Point(x, 0), fitz.Point(x, H), color=(0.6, 0.6, 0.6), width=0.4, dashes="[3 3] 0")
    brand = _s(lab.get("brand")) or "[Brand]"
    for x0, x1 in ((335, 435), (785, 895)):
        ctx.box((x0, 20, x1, 410), brand, 30, acc_text, True, align=1, rotate=90, what="side panel brand name")

    # ------------------------------------------------------------ front panel
    pg.draw_rect(fitz.Rect(460, 45, 760, 330), color=None, fill=WHITE)
    labelart._veg(pg, fitz.Rect(470, 55, 500, 85), "non_veg" if lab.get("veg") == "non_veg" else "veg", WHITE)
    ctx.box((510, 52, 755, 100), brand, 34, pri if _lum(pri) < 0.7 else INK, True, what="brand name")
    ctx.box((510, 100, 755, 114), _s(lab.get("category") or "NUTRACEUTICAL").upper(), 9, TEAL, True, what="category")
    ctx.box((470, 118, 755, 146), lab.get("descriptor"), 8, INK, what="product name")
    claims = [_s(c) for c in (lab.get("claims") or []) if _s(c).strip()]
    if claims:
        ctx.box((470, 154, 755, 250), "\n".join(claims), 11, pri if _lum(pri) < 0.7 else INK, True, what="front claims")
    ctx.box((470, 270, 755, 322), lab.get("target_group"), 9, INK, True, what="target group")
    ctx.box((462, 340, 760, 362), "Net Quantity: " + _s(lab.get("net_quantity") or "[ ]"), 11, on_pri, True, what="net quantity")

    # ------------------------------------------------------------ back panel
    nut = lab.get("nutrition") or {}
    rows = [["Nutrients", "Per serve", "% RDA*"]] + [list(r)[:3] for r in (nut.get("rows") or []) if isinstance(r, (list, tuple))]
    ctx.box((10, 4, 186, 20), nut.get("heading") or "Nutritional Information", 6.5, INK, True, what="nutrition heading")
    rowh = 10.5 if len(rows) <= 22 else (9.5 if len(rows) <= 26 else 8.5)
    y = ctx.table(10, 21, [104, 42, 30], rows, 6.2, rowh)
    ctx.box((10, y + 2, 186, y + 34), nut.get("footnote") or "* RDA per ICMR-NIN 2020 for an average adult.", 5.8, INK, what="nutrition footnote")
    ctx.box((192, 6, 322, 112), "Ingredients: " + _s(lab.get("ingredients")), 6.8, INK, what="ingredients")
    stm = [_s(x) for x in (lab.get("statements") or []) if _s(x).strip()]
    head = [x for x in stm if "NOT FOR MEDICINAL USE" in x.upper()]
    rest = [x for x in stm if x not in head]
    if head:
        ctx.box((192, 116, 322, 132), head[0], 7.5, INK, True, what="NOT FOR MEDICINAL USE")
    ctx.box((192, 134, 322, 262), "\n".join(rest + ([_s(lab.get("storage"))] if lab.get("storage") else [])), 6.6, INK, what="statements")
    legal = "\n".join(x for x in (_s(lab.get("manufacturer")), _s(lab.get("marketer")), _s(lab.get("consumer_care"))) if x)
    ctx.box((10, 268, 232, 424), legal, 6.6, INK, what="manufacturer and marketer")
    pg.draw_rect(fitz.Rect(240, 268, 322, 282), color=INK, width=0.6)
    ctx.box((243, 270, 320, 282), "fssai", 7, INK, True, what="FSSAI logo")
    price = "\n".join(_s(x) for x in (lab.get("price_lines") or []) + (lab.get("date_lines") or []))
    ctx.box((240, 290, 324, 424), price, 6.6, INK, what="price and date block")
    b = doc.tobytes()
    ctx.warnings.append("The FSSAI logo, QR code and barcode are placeholders. The designer uses the official FSSAI logo and real codes.")
    ctx.warnings.append("The designer checks every type size against the font height table of the Labelling and Display Regulations for this pack size.")
    return b, ctx.warnings


def to_pngs(pdf_bytes, dpi=140):
    d = fitz.open(stream=pdf_bytes, filetype="pdf")
    return [p.get_pixmap(dpi=dpi).tobytes("png") for p in d]