"""Turns almost any uploaded file into something the app can use:
label artwork (PDF or PNG pages) or case documents (text, or a PDF or image that is read as it is)."""
import email
import html as _html
import io
import os
import re
import subprocess
import tempfile
import zipfile
from email import policy
from html.parser import HTMLParser

import fitz
from PIL import Image, ImageOps

try:  # phone photos (HEIC and HEIF)
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

IMG_EXT = {".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".psd", ".ico", ".pcx", ".ppm"}
ART_OTHER = {".svg", ".eps", ".ai", ".xps", ".oxps"}
TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".log", ".yaml", ".yml", ".ini", ".rst"}
MAX_FILES, MAX_UNZIPPED, MAX_DOC_CHARS, MAX_FRAMES, EMBED_MIN_W = 60, 120 * 1024 * 1024, 200_000, 6, 400

SUPPORTED = ("PDF, images (PNG, JPG, WEBP, GIF, BMP, TIFF, HEIC, PSD), SVG, AI and EPS artwork, Word (DOCX, DOC, RTF, ODT), "
             "Excel (XLSX, XLS, CSV, ODS), PowerPoint (PPTX, PPT, ODP), text, JSON, XML, HTML, e-mail (EML) and ZIP files")


def _ext(name):
    return os.path.splitext(name.lower())[1]


def _clip(text):
    return text if len(text) <= MAX_DOC_CHARS else text[:MAX_DOC_CHARS] + "\n[document cut here: too long]"


def _decode(raw):
    for enc in ("utf-8-sig", "utf-16"):
        if raw[:3] == b"\xef\xbb\xbf" or (enc == "utf-16" and raw[:2] in (b"\xff\xfe", b"\xfe\xff")):
            try:
                return raw.decode(enc)
            except Exception:
                pass
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("cp1252", errors="replace")


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def _html_text(s):
    p = _Strip()
    p.feed(s)
    return re.sub(r"\n\s*\n+", "\n", "".join(p.out)).strip()


def _xml_text(xml, breaks):
    xml = re.sub(breaks, "\n", xml)
    return _html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


def _strings(raw):
    """Last resort for old binary Office files: the readable runs of text."""
    runs = re.findall(rb"[\x20-\x7e\xa0-\xff]{6,}", raw) + [r.encode("latin-1", "ignore") for r in re.findall(r"(?:[\x20-\x7e]\x00){6,}", raw.decode("latin-1"))]
    out = []
    for r in re.findall(rb"(?:[\x20-\x7e]\x00){6,}", raw):
        out.append(r.decode("utf-16-le", "ignore"))
    out += [r.decode("cp1252", "ignore") for r in re.findall(rb"[\x20-\x7e]{6,}", raw)]
    return "\n".join(out)


# ------------------------------------------------------------------ images and artwork
def _png(im):
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _to_art(name, raw):
    """Returns [(new_name, bytes)] where bytes are PDF or PNG."""
    ext = _ext(name)
    base = os.path.splitext(name)[0]
    if ext == ".svg" or ext in (".xps", ".oxps"):
        d = fitz.open(stream=raw, filetype=ext.lstrip("."))
        return [(base + ".pdf", d.convert_to_pdf())]
    if ext == ".ai":
        try:
            fitz.open(stream=raw, filetype="pdf")
            return [(base + ".pdf", raw)]
        except Exception:
            raise ValueError("this Illustrator file has no PDF content. Export it as PDF from Illustrator")
    if ext == ".eps":
        im = Image.open(io.BytesIO(raw))
        im.load()
        return [(base + ".png", _png(im))]
    im = Image.open(io.BytesIO(raw))
    out = []
    n = getattr(im, "n_frames", 1)
    for i in range(min(n, MAX_FRAMES if ext in (".tif", ".tiff") else 1)):
        im.seek(i)
        out.append((f"{base}_p{i + 1}.png" if n > 1 and ext in (".tif", ".tiff") else base + ".png", _png(im.copy())))
    return out


# ------------------------------------------------------------------ Office and other documents
def _docx(raw):
    from docx import Document
    d = Document(io.BytesIO(raw))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for r in t.rows:
            parts.append(" | ".join(c.text.strip() for c in r.cells))
    for s in d.sections:
        parts += [p.text for p in s.header.paragraphs if p.text.strip()] + [p.text for p in s.footer.paragraphs if p.text.strip()]
    return "\n".join(parts)


def _pptx(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    out = []
    for i, n in enumerate(names, 1):
        xml = z.read(n).decode("utf-8", "ignore")
        out.append(f"[Slide {i}] " + " ".join(_html.unescape(t) for t in re.findall(r"<a:t>(.*?)</a:t>", xml, re.S)))
    for n in sorted(x for x in z.namelist() if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", x)):
        t = " ".join(_html.unescape(x) for x in re.findall(r"<a:t>(.*?)</a:t>", z.read(n).decode("utf-8", "ignore"), re.S))
        if t.strip():
            out.append("[Notes] " + t)
    return "\n".join(out)


def _xlsx(raw):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"[Sheet {ws.title}]")
        for k, row in enumerate(ws.iter_rows(values_only=True)):
            if k > 5000:
                out.append("[sheet cut here]")
                break
            if any(c is not None for c in row):
                out.append(" | ".join("" if c is None else str(c) for c in row))
    return "\n".join(out)


def _xls(raw):
    import xlrd
    wb = xlrd.open_workbook(file_contents=raw)
    out = []
    for ws in wb.sheets():
        out.append(f"[Sheet {ws.name}]")
        for r in range(min(ws.nrows, 5000)):
            row = ws.row_values(r)
            if any(str(c).strip() for c in row):
                out.append(" | ".join(str(c) for c in row))
    return "\n".join(out)


def _odf(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    return _xml_text(z.read("content.xml").decode("utf-8", "ignore"), r"</text:p>|</text:h>|</table:table-row>|</draw:page>")


def _rtf(raw):
    s = raw.decode("cp1252", "ignore")
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "ignore"), s)
    s = re.sub(r"\\par[d]?|\\line", "\n", s)
    s = re.sub(r"\\tab", "\t", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    return re.sub(r"[{}]", "", s).strip()


def _doc(raw):
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as f:
        f.write(raw)
        path = f.name
    try:
        r = subprocess.run(["antiword", path], capture_output=True, timeout=40)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "ignore"), False
    except Exception:
        pass
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
    return _strings(raw), True


def _printable(raw):
    if b"\x00" in raw[:4000] and raw[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        return False
    t = _decode(raw[:20000])
    return bool(t) and sum(c.isprintable() or c in "\n\r\t" for c in t) / len(t) > 0.9


# ------------------------------------------------------------------ main entry
def _embedded_images(raw, name):
    out = []
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        for n in z.namelist():
            if "/media/" in n and _ext(n) in IMG_EXT and len(out) < 8:
                try:
                    im = Image.open(io.BytesIO(z.read(n)))
                    if im.width >= EMBED_MIN_W:
                        out.append((f"{os.path.splitext(name)[0]}_{os.path.basename(n).split('.')[0]}.png", _png(im)))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def ingest(blobs, doc_names=None, all_docs=False):
    """blobs: [(name, bytes)]. doc_names: PDFs or images the user marked as case documents.
    all_docs: everything is a case document (no label yet).
    Returns (art, docs, notes, embedded):
      art       [(name, bytes)]  label artwork, PDF or PNG
      docs      [{"name", "text"} or {"name", "raw"}]  case documents
      notes     [str]  what could not be read, and why
      embedded  [(name, png bytes)]  large pictures found inside Word or PowerPoint files"""
    doc_names = set(doc_names or ())
    art, docs, notes, embedded = [], [], [], []
    count = {"n": 0, "bytes": 0}

    def add_text(name, text, approx=False):
        text = _clip(text.strip())
        if not text:
            notes.append(f"{name}: no readable text was found in it.")
            return
        docs.append({"name": name, "text": text})
        if approx:
            notes.append(f"{name}: the text of this file type is read roughly, so check the figures against the original.")

    def handle(name, raw, depth, force_doc):
        count["n"] += 1
        count["bytes"] += len(raw)
        if count["n"] > MAX_FILES:
            if count["n"] == MAX_FILES + 1:
                notes.append(f"Only the first {MAX_FILES} files were read.")
            return
        if count["bytes"] > MAX_UNZIPPED:
            notes.append(f"{name}: skipped, the total size is too large.")
            return
        ext = _ext(name)
        try:
            if ext == ".pdf":
                fitz.open(stream=raw, filetype="pdf")
                (docs.append({"name": name, "raw": raw}) if (force_doc or all_docs) else art.append((name, raw)))
            elif ext in IMG_EXT or ext in ART_OTHER:
                items = _to_art(name, raw)
                if force_doc or all_docs:
                    docs.extend({"name": n, "raw": b} for n, b in items)
                else:
                    art.extend(items)
            elif ext == ".docx":
                add_text(name, _docx(raw))
                embedded.extend(_embedded_images(raw, name))
            elif ext == ".pptx":
                add_text(name, _pptx(raw))
                embedded.extend(_embedded_images(raw, name))
            elif ext in (".xlsx", ".xlsm"):
                add_text(name, _xlsx(raw))
            elif ext == ".xls":
                add_text(name, _xls(raw))
            elif ext in (".odt", ".ods", ".odp"):
                add_text(name, _odf(raw))
            elif ext == ".rtf":
                add_text(name, _rtf(raw), approx=True)
            elif ext == ".doc":
                t, approx = _doc(raw)
                add_text(name, t, approx)
            elif ext == ".ppt":
                add_text(name, _strings(raw), approx=True)
            elif ext in (".html", ".htm"):
                add_text(name, _html_text(_decode(raw)))
            elif ext in TEXT_EXT:
                add_text(name, _decode(raw))
            elif ext == ".eml":
                msg = email.message_from_bytes(raw, policy=policy.default)
                head = "\n".join(f"{k}: {msg[k]}" for k in ("From", "To", "Date", "Subject") if msg[k])
                body = msg.get_body(preferencelist=("plain", "html"))
                text = body.get_content() if body else ""
                if body is not None and body.get_content_type() == "text/html":
                    text = _html_text(text)
                add_text(name, head + "\n\n" + text)
                if depth < 2:
                    for part in msg.iter_attachments():
                        data = part.get_payload(decode=True)
                        if data:
                            handle(f"{name}/{part.get_filename() or 'attachment'}", data, depth + 1, False)
            elif ext == ".msg":
                notes.append(f"{name}: Outlook .msg files cannot be read. Save the e-mail as .eml or print it to PDF.")
            elif ext in (".zip",):
                if depth >= 2:
                    notes.append(f"{name}: a ZIP inside a ZIP was not opened.")
                else:
                    z = zipfile.ZipFile(io.BytesIO(raw))
                    if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                        notes.append(f"{name}: skipped, it unpacks to too much data.")
                    else:
                        for i in z.infolist():
                            if not i.is_dir() and not os.path.basename(i.filename).startswith(("._", "~$")) and "__MACOSX" not in i.filename:
                                handle(f"{name}/{i.filename}", z.read(i), depth + 1, False)
            elif _printable(raw):
                add_text(name, _decode(raw))
            else:
                notes.append(f"{name}: this file type cannot be read ({ext or 'no extension'}). Export it as PDF, Word, Excel or an image.")
        except Exception as e:
            notes.append(f"{name}: could not be read ({str(e)[:140]}).")

    for name, raw in blobs:
        handle(name, raw, 0, name in doc_names)

    def unique(items, get, put):  # two files can end up with the same name after conversion
        seen = {}
        out = []
        for it in items:
            n = get(it)
            seen[n] = seen.get(n, 0) + 1
            if seen[n] > 1:
                base, ext = os.path.splitext(n)
                it = put(it, f"{base}_{seen[n]}{ext}")
            out.append(it)
        return out

    art = unique(art, lambda x: x[0], lambda x, n: (n, x[1]))
    docs = unique(docs, lambda x: x["name"], lambda x, n: dict(x, name=n))
    embedded = unique(embedded, lambda x: x[0], lambda x, n: (n, x[1]))
    return art, docs, notes, embedded