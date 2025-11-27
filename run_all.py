#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PVJ Extractor — CLI & Batch Runner
Part 6/6 of ~3000-line app

Usage examples:
  python run_all.py input_pdfs/2025_08_v19_n7.pdf
  python run_all.py input_pdfs/*.pdf
  python run_all.py input_pdfs --recursive
  python run_all.py input_pdfs --dpi 500 --threads 4 --max-pages 100
  python run_all.py input_pdfs --crops rice cotton maize wheat tomato

Each PDF outputs to <OUTPUT_DIR>/<pdf_base>.xlsx (e.g., 2025_08_v19_n7.xlsx)
"""

from __future__ import annotations
import os
import sys
import glob
import time
import argparse
from typing import List, Dict, Any

import pandas as pd

# Internal modules
import extractor
import excel_writer
from config import DEFAULTS, OUTPUT_DIR, show_config, Config

SUPPORTED_PDF_EXTS = {".pdf", ".PDF"}


def find_pdfs(paths: List[str], recursive: bool) -> List[str]:
    """Expand globs/dirs/files into a unique list of PDF paths."""
    found: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            if recursive:
                for root, _, files in os.walk(p):
                    for f in files:
                        if os.path.splitext(f)[1] in SUPPORTED_PDF_EXTS:
                            found.append(os.path.join(root, f))
            else:
                for f in os.listdir(p):
                    fp = os.path.join(p, f)
                    if os.path.isfile(fp) and os.path.splitext(fp)[1] in SUPPORTED_PDF_EXTS:
                        found.append(fp)
        else:
            # glob expansion
            matched = glob.glob(p, recursive=recursive)
            for m in matched:
                if os.path.isfile(m) and os.path.splitext(m)[1] in SUPPORTED_PDF_EXTS:
                    found.append(m)
    # de-dup & stable order
    seen = set()
    unique = []
    for f in found:
        if f not in seen:
            seen.add(f)
            unique.append(os.path.abspath(f))
    return unique


def pdf_to_xlsx_name(pdf_path: str, out_dir: str) -> str:
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{base}.xlsx")


def progress_print(frac: float, detail: Dict[str, Any]):
    stage = detail.get("stage", "")
    page = detail.get("page", "")
    file = detail.get("file", "")
    pct = int(frac * 100)
    msg = f"[{pct:3d}%]"
    if file:
        msg += f" {file}"
    if stage:
        msg += f" | {stage}"
    if page:
        msg += f" p{page}"
    print(msg, end="\r", flush=True)


def build_cfg_from_args(args: argparse.Namespace) -> Config:
    cfg = Config(
        DPI=args.dpi if args.dpi else DEFAULTS.DPI,
        CONTRAST=args.contrast if args.contrast else DEFAULTS.CONTRAST,
        BIN_THRESHOLD=args.threshold if args.threshold else DEFAULTS.BIN_THRESHOLD,
        LANG="eng",
        TARGET_CROPS=[c.lower() for c in (args.crops if args.crops else DEFAULTS.TARGET_CROPS)],
        MAX_PAGES=args.max_pages,
        ALLOW_HINDI=False,
        THREADS=args.threads if args.threads else DEFAULTS.THREADS,
        SAVE_INTERMEDIATE_IMAGES=args.save_images,
        DEBUG_OCR_TEXT=args.debug_text,
        FIELD_PATTERNS=DEFAULTS.FIELD_PATTERNS,
    )
    return cfg


def process_one(pdf_path: str, cfg: Config, out_dir: str) -> str:
    """Run the full pipeline for a single PDF and write the Excel workbook."""
    out_xlsx = pdf_to_xlsx_name(pdf_path, out_dir)
    t0 = time.time()
    print(f"\n▶️  Processing: {pdf_path}")
    df, summaries = extractor.extract_to_dataframe(
        pdf_path=pdf_path,
        config=cfg,
        progress_cb=lambda f, s: progress_print(f, {**s, "file": os.path.basename(pdf_path)}),
        cancel_cb=lambda: False,
    )
    # tidy summaries: ensure dict exists
    summaries = summaries or {}

    # Write workbook
    excel_writer.write_full_workbook(df=df, summaries=summaries, out_path=out_xlsx, config=cfg)

    dt = time.time() - t0
    rows = 0 if df is None or df.empty else int(df.shape[0])
    print(f"\n✅ Done: {os.path.basename(pdf_path)} → {out_xlsx} "
          f"({rows} rows, {dt:.1f}s)")
    return out_xlsx


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PVJ OCR Extractor — CLI Batch Runner")
    p.add_argument("inputs", nargs="+", help="PDF files, folders, or globs")
    p.add_argument("--recursive", action="store_true", help="Recurse into folders")
    p.add_argument("--out", default=OUTPUT_DIR, help=f"Output folder (default: {OUTPUT_DIR})")

    # OCR / performance
    p.add_argument("--dpi", type=int, default=None, help="Render DPI for OCR (default from config)")
    p.add_argument("--contrast", type=float, default=None, help="Contrast boost (default from config)")
    p.add_argument("--threshold", type=int, default=None, help="Binarization threshold 0-255 (default from config)")
    p.add_argument("--threads", type=int, default=None, help="OCR threads (default from config)")
    p.add_argument("--max-pages", type=int, default=None, help="Limit pages (debug/speed)")

    # Filters
    p.add_argument("--crops", nargs="*", help="Filter crops (e.g., rice cotton maize wheat tomato)")

    # Debug
    p.add_argument("--debug-text", action="store_true", help="Save OCR text debug files")
    p.add_argument("--save-images", action="store_true", help="Save preprocessed page images used for OCR")

    # Info
    p.add_argument("--show-config", action="store_true", help="Print effective configuration and exit")

    return p.parse_args(argv)


def main(argv: List[str] | None = None):
    args = parse_args(argv or sys.argv[1:])
    cfg = build_cfg_from_args(args)

    if args.show_config:
        show_config(cfg)
        return 0

    pdfs = find_pdfs(args.inputs, recursive=args.recursive)
    if not pdfs:
        print("No PDFs found. Provide files/folders/globs. Example:")
        print("  python run_all.py input_pdfs/*.pdf")
        return 1

    print(f"Found {len(pdfs)} PDF(s). Output folder: {args.out}")
    os.makedirs(args.out, exist_ok=True)

    failures = 0
    outputs: List[str] = []
    t0 = time.time()

    for i, pdf in enumerate(pdfs, start=1):
        try:
            outputs.append(process_one(pdf, cfg, args.out))
        except Exception as e:
            failures += 1
            print(f"\n❌ Failed {os.path.basename(pdf)}: {e}")

    dt = time.time() - t0
    print("\n================ BATCH SUMMARY ================")
    print(f"Total PDFs: {len(pdfs)}")
    print(f"Succeeded : {len(outputs)}")
    print(f"Failed    : {failures}")
    print(f"Duration  : {dt:.1f}s")
    if outputs:
        print("\nOutputs:")
        for out in outputs:
            print("  -", out)
    print("===============================================")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
