"""Mace label audit report builder.

Builds the single Word report described in 05_templates.md from the artwork PDF
and a findings file in JSON.

Usage:
    python3 07_report_builder.py findings.json "OUTPUT.docx" [workdir]

Box options in the findings file: "pad" (points round the box, default 1.5; use 0.6 to 1
where text lines sit close), "side" of the tag (L, R, T or B), "missing" (dotted box).
"zoom": list of {page, rect, caption} for enlarged views of a dense artwork page; each
view is printed after the full page, in the marked and in the corrected artwork.

Needs: PyMuPDF (fitz), Pillow, python-docx; DejaVu fonts for the image tags.
"""
import datetime, json, os, sys
import fitz
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

DPI = 220
S = DPI / 72
M = 90  # left margin on rendered artwork so tags never fall off the image
FONT_DIR = '/usr/share/fonts/truetype/dejavu/'
FB = FONT_DIR + 'DejaVuSans-Bold.ttf'
FC = FONT_DIR + 'DejaVuSansCondensed-Bold.ttf'
SEV = {'Critical': (210, 25, 25), 'Major': (240, 130, 0), 'Minor': (225, 190, 0)}
SEVHEX = {'Critical': 'D21919', 'Major': 'F08200', 'Minor': 'E1BE00'}
BLUE = (0, 85, 200)
MAROON = RGBColor(0x8B, 0x1A, 0x1A)


# ---------------------------------------------------------------- images
def render(doc, pno):
    pix = doc[pno - 1].get_pixmap(dpi=DPI)
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    c = Image.new('RGB', (im.width + M, im.height), 'white')
    c.paste(im, (M, 0))
    return c


def px(b, pad=2):
    return [int((b[0] - pad) * S) + M, int((b[1] - pad) * S),
            int((b[2] + pad) * S) + M, int((b[3] + pad) * S)]


def tag(d, x, y, label, col, size=34):
    f = ImageFont.truetype(FB, size)
    w = d.textlength(label, font=f) + 18
    d.rounded_rectangle([x, y, x + w, y + size + 10], radius=10, fill=col)
    d.text((x + 9, y + 3), label, fill='white', font=f)


def tagb(d, b, side, label, col, size=34):
    f = ImageFont.truetype(FB, size)
    w = d.textlength(label, font=f) + 18
    h = size + 10
    cy = (b[1] + b[3]) // 2 - h // 2
    if side == 'L':
        x, y = b[0] - w - 4, cy
    elif side == 'R':
        x, y = b[2] + 4, cy
    elif side == 'B':
        x, y = b[0], b[3] + 4
    else:
        x, y = b[0], b[1] - h - 4
    tag(d, max(0, x), max(0, y), label, col, size)


def dashed_rect(d, b, col, width=6, dash=24):
    x0, y0, x1, y1 = b
    for x in range(x0, x1, dash * 2):
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=col, width=width)
        d.line([(x, y1), (min(x + dash, x1), y1)], fill=col, width=width)
    for y in range(y0, y1, dash * 2):
        d.line([(x0, y), (x0, min(y + dash, y1))], fill=col, width=width)
        d.line([(x1, y), (x1, min(y + dash, y1))], fill=col, width=width)


def fit_text(d, box, text, col):
    x0, y0, x1, y1 = box
    for size in range(40, 8, -1):
        f = ImageFont.truetype(FC, size)
        words, lines, cur = text.split(), [], ''
        for w in words:
            t = (cur + ' ' + w).strip()
            if d.textlength(t, font=f) <= (x1 - x0 - 12):
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        h = len(lines) * (size + 3)
        if h <= (y1 - y0 - 6):
            yy = y0 + ((y1 - y0) - h) // 2
            for ln in lines:
                d.text((x0 + 6, yy), ln, fill=col, font=f)
                yy += size + 3
            return


PAD = 1.5  # points added round every box unless the finding sets its own 'pad'


def marks(f):
    out = [(f['box'], str(f['n']), f.get('side', 'L'), f.get('missing', False), f.get('pad', PAD))]
    for e in f.get('extra', []):
        if e.get('mark'):
            out.append((e['box'], e['tag'], e.get('side', 'L'), e.get('missing', False), e.get('pad', PAD)))
    return out


def zoom_crop(img_path, rect, out_path):
    """Enlarged view of part of a rendered page; rect in PDF points."""
    im = Image.open(img_path)
    x0 = 0 if rect[0] <= 1 else int(rect[0] * S) + M - 40
    box = [max(0, x0), max(0, int(rect[1] * S)), min(im.width, int(rect[2] * S) + M + 40),
           min(im.height, int(rect[3] * S))]
    im.crop(box).save(out_path)
    return out_path


def build_images(data, work):
    pdf = fitz.open(data['artwork'])
    out = {'marked': {}, 'corrected': {}, 'crops': {}}
    for pno in data['pages']:
        F = [f for f in data['findings'] if f['page'] == pno]
        img = render(pdf, pno).convert('RGBA')
        ov = Image.new('RGBA', img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for f in F:
            c = SEV[f['sev']]
            for bx, lab, sd, miss, pad in marks(f):
                if miss:
                    d.rectangle(px(bx, pad), fill=c + (28,))
                    continue
                d.rectangle(px(bx, pad), fill=c + (70,), outline=c + (255,), width=6)
        img = Image.alpha_composite(img, ov)
        d = ImageDraw.Draw(img)
        for f in F:
            for bx, lab, sd, miss, pad in marks(f):
                if miss:
                    dashed_rect(d, px(bx, pad), SEV[f['sev']] + (255,))
                tagb(d, px(bx, pad), sd, lab, SEV[f['sev']])
        p = os.path.join(work, f'marked_p{pno}.png')
        img.convert('RGB').save(p)
        out['marked'][pno] = p
        base = render(pdf, pno)
        for f in F:
            cp = os.path.join(work, f"crop{f['n']}.png")
            base.crop(px(f['box'], pad=f.get('pad', PAD) + 4)).save(cp)
            out['crops'][f['n']] = cp
        img = render(pdf, pno)
        d = ImageDraw.Draw(img)
        for f in F:
            items = []
            if f.get('over'):
                items.append((f['box'], f['over'], str(f['n']), f.get('side', 'L'), f.get('pad', PAD)))
            for e in f.get('extra', []):
                if e.get('over'):
                    items.append((e['box'], e['over'], e['tag'], e.get('side', 'L'), e.get('pad', PAD)))
            for b, text, lab, sd, pad in items:
                bb = px(b, pad)
                d.rectangle(bb, fill=(232, 241, 255), outline=BLUE, width=6)
                fit_text(d, bb, text, BLUE)
                tagb(d, bb, sd, lab, BLUE)
        p = os.path.join(work, f'corrected_p{pno}.png')
        img.save(p)
        out['corrected'][pno] = p
    out['zoom'] = []
    for k, z in enumerate(data.get('zoom', []), 1):
        out['zoom'].append((z, zoom_crop(out['marked'][z['page']], z['rect'], os.path.join(work, f'zoom_marked_{k}.png')),
                            zoom_crop(out['corrected'][z['page']], z['rect'], os.path.join(work, f'zoom_corrected_{k}.png'))))
    return out


def fit_height(path, max_h, max_w=23.4):
    im = Image.open(path)
    return Cm(min(max_h, max_w * im.height / im.width))


# ---------------------------------------------------------------- word helpers
def add_heading_numbering(doc):
    """Word auto-numbering linked to Heading 1 (1.) and Heading 2 (1.1)."""
    numbering = doc.part.numbering_part.element
    abs_ids = [int(a.get(qn('w:abstractNumId'))) for a in numbering.findall(qn('w:abstractNum'))]
    num_ids = [int(n.get(qn('w:numId'))) for n in numbering.findall(qn('w:num'))]
    aid = max(abs_ids + [0]) + 1
    nid = max(num_ids + [0]) + 1
    a = OxmlElement('w:abstractNum')
    a.set(qn('w:abstractNumId'), str(aid))
    ml = OxmlElement('w:multiLevelType')
    ml.set(qn('w:val'), 'multilevel')
    a.append(ml)
    for lvl, (fmt, style, ind) in enumerate([('%1.', 'Heading1', 567), ('%1.%2', 'Heading2', 851)]):
        L = OxmlElement('w:lvl')
        L.set(qn('w:ilvl'), str(lvl))
        for tagname, val in (('w:start', '1'), ('w:numFmt', 'decimal'), ('w:pStyle', style),
                             ('w:lvlText', fmt), ('w:lvlJc', 'left')):
            e = OxmlElement(tagname)
            e.set(qn('w:val'), val)
            L.append(e)
        pPr = OxmlElement('w:pPr')
        ind_el = OxmlElement('w:ind')
        ind_el.set(qn('w:left'), str(ind))
        ind_el.set(qn('w:hanging'), str(ind))
        pPr.append(ind_el)
        L.append(pPr)
        a.append(L)
    first_num = numbering.find(qn('w:num'))
    if first_num is not None:
        first_num.addprevious(a)
    else:
        numbering.append(a)
    n = OxmlElement('w:num')
    n.set(qn('w:numId'), str(nid))
    an = OxmlElement('w:abstractNumId')
    an.set(qn('w:val'), str(aid))
    n.append(an)
    numbering.append(n)
    for lvl, sname in enumerate(('Heading 1', 'Heading 2')):
        st = doc.styles[sname]
        pPr = st.element.get_or_add_pPr()
        numPr = OxmlElement('w:numPr')
        il = OxmlElement('w:ilvl')
        il.set(qn('w:val'), str(lvl))
        ni = OxmlElement('w:numId')
        ni.set(qn('w:val'), str(nid))
        numPr.append(il)
        numPr.append(ni)
        pPr.insert(0, numPr)


def field_run(par, code):
    r = par.add_run()
    for kind, text in (('begin', None), ('instr', code), ('separate', None), ('text', '1'), ('end', None)):
        if kind == 'instr':
            e = OxmlElement('w:instrText')
            e.set(qn('xml:space'), 'preserve')
            e.text = text
        elif kind == 'text':
            e = OxmlElement('w:t')
            e.text = text
        else:
            e = OxmlElement('w:fldChar')
            e.set(qn('w:fldCharType'), kind)
        r._r.append(e)
    r.font.size = Pt(10)
    return r


def shade(cell, hexcol):
    tcPr = cell._tc.get_or_add_tcPr()
    s = OxmlElement('w:shd')
    s.set(qn('w:val'), 'clear')
    s.set(qn('w:color'), 'auto')
    s.set(qn('w:fill'), hexcol)
    tcPr.append(s)


def cell_text(cell, text, bold=False, color=None, size=11, italic=False):
    cell.text = ''
    p = cell.paragraphs[0]
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor(*color)
    return p


def fixed_table(doc, widths, header):
    tb = doc.add_table(rows=1, cols=len(widths))
    tb.style = 'Table Grid'
    tb.autofit = False
    tl = OxmlElement('w:tblLayout')
    tl.set(qn('w:type'), 'fixed')
    tb._tbl.tblPr.append(tl)
    for i, w in enumerate(widths):
        tb.columns[i].width = Cm(w)
    for i, h in enumerate(header):
        cell_text(tb.cell(0, i), h, bold=True, color=(255, 255, 255))
        shade(tb.cell(0, i), '8B1A1A')
    # repeat header row on each page
    trPr = tb.rows[0]._tr.get_or_add_trPr()
    th = OxmlElement('w:tblHeader')
    th.set(qn('w:val'), 'true')
    trPr.append(th)
    return tb


def set_widths(tb, widths):
    for r in tb.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)


# ---------------------------------------------------------------- report
def build(data, out_docx, work):
    os.makedirs(work, exist_ok=True)
    imgs = build_images(data, work)
    doc = Document()
    st = doc.styles['Normal']
    st.font.name = 'Times New Roman'
    st.font.size = Pt(13)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')
    st.paragraph_format.line_spacing = 1.5
    for hn, size in (('Heading 1', 15), ('Heading 2', 13)):
        h = doc.styles[hn]
        h.font.name = 'Times New Roman'
        h.font.size = Pt(size)
        h.font.bold = True
        h.font.underline = False
        h.font.color.rgb = MAROON
        h.element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')
        h.element.rPr.rFonts.set(qn('w:ascii'), 'Times New Roman')
        h.element.rPr.rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    add_heading_numbering(doc)

    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    sec.left_margin, sec.right_margin = Cm(3.5), Cm(2.8)
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = hp.add_run('Mace Corporate Associates')
    hr.font.size = Pt(10)
    hr.font.color.rgb = MAROON
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.add_run('Page ').font.size = Pt(10)
    field_run(fp, 'PAGE')
    fp.add_run(' of ').font.size = Pt(10)
    field_run(fp, 'NUMPAGES')

    cp = doc.core_properties
    cp.author = 'Mace Corporate Associates'
    cp.last_modified_by = 'Mace Corporate Associates'
    cp.title = f"{data['product']} Label Audit Report"
    cp.comments = ''
    cp.keywords = ''
    cp.created = cp.modified = datetime.datetime.now()

    def para(text='', bold=False, color=None, size=None, align=None, italic=False):
        p = doc.add_paragraph()
        p.alignment = align if align is not None else WD_ALIGN_PARAGRAPH.JUSTIFY
        r = p.add_run(text)
        r.bold = bold
        r.italic = italic
        if color:
            r.font.color.rgb = RGBColor(*color)
        if size:
            r.font.size = Pt(size)
        return p

    def h1(text, new_page=False):
        h = doc.add_heading(text, 1)
        if new_page:
            h.paragraph_format.page_break_before = True
        return h

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run(f"Label Audit Report: {data['product']}")
    tr.bold = True
    tr.font.size = Pt(16)
    tr.font.color.rgb = MAROON
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(f"{data.get('client', '')}   |   Audit date {data['audit_date']}")
    sr.font.size = Pt(11)

    # 1 identification
    h1('Product identification')
    tb = fixed_table(doc, [7.0, 16.4], ['Particular', 'As found'])
    for k, v in data['identification']:
        row = tb.add_row().cells
        cell_text(row[0], k, bold=True)
        cell_text(row[1], v)
    set_widths(tb, [7.0, 16.4])

    # 2 executive position
    h1('Executive position')
    para(data['executive'])

    # 3 marked artwork
    h1('Marked artwork', new_page=True)
    para('Each problem area is shaded on the artwork as printed. The number on the box is the Sr. No. in the '
         'Deficiency Schedule. A dotted box marks the place of a mandatory item that is missing.', size=12)
    leg = doc.add_table(rows=1, cols=3)
    leg.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, k in enumerate(('Critical', 'Major', 'Minor')):
        p = cell_text(leg.cell(0, i), k, bold=True, color=(255, 255, 255))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        shade(leg.cell(0, i), SEVHEX[k])
    for k, pno in enumerate(data['pages']):
        if k:
            para(f'Artwork page {pno}', bold=True, size=12, align=WD_ALIGN_PARAGRAPH.CENTER).paragraph_format.page_break_before = True
        doc.add_picture(imgs['marked'][pno], height=fit_height(imgs['marked'][pno], 11.0 if k == 0 else 14.8))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for z, zm, zc in imgs['zoom']:
        cap = para(f"Enlarged view: {z['caption']}", bold=True, size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
        cap.paragraph_format.page_break_before = True
        doc.add_picture(zm, height=fit_height(zm, 14.6))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 4 deficiency schedule
    h1('Deficiency Schedule', new_page=True)
    widths = [1.1, 5.6, 6.0, 3.6, 2.0, 5.1]
    tb = fixed_table(doc, widths, ['Sr.', 'As printed', 'Deficiency', 'Provision', 'Severity', 'Correction'])
    for f in sorted(data['findings'], key=lambda x: x['n']):
        row = tb.add_row().cells
        cell_text(row[0], str(f['n']), bold=True)
        row[1].text = ''
        if not f.get('missing'):
            row[1].paragraphs[0].add_run().add_picture(imgs['crops'][f['n']], width=Cm(5.2))
            p2 = row[1].add_paragraph()
        else:
            p2 = row[1].paragraphs[0]
        p2.paragraph_format.line_spacing = 1.0
        r = p2.add_run(f['printed'])
        r.font.size = Pt(10)
        r.italic = True
        p3 = cell_text(row[2], f['deficiency'])
        if f.get('remark'):
            rr = p3.add_run(' ' + f['remark'])
            rr.font.size = Pt(11)
            rr.font.color.rgb = RGBColor(*BLUE)
        cell_text(row[3], f['prov'])
        cell_text(row[4], f['sev'], bold=True, color=(255, 255, 255))
        shade(row[4], SEVHEX[f['sev']])
        cell_text(row[5], f['fix'], color=BLUE)
    set_widths(tb, widths)

    # 4A online listing (Block T), only where listings were examined
    online = data.get('online', {})
    if online.get('rows'):
        h1('Online listing findings', new_page=True)
        if online.get('intro'):
            para(online['intro'])
        w = [1.1, 4.2, 6.0, 5.4, 2.3, 4.4]
        tb = fixed_table(doc, w, ['Sr.', 'Listing and page', 'As displayed', 'Deficiency and provision',
                                  'Severity', 'Correction'])
        for i, rw in enumerate(online['rows'], 1):
            row = tb.add_row().cells
            cell_text(row[0], str(i), bold=True)
            cell_text(row[1], rw['where'])
            cell_text(row[2], rw['shown'])
            cell_text(row[3], rw['defect'])
            cell_text(row[4], rw['sev'], bold=True)
            shade(row[4], SEVHEX.get(rw['sev'], 'FFFFFF'))
            cell_text(row[5], rw['fix'], color=BLUE)
        set_widths(tb, w)
        for shot in online.get('screens', []):
            if os.path.exists(shot['path']):
                doc.add_picture(shot['path'], width=Cm(min(16.0, 23.4)))
                para(shot.get('caption', ''), italic=True, size=9)

    # 5 composition
    h1('Composition and rationality', new_page=True)
    comp = data.get('composition', {})
    if comp.get('rows'):
        doc.add_heading('Ingredient table', 2)
        w = [5.0, 2.4, 4.6, 4.2, 3.6, 3.6]
        tb = fixed_table(doc, w, ['Ingredient', 'Per unit', 'Schedule and entry (N22; N16)', 'Permitted range',
                                  'Marker required', 'Marker declared'])
        for rw in comp['rows']:
            row = tb.add_row().cells
            for i, v in enumerate(rw):
                cell_text(row[i], v)
        set_widths(tb, w)
    rec = data.get('reconciliation', {})
    if rec.get('rows'):
        doc.add_heading('Dose reconciliation', 2)
        w = [5.4, 2.6, 4.0, 3.2, 3.2, 2.5, 2.5]
        tb = fixed_table(doc, w, ['Ingredient', 'Per unit', 'Schedule', 'Floor per day', 'Ceiling per day',
                                  'Units, min', 'Units, max'])
        for rw in rec['rows']:
            row = tb.add_row().cells
            for i, v in enumerate(rw):
                cell_text(row[i], v)
        set_widths(tb, w)
    for key, head in (('evidence', 'Evidence under N22 5(7) and N16 3(29)'), ('conclusion', 'Conclusion')):
        if rec.get(key):
            doc.add_heading(head, 2)
            para(rec[key])

    # 6 open verification list
    h1('Unable to verify')
    w = [1.1, 6.2, 4.4, 8.2, 3.5]
    tb = fixed_table(doc, w, ['Sr.', 'Point', 'Provision', 'Document or check required', 'From whom'])
    for i, rw in enumerate(data.get('verification', []), 1):
        row = tb.add_row().cells
        cell_text(row[0], str(i), bold=True)
        for j, v in enumerate(rw, 1):
            cell_text(row[j], v)
    set_widths(tb, w)

    # 7, 8: exposure is given once, under four heads (FSS Act; DMR54; Consumer Protection; Legal Metrology)
    h1('Exposure')
    exp = data.get('exposure', [])
    if isinstance(exp, dict):
        for head in ('FSS Act, 2006', 'Drugs and Magic Remedies Act, 1954', 'Consumer Protection Act, 2019 and E-Commerce Rules',
                     'Legal Metrology Act, 2009 and Rules', 'Forum map'):
            if exp.get(head):
                doc.add_heading(head, 2)
                for p in exp[head]:
                    para(p)
    else:
        for p in exp:
            para(p)
    h1('Recommended course')
    for p in data.get('course', []):
        para(p)

    # 9 corrected artwork
    h1('Corrected artwork', new_page=True)
    para('Each change is boxed in blue at the place where it is to be made, with the corrected wording inside the box. '
         'Numbers match the schedule. Square brackets are figures to be taken from the formulation sheet or the '
         'analytical report. The designer applies the changes in the source file.', size=12)
    for k, pno in enumerate(data['pages']):
        if k:
            para(f'Artwork page {pno}', bold=True, size=12, align=WD_ALIGN_PARAGRAPH.CENTER).paragraph_format.page_break_before = True
        doc.add_picture(imgs['corrected'][pno], height=fit_height(imgs['corrected'][pno], 11.0 if k == 0 else 14.8))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for z, zm, zc in imgs['zoom']:
        cap = para(f"Enlarged view: {z['caption']}", bold=True, size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
        cap.paragraph_format.page_break_before = True
        doc.add_picture(zc, height=fit_height(zc, 14.6))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 10 suggested label
    h1('Suggested compliant label', new_page=True)
    para('Changed or added text is in blue; unchanged text is in black. Square brackets are figures to be taken from '
         'the formulation sheet or an accredited analytical report.', size=12)
    for panel in data.get('label', []):
        doc.add_heading(panel['panel'], 2)
        for ln in panel['lines']:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(1)
            p.paragraph_format.line_spacing = 1.15
            for txt, bold, changed in ln:
                r = p.add_run(txt)
                r.bold = bool(bold)
                if changed:
                    r.font.color.rgb = RGBColor(*BLUE)

    # 11 sources
    h1('Sources relied on', new_page=True)
    doc.add_heading('Verified from the library', 2)
    w = [8.4, 15.0]
    tb = fixed_table(doc, w, ['Provision', 'Library file and page'])
    for a, b in data.get('sources_verified', []):
        row = tb.add_row().cells
        cell_text(row[0], a)
        cell_text(row[1], b)
    set_widths(tb, w)
    doc.add_heading('Not verified from the library', 2)
    for p in data.get('sources_unverified', []) or ['None.']:
        para(p)

    doc.save(out_docx)
    return out_docx


if __name__ == '__main__':
    data = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    work = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(out)), '_build')
    print(build(data, out, work))
