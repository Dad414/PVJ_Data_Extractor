#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PVJ Extractor — OCR Utilities
Part 3/6 of ~3000-line app
Handles page rendering, preprocessing, and text extraction from PDFs.
"""

import io
import os
import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import concurrent.futures
import re
from typing import List, Dict, Any, Callable, Tuple
from tqdm import tqdm

# Import settings from config.py
try:
    from config import DEFAULTS
except ImportError:
    DEFAULTS = None


# ----------------------------------------------------------------------
# 🧩 Helper: preprocessing for better OCR results
# ----------------------------------------------------------------------
def preprocess_image(img: Image.Image, contrast=2.0, threshold=180) -> Image.Image:
    """
    Convert PDF-rendered page to grayscale, sharpen, enhance contrast, and binarize.
    """
    gray = img.convert("L")  # grayscale
    sharp = gray.filter(ImageFilter.SHARPEN)
    enhanced = ImageEnhance.Contrast(sharp).enhance(contrast)
    bw = enhanced.point(lambda x: 0 if x < threshold else 255, "1")
    return bw


# ----------------------------------------------------------------------
# 🧩 OCR single page
# ----------------------------------------------------------------------
def ocr_page(
    page,
    dpi: int = 450,
    lang: str = "eng",
    contrast: float = 2.0,
    threshold: int = 180,
    debug_dir: str | None = None,
) -> str:
    """
    Perform OCR on a single PyMuPDF page.
    Returns the recognized English text.
    """
    try:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img = preprocess_image(img, contrast, threshold)

        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            debug_path = os.path.join(debug_dir, f"page_{page.number+1}.png")
            img.save(debug_path)

        text = pytesseract.image_to_string(img, lang=lang)
        text = re.sub(r"[\u0900-\u097F]+", "", text)  # remove Hindi text
        return text.strip()
    except Exception as e:
        return f"[OCR ERROR: {e}]"


# ----------------------------------------------------------------------
# 🧩 OCR multiple pages (parallelized)
# ----------------------------------------------------------------------
def ocr_document(
    pdf_path: str,
    cfg=None,
    progress_cb: Callable[[float, Dict[str, Any]], None] | None = None,
    cancel_cb: Callable[[], bool] | None = None,
) -> List[str]:
    """
    Perform OCR for all or selected pages of a PDF.
    Uses ThreadPoolExecutor for speed.
    Returns a list of text (one per page).
    """
    cfg = cfg or DEFAULTS
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    pages = range(total_pages) if cfg.MAX_PAGES is None else range(min(cfg.MAX_PAGES, total_pages))
    texts: List[str] = [""] * len(pages)

    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.THREADS) as executor:
        future_to_i = {
            executor.submit(ocr_page, doc[i], cfg.DPI, cfg.LANG, cfg.CONTRAST, cfg.BIN_THRESHOLD,
                            os.path.join("debug_pages") if cfg.DEBUG_OCR_TEXT else None): i
            for i in pages
        }

        for count, future in enumerate(concurrent.futures.as_completed(future_to_i), start=1):
            if cancel_cb and cancel_cb():
                break
            i = future_to_i[future]
            try:
                texts[i] = future.result()
            except Exception as e:
                texts[i] = f"[ERROR: {e}]"
            if progress_cb:
                progress_cb(count / len(pages), {"page": i + 1, "stage": "ocr"})

    doc.close()
    return texts


# ----------------------------------------------------------------------
# 🧩 Extract text (OCR + digital hybrid)
# ----------------------------------------------------------------------
def hybrid_extract_text(
    pdf_path: str,
    cfg=None,
    progress_cb: Callable[[float, Dict[str, Any]], None] | None = None,
    cancel_cb: Callable[[], bool] | None = None,
) -> List[str]:
    """
    Try text extraction first, then fallback to OCR if text is missing or too short.
    """
    cfg = cfg or DEFAULTS
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    texts = []

    for i in tqdm(range(total_pages), desc="Reading pages"):
        if cancel_cb and cancel_cb():
            break

        page = doc[i]
        text = page.get_text("text").strip()
        text = re.sub(r"[\u0900-\u097F]+", "", text)
        if len(text) < 150:  # too short → fallback to OCR
            text = ocr_page(page, cfg.DPI, cfg.LANG, cfg.CONTRAST, cfg.BIN_THRESHOLD)
        texts.append(text)

        if progress_cb:
            progress_cb((i + 1) / total_pages, {"page": i + 1, "stage": "read"})

    doc.close()
    return texts


# ----------------------------------------------------------------------
# 🧩 Simple debug utility
# ----------------------------------------------------------------------
def save_debug_texts(pdf_path: str, texts: List[str], out_dir="debug_texts"):
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    for i, t in enumerate(texts, start=1):
        fpath = os.path.join(out_dir, f"{base}_page{i}.txt")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(t)


# ----------------------------------------------------------------------
# 🧩 Command-line test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ocr_utils.py <pdf_path>")
        sys.exit(1)

    pdf = sys.argv[1]
    print(f"OCR scanning {pdf} ...")
    texts = hybrid_extract_text(pdf)
    print(f"Extracted {len(texts)} pages.")
    save_debug_texts(pdf, texts)
    print("Saved OCR debug text files.")
