#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PVJ Extractor — Configuration
Part 2/6 of ~3000-line app
Holds all tunable parameters, defaults, and helper utilities.
"""

import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Any

# ----------------------------------------------------------------------
# 📦 Default folders
# ----------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(ROOT_DIR, "input_pdfs")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output_excels")
LOG_DIR = os.path.join(ROOT_DIR, "logs")

for d in [INPUT_DIR, OUTPUT_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

# ----------------------------------------------------------------------
# ⚙️ General OCR + Parsing Settings
# ----------------------------------------------------------------------
@dataclass
class Config:
    DPI: int = 450
    CONTRAST: float = 2.0
    BIN_THRESHOLD: int = 180
    LANG: str = "eng"

    TARGET_CROPS: List[str] = None
    MAX_PAGES: int | None = None  # None = entire PDF
    ALLOW_HINDI: bool = False
    THREADS: int = 2
    SAVE_INTERMEDIATE_IMAGES: bool = False
    DEBUG_OCR_TEXT: bool = True

    FIELD_PATTERNS: Dict[str, List[str]] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------
# 🧠 Default regex patterns for field detection
# ----------------------------------------------------------------------
DEFAULT_PATTERNS = {
    "Variety_Name": [r"Variety Name[:\-–]?\s*([^\n]+)"],
    "Crop": [r"Crop[:\-–]?\s*([^\n]+)"],
    "Applicant": [
        r"(?:Applicant|By|Submitted by)[:\-–]?\s*([A-Za-z0-9&.,()' \-/]+)",
        r"Applicant[:\-–]?\s*([^\n]+)"
    ],
    "Developer_or_Breeder": [
        r"(?:Developer|Breeder|Developed by|Bred by)[:\-–]?\s*([^\n]+)"
    ],
    "Charter_of_Crop": [r"Charter of Crop[:\-–]?\s*([^\n]+)"],
    "Taxonomy": [r"Taxonomy[:\-–]?\s*([^\n]+)"],
    "Productivity": [r"Productivity[:\-–]?\s*([^\n]+)"],
    "Distinctiveness": [
        r"(?:Distinctiveness|Special Features)[:\-–]?\s*([^\n]+)"
    ],
}

# ----------------------------------------------------------------------
# 🌾 Crop filters
# ----------------------------------------------------------------------
DEFAULT_CROPS = ["rice", "cotton", "maize", "wheat", "tomato"]

# ----------------------------------------------------------------------
# 🪄 Assembled defaults instance
# ----------------------------------------------------------------------
DEFAULTS = Config(
    TARGET_CROPS=DEFAULT_CROPS,
    FIELD_PATTERNS=DEFAULT_PATTERNS
)

# ----------------------------------------------------------------------
# 💡 Utility to print current config for debugging
# ----------------------------------------------------------------------
def show_config(cfg: Config | None = None):
    cfg = cfg or DEFAULTS
    print("=== PVJ Extractor Configuration ===")
    for k, v in cfg.as_dict().items():
        print(f"{k:20s}: {v}")
    print("====================================")


if __name__ == "__main__":
    show_config()
