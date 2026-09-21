"""Step 3: PDF -> text. Machine-readable text first (pdfplumber, then pypdf); OCR is never attempted silently.

Output: data/interim/bulletin_text/YYYY-MM.json holding per-page text plus extraction diagnostics. If neither library
recovers a usable text layer the bulletin is marked `needs_ocr` and routed to manual review instead of being dropped.
"""
import json

import pdfplumber
import pypdf

from . import config

MIN_CHARS_PER_PAGE = 300  # below this average a page is treated as having no usable text layer


def _pdfplumber_pages(path):
    with pdfplumber.open(path) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def _pypdf_pages(path):
    return [(p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages]


def extract_pdf(path) -> dict:
    errors = []
    for method, fn in (("pdfplumber", _pdfplumber_pages), ("pypdf", _pypdf_pages)):
        try:
            pages = fn(path)
        except Exception as e:  # corrupted PDFs must not stop the batch
            errors.append(f"{method}: {type(e).__name__}: {e}")
            continue
        chars = sum(len(p) for p in pages)
        if pages and chars / len(pages) >= MIN_CHARS_PER_PAGE:
            return {"method": method, "pages": pages, "n_pages": len(pages), "n_chars": chars, "errors": errors,
                    "has_text_layer": True}
        errors.append(f"{method}: text layer too thin ({chars} chars / {len(pages)} pages)")
    return {"method": "needs_ocr", "pages": [], "n_pages": 0, "n_chars": 0, "errors": errors, "has_text_layer": False}


def text_path(bid: str):
    return config.BULLETIN_TEXT / f"{bid}.json"


def extract_bulletin(bid: str, pdf_path, force: bool = False) -> dict:
    out = text_path(bid)
    if out.exists() and not force:
        return json.loads(out.read_text(encoding="utf-8"))
    res = extract_pdf(pdf_path)
    config.BULLETIN_TEXT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res
