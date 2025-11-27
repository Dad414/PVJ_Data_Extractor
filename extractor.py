#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PVJ Extractor v4.0 — crop-agnostic, robust OCR parser with audits
Compatible with main_app.py (progress_cb, cancel_cb).
"""

from __future__ import annotations
import os, re
import pandas as pd
from typing import List, Dict, Any, Tuple, Callable
from tqdm import tqdm

# Local modules
from config import DEFAULTS
import ocr_utils

# ---------------------------- Utilities ---------------------------- #

DEVANAGARI_RANGE = re.compile(r"[\u0900-\u097F]")  # strip Hindi if present

def strip_non_english(s: str) -> str:
    if not isinstance(s, str):
        return ""
    # remove Devanagari, collapse spaces
    s = DEVANAGARI_RANGE.sub(" ", s)
    s = re.sub(r"[^\S\r\n]+", " ", s)
    return s.strip()

def clean_lines(block: str) -> List[str]:
    block = strip_non_english(block)
    lines = []
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln: continue
        # Filter noise: single chars that aren't common words, or mostly punctuation
        if len(ln) < 2 and ln.lower() not in ('a', 'i', 'x'):
            continue
        # Normalize spaces
        lines.append(re.sub(r"\s+", " ", ln))
    return lines

def safe(s: Any, default="NA") -> str:
    if s is None:
        return default
    if isinstance(s, float) and pd.isna(s):
        return default
    s = str(s).strip()
    return s if s else default

# ------------------------- Knowledge Bases ------------------------- #

# Big crop lexicon (expand anytime)
CROP_WORDS = [
    # cereals
    "rice","wheat","maize","barley","sorghum","millet","oat","rye",
    # pulses
    "gram","pigeonpea","lentil","blackgram","greengram","cowpea","fieldpea",
    # oilseeds
    "mustard","rapeseed","groundnut","sesame","sunflower","soybean","safflower","linseed","castor",
    # commercial
    "cotton","sugarcane","jute","tobacco","tea","coffee","coconut",
    # vegetables & fruits (common)
    "tomato","potato","onion","brinjal","chilli","okra","cabbage","cauliflower","cucumber","melon",
    # others often appearing
    "banana","papaya","pomegranate","guava","mango","pear","pearl millet","bajra","finger millet","ragi",
]

# Abbreviation expansion for applicants/institutes (extend as needed)
APPLICANT_MAP = {
    "CICR": "ICAR-Central Institute for Cotton Research",
    "DRR": "ICAR-Directorate of Rice Research",
    "ICAR": "Indian Council of Agricultural Research",
    "IARI": "ICAR-Indian Agricultural Research Institute (Pusa)",
    "JNKVV": "Jawaharlal Nehru Krishi Vishwavidyalaya",
    "IGKV": "Indira Gandhi Krishi Vishwavidyalaya",
    "ANGRAU": "Acharya N G Ranga Agricultural University",
    "PAU": "Punjab Agricultural University",
    "TNAU": "Tamil Nadu Agricultural University",
    "UAS": "University of Agricultural Sciences",
    "MPKV": "Mahatma Phule Krishi Vidyapeeth (Phule/ Rahuri)",
    "BHU": "Banaras Hindu University",
    "BARC": "Bhabha Atomic Research Centre (Trombay)",
    "JNARDDC": "Jawaharlal Nehru Aluminium Research Dev & Design Centre",
    "PUSA": "ICAR-Indian Agricultural Research Institute (Pusa)",
    "JKV": "Jawahar Krishi Vishwavidyalaya",
    "JAWAHAR": "JNKVV-Jawahar",
    "CHHATTISGARH": "IGKV-Chhattisgarh Agricultural University",
}

PUBLIC_HINTS = [
    "icar","university","college","institute","govt","government","research","krishi","angrau","pau","tnau",
    "uas","jknvv","jnkvv","iari","pusa","barc","igkv","mpkv","bhu","gov","component project","directorate"
]
PRIVATE_HINTS = ["pvt","private","limited","ltd","seeds","seed","biotech","agro","genetics","lifecycle","company","industries"]
FARMER_HINTS = ["farmer","grower"]

# Cotton taxonomy markers
COTTON_TAXA = [
    ("Tetraploid Cotton","tetraploid cotton|t\.\s*cotton|g\. hirsutum|gossypium hirsutum"),
    ("Diploid Cotton","diploid cotton|d\.\s*cotton|g.*arboreum|gossypium arboreum"),
]

VARIETY_TYPE_WORDS = [("Extant","extant"), ("Notified","notified"), ("New","new"), ("Hybrid","hybrid")]

# ------------------------ Field Classifiers ------------------------ #

def classify_applicant_type(name: str) -> str:
    n = name.lower()
    if any(k in n for k in FARMER_HINTS): return "Farmer"
    if any(k in n for k in PRIVATE_HINTS): return "Private Sector"
    if any(k in n for k in PUBLIC_HINTS): return "Public / Govt"
    # If the expanded name is from APPLICANT_MAP we default to Public/Govt
    for abbr, full in APPLICANT_MAP.items():
        if abbr.lower() in n or full.lower() in n:
            return "Public / Govt"
    return "Other" if name not in ("", "NA") else "NA"

def expand_applicant(token: str) -> str:
    if not token: return "NA"
    token_up = re.sub(r"[^A-Z]", "", token.upper())
    for abbr, full in APPLICANT_MAP.items():
        if token_up.startswith(abbr):
            return full
    return token

def detect_variety_type(block: str) -> str:
    b = block.lower()
    for label, key in VARIETY_TYPE_WORDS:
        if key in b: return label
    return "NA"

def infer_crop(block: str) -> str:
    b = " " + block.lower() + " "
    for w in CROP_WORDS:
        if f" {w} " in b:
            return w.capitalize()
    # extra: “T. Cotton / D. Cotton / Tetraploid Cotton”
    if re.search(r"\b(t\.|tetraploid)\s*cotton\b", b): return "Cotton"
    if re.search(r"\b(d\.|diploid)\s*cotton\b", b): return "Cotton"
    return "NA"

def detect_taxonomy(block: str, crop: str) -> str:
    if crop != "Cotton": return "NA"
    b = block.lower()
    for label, pat in COTTON_TAXA:
        if re.search(pat, b): return label
    return "NA"

def normalize_units(value: float, unit: str) -> float:
    unit = (unit or "q/ha").lower().replace(" ", "")
    if unit in ("q/ha","quintal/ha","quintals/ha","quintalperhectare"): return value
    if unit in ("t/ha","ton/ha","tons/ha","tonnes/ha"): return value * 10.0
    if unit in ("kg/ha","kgs/ha","kilogram/ha"): return value / 100.0
    if unit in ("q/acre","quintal/acre","quintals/acre"): return value * 2.47
    if unit in ("t/acre","ton/acre","tons/acre"): return value * 24.7
    if unit in ("kg/acre","kgs/acre"): return value / 40.47
    # unknown -> assume already q/ha
    return value

def detect_productivity(block: str) -> Tuple[str, str]:
    """
    Return (normalized_text, unit_confidence)
    normalized_text is like '45 q/ha' or 'NA'.
    """
    b = strip_non_english(block)
    # primary explicit patterns with unit
    pat = r"(\d+(?:\.\d+)?)\s*(q/ha|t/ha|tons/ha|ton/ha|kg/ha|q/acre|t/acre|kg/acre)"
    m = list(re.finditer(pat, b, flags=re.I))
    if m:
        val = float(m[-1].group(1))
        unit = m[-1].group(2)
        qha = normalize_units(val, unit)
        if 5 <= qha <= 150:
            return (f"{round(qha,2)} q/ha", "High")
    # secondary: nice lone number lines within plausible range (q/ha)
    for ln in clean_lines(b)[-5:]:  # last few lines often carry numeric cues
        if re.fullmatch(r"\d{1,3}(?:\.\d+)?", ln):
            try:
                v = float(ln)
                if 5 <= v <= 150:
                    return (f"{v} q/ha", "Medium")
            except: pass
    return ("NA","Low")

def extract_variety_name(lines: List[str]) -> str:
    if not lines: return "NA"
    # If second line looks like code in parentheses, join 1st+2nd
    if len(lines) >= 2 and re.search(r"\((?!Notified|Extant|New)[^)]+\)", lines[1]) and len(lines[1]) < 50:
        return f"{lines[0]} {lines[1]}".strip()
    # Else if second line short (<= 30 chars) and first doesn’t end with punctuation, join
    if len(lines) >= 2 and len(lines[1]) <= 30 and not re.search(r"[.:;]$", lines[0]):
        return f"{lines[0]} {lines[1]}".strip()
    return lines[0].strip()

def infer_applicant_from_header(lines: List[str]) -> str:
    if not lines: return "NA"
    token = lines[0].split()[0]
    token = re.sub(r"[^A-Za-z]", "", token)
    return expand_applicant(token) if token else "NA"

def parse_taxonomy_charter(block: str) -> Tuple[str,str]:
    """
    Returns (taxonomy, charter_hint). Charter hint is any phrase that looks like a
    short characterization signal (e.g., disease resistance/yield claim) if present.
    """
    crop = infer_crop(block)
    taxonomy = detect_taxonomy(block, crop)
    # charter hint - look for small descriptive chunks (very light heuristic)
    charter = "NA"
    m = re.search(r"(resistant|tolerant|suitable|high\s+yield|early\s+maturity|drought|flood)\b.*", block, flags=re.I)
    if m:
        charter = m.group(0).strip()
        charter = re.sub(r"\s+", " ", charter)
        if len(charter) > 100: charter = charter[:100] + "…"
    return taxonomy, charter

# ---------------------- Block → Entry Parsing ---------------------- #

def parse_block(block: str) -> Dict[str, Any]:
    block = strip_non_english(block)
    lines = clean_lines(block)

    entry: Dict[str, Any] = {
        "Variety_Name": "NA",
        "Crop": "NA",
        "Variety_Type": "NA",
        "Applicant": "NA",
        "Applicant_Type": "NA",
        "Charter_of_Crop": "NA",
        "Taxonomy": "NA",
        "Productivity": "NA",
        "Productivity_Confidence": "Low",
        "Distinctiveness": "NA",
        "Developer_or_Breeder": "NA",
        "Block_Text": safe(block),
    }

    if not lines:
        return entry

    entry["Variety_Name"] = extract_variety_name(lines)
    entry["Crop"] = infer_crop(block)
    entry["Variety_Type"] = detect_variety_type(block)

    prod, conf = detect_productivity(block)
    entry["Productivity"] = prod
    entry["Productivity_Confidence"] = conf

    # Applicant / Breeder
    applicant = infer_applicant_from_header(lines)
    entry["Applicant"] = applicant
    entry["Developer_or_Breeder"] = applicant
    entry["Applicant_Type"] = classify_applicant_type(applicant)

    # Taxonomy & charter hints
    taxonomy, charter = parse_taxonomy_charter(block)
    entry["Taxonomy"] = taxonomy
    entry["Charter_of_Crop"] = charter

    return entry

# --------------------- Page Text → Entries ------------------------ #

def parse_entries_from_text(text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    text = strip_non_english(text)

    # split by the registration anchor
    anchor = re.compile(r"(REG/\d{4}/\d+)", flags=re.I)
    chunks = re.split(anchor, text)

    if len(chunks) < 2:
        return entries

    for i in range(1, len(chunks), 2):
        reg_no = chunks[i].strip()
        block = chunks[i+1] if i+1 < len(chunks) else ""
        # skip tiny noise blocks
        if len(block.strip()) < 15: 
            continue
        # Must contain at least a crop word somewhere; if none, still keep (crop-agnostic mode),
        # but we’ll try inferring anyway.
        entry = parse_block(block)
        entry["Reg_No"] = reg_no
        entries.append(entry)

    return entries

# ----------------------- Orchestrator ----------------------------- #

def extract_to_dataframe(
    pdf_path: str,
    config=None,
    progress_cb: Callable[[float, Dict[str, Any]], None] | None = None,
    cancel_cb: Callable[[], bool] | None = None
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    Full pipeline: OCR/native text -> parse -> DataFrame (+ summaries).
    """
    cfg = config or DEFAULTS

    # 1) Hybrid extract
    texts = ocr_utils.hybrid_extract_text(pdf_path, cfg, progress_cb, cancel_cb)
    total = len(texts) if texts else 1

    # 2) Parse per page
    rows: List[Dict[str, Any]] = []
    for i, page_text in enumerate(tqdm(texts, desc="Parsing pages"), start=1):
        if cancel_cb and cancel_cb(): break
        page_entries = parse_entries_from_text(page_text)
        for e in page_entries:
            e["Page_Number"] = i
        rows.extend(page_entries)
        if progress_cb: progress_cb(i/total, {"page": i, "stage": "parse"})

    # 3) DataFrame assembly
    df = pd.DataFrame(rows)

    required = [
        "Reg_No","Variety_Name","Crop","Variety_Type","Applicant","Applicant_Type",
        "Charter_of_Crop","Taxonomy","Productivity","Productivity_Confidence",
        "Distinctiveness","Developer_or_Breeder","Page_Number","Block_Text"
    ]
    for c in required:
        if c not in df.columns: df[c] = "NA"
    df = df[required].drop_duplicates(subset=["Reg_No"]).reset_index(drop=True)

    # 4) Audit flags (row-level)
    df["Audit_Flags"] = df.apply(_row_audit_flags, axis=1)

    # 5) Summaries
    summaries: Dict[str, pd.DataFrame] = {}
    if not df.empty:
        summaries["Summary_Crop"] = (
            df.groupby("Crop")["Reg_No"].count().reset_index(name="Count").sort_values("Count", ascending=False)
        )
        summaries["Summary_Applicant_Type"] = (
            df.groupby("Applicant_Type")["Reg_No"].count().reset_index(name="Count").sort_values("Count", ascending=False)
        )
        summaries["Summary_Variety_Type"] = (
            df.groupby("Variety_Type")["Reg_No"].count().reset_index(name="Count").sort_values("Count", ascending=False)
        )

    return df, summaries

# ------------------------- Audits -------------------------------- #

def _row_audit_flags(r: pd.Series) -> str:
    flags = []

    if r.get("Variety_Name","NA") in ("NA",""):
        flags.append("no_variety_name")

    crop = r.get("Crop","NA")
    if crop == "NA":
        flags.append("crop_unknown")

    vt = r.get("Variety_Type","NA")
    if vt == "NA":
        flags.append("variety_type_missing")

    prod = r.get("Productivity","NA")
    if prod == "NA":
        flags.append("productivity_missing")
    else:
        try:
            val = float(str(prod).replace("q/ha","").strip())
            if not (5 <= val <= 150):
                flags.append("productivity_out_of_range")
        except:
            flags.append("productivity_unparsable")

    if r.get("Applicant","NA") == "NA":
        flags.append("applicant_missing")

    # Cotton taxonomy sanity
    if crop == "Cotton" and r.get("Taxonomy","NA") == "NA":
        # OK to be NA, but helpful to nudge review
        flags.append("cotton_taxonomy_unknown")

    return ",".join(flags) if flags else "OK"

# ------------------------ CLI Debug ------------------------------- #

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python extractor.py <file.pdf>")
        raise SystemExit(1)
    pdf = sys.argv[1]
    if not os.path.exists(pdf):
        print("File not found:", pdf); raise SystemExit(1)
    df, sums = extract_to_dataframe(pdf)
    print(df.head(20).to_string(index=False))
    for k, v in sums.items():
        print("\n--", k, "--\n", v.to_string(index=False))
