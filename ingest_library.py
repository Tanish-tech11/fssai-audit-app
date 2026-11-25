"""Run this on the PC that holds the client's library. It reads every PDF page by page and
stores the text in Supabase so the web app can check findings against the real pages.

Usage (PowerShell, from the app folder):
    $env:SUPABASE_URL="https://xxxx.supabase.co"
    $env:SUPABASE_SERVICE_KEY="service_role_key"
    pip install pymupdf pytesseract pillow supabase
    python ingest_library.py "C:\\path\\to\\00_NUTRA LABEL AUDIT LIBRARY"

Scanned pages need Tesseract installed on this PC (https://github.com/UB-Mannheim/tesseract/wiki).
Without it, scanned pages are stored empty and listed at the end. Re-running skips unchanged files.
"""
import hashlib, os, sys
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz
from PIL import Image

OCR_DPI = 200
MIN_CHARS = 80


def ocr_page(page):
    import pytesseract
    pix = page.get_pixmap(dpi=OCR_DPI)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(im, lang=os.getenv("OCR_LANG", "eng"))


def clean(t):
    return t.replace("\x00", "").strip()


def main(root):
    from supabase import create_client
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        sys.exit("Set SUPABASE_URL and SUPABASE_SERVICE_KEY first.")
    sb = create_client(url, key)
    root = Path(root)
    if not root.is_dir():
        sys.exit(f"Folder not found: {root}\nCheck the path (right click the folder in VS Code > Copy Path).")
    pdfs = sorted(list(root.rglob("*.pdf")) + list(root.rglob("*.PDF")))
    pdfs = sorted(set(pdfs))
    if not pdfs:
        sys.exit(f"The folder exists but no PDF files were found in it: {root}\n"
                 "If the files show a cloud icon, set the folder to 'Always keep on this device' in OneDrive.")
    print(f"{len(pdfs)} PDFs found under {root}")
    have_ocr = True
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception:
        have_ocr = False
        print("Tesseract not found: scanned pages will be stored empty.")
    total_chars, problems = 0, []
    for i, p in enumerate(pdfs, 1):
        rel = p.relative_to(root).as_posix()
        sha = hashlib.sha1(p.read_bytes()).hexdigest()
        old = sb.table("library_files").select("sha1,empty_pages").eq("file", rel).execute().data
        if old and old[0]["sha1"] == sha and not (have_ocr and old[0]["empty_pages"]):
            print(f"[{i}/{len(pdfs)}] unchanged  {rel}")
            continue
        try:
            doc = fitz.open(p)
            rows, ocr_n, empty_n = [], 0, 0
            for n, page in enumerate(doc, 1):
                txt, ocr = clean(page.get_text("text")), False
                if len(txt) < MIN_CHARS and have_ocr:
                    try:
                        txt, ocr = clean(ocr_page(page)), True
                    except Exception:
                        pass
                ocr_n += ocr
                empty_n += len(txt) < 20
                total_chars += len(txt)
                rows.append({"file": rel, "page": n, "text": txt, "ocr": ocr})
            sb.table("library_pages").delete().eq("file", rel).execute()
            for k in range(0, len(rows), 50):
                sb.table("library_pages").insert(rows[k:k + 50]).execute()
            sb.table("library_files").upsert({
                "file": rel, "folder": rel.split("/")[0], "pages": len(rows), "ocr_pages": ocr_n,
                "empty_pages": empty_n, "sha1": sha}).execute()
            print(f"[{i}/{len(pdfs)}] {len(rows)} pages (ocr {ocr_n}, empty {empty_n})  {rel}")
            if empty_n:
                problems.append(f"{rel}: {empty_n} empty pages")
        except Exception as e:
            problems.append(f"{rel}: {e}")
            print(f"[{i}/{len(pdfs)}] FAILED {rel}: {e}")
    print(f"\nDone. About {total_chars / 1e6:.1f} million characters stored this run.")
    if problems:
        print("\nCheck these:")
        print("\n".join(problems))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])