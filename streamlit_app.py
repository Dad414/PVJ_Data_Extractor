import streamlit as st
import pandas as pd
import os
import time
import tempfile
import shutil
from typing import List, Dict, Any

# Internal modules
import extractor
import excel_writer
from config import DEFAULTS, Config

# Page Config
st.set_page_config(
    page_title="PVJ OCR Extractor",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Sidebar Settings ---
st.sidebar.title("⚙️ Settings")

st.sidebar.subheader("OCR Parameters")
contrast = st.sidebar.slider("Contrast Boost", 1.0, 5.0, 2.0, 0.1, help="Increase to make text darker against background.")
threshold = st.sidebar.slider("Binarization Threshold", 0, 255, 180, 5, help="Pixel value cutoff for black/white conversion.")
dpi = st.sidebar.number_input("OCR DPI", 150, 600, 450, 50, help="Higher DPI = slower but better accuracy.")

st.sidebar.subheader("Output")
output_dir = st.sidebar.text_input("Output Directory", os.path.expanduser("~/PVJ_Outputs"))

# --- Main UI ---
st.title("🌱 PVJ OCR Extractor")
st.markdown("""
Upload **Plant Variety Journal (PVJ)** PDFs to extract data into structured Excel reports.
You can review and edit the extracted data before saving.
""")

uploaded_files = st.file_uploader("Choose PDF files", type=["pdf"], accept_multiple_files=True)

if "extraction_results" not in st.session_state:
    st.session_state.extraction_results = {}

def process_file(uploaded_file, cfg: Config):
    # Save uploaded file to temp
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        # Progress callback
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(frac, detail):
            progress_bar.progress(frac)
            status_text.text(f"Processing {uploaded_file.name}: {detail.get('stage', '')} - Page {detail.get('page', '?')}")

        # Run Extraction
        df, summaries = extractor.extract_to_dataframe(
            pdf_path=tmp_path,
            config=cfg,
            progress_cb=update_progress,
            cancel_cb=lambda: False
        )
        
        progress_bar.empty()
        status_text.empty()
        
        return df, summaries

    finally:
        # Cleanup temp file
        try:
            os.remove(tmp_path)
        except:
            pass

if uploaded_files:
    if st.button(f"Start Extraction ({len(uploaded_files)} files)"):
        # Build Config
        cfg = Config(
            DPI=dpi,
            CONTRAST=contrast,
            BIN_THRESHOLD=threshold,
            LANG="eng",
            TARGET_CROPS=DEFAULTS.TARGET_CROPS,
            MAX_PAGES=None,
            ALLOW_HINDI=False,
            THREADS=DEFAULTS.THREADS,
            SAVE_INTERMEDIATE_IMAGES=False,
            DEBUG_OCR_TEXT=False,
            FIELD_PATTERNS=DEFAULTS.FIELD_PATTERNS,
        )

        for up_file in uploaded_files:
            with st.spinner(f"Processing {up_file.name}..."):
                df, summaries = process_file(up_file, cfg)
                st.session_state.extraction_results[up_file.name] = {
                    "df": df,
                    "summaries": summaries,
                    "processed": True
                }
        st.success("Batch processing complete!")

# --- Results Display ---
if st.session_state.extraction_results:
    st.divider()
    st.subheader("📝 Review & Download")
    
    tabs = st.tabs(list(st.session_state.extraction_results.keys()))
    
    for i, filename in enumerate(st.session_state.extraction_results.keys()):
        with tabs[i]:
            res = st.session_state.extraction_results[filename]
            df = res["df"]
            
            if df is not None and not df.empty:
                st.info(f"Extracted {len(df)} rows.")
                
                # Editable Dataframe
                edited_df = st.data_editor(
                    df,
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"editor_{filename}"
                )
                
                # Update stored DF with edits
                st.session_state.extraction_results[filename]["df"] = edited_df
                
                # Download Button
                # We need to generate the Excel in memory
                output = io.BytesIO()
                # We reuse excel_writer logic but need to adapt it to write to stream or temp file
                # Since excel_writer writes to a path, let's use a temp path
                
                if st.button(f"Prepare Download for {filename}", key=f"btn_{filename}"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_xls:
                        excel_writer.write_full_workbook(
                            df=edited_df,
                            summaries=res["summaries"],
                            out_path=tmp_xls.name,
                            config=DEFAULTS # Use defaults for writing config
                        )
                        tmp_xls_path = tmp_xls.name
                    
                    with open(tmp_xls_path, "rb") as f:
                        st.download_button(
                            label=f"⬇️ Download {filename.replace('.pdf', '.xlsx')}",
                            data=f,
                            file_name=filename.replace('.pdf', '.xlsx'),
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_{filename}"
                        )
            else:
                st.warning("No data extracted or empty file.")

import io
