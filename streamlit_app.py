import streamlit as st
import io
import pandas as pd
import os
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

# --- Session State Initialization ---
if "extraction_results" not in st.session_state:
    st.session_state.extraction_results = {}
if "custom_config" not in st.session_state:
    st.session_state.custom_config = {
        "contrast": 2.0,
        "threshold": 180,
        "dpi": 450,
        "output_dir": os.path.expanduser("~/PVJ_Outputs")
    }

# --- Sidebar Navigation ---
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["🏠 Home", "📊 Analysis", "⚙️ Settings"])

st.sidebar.divider()
st.sidebar.info(f"**Files Processed:** {len(st.session_state.extraction_results)}")

# --- Helper Functions ---
def process_file(uploaded_file, cfg: Config):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(frac, detail):
            progress_bar.progress(frac)
            status_text.text(f"Processing {uploaded_file.name}: {detail.get('stage', '')} - Page {detail.get('page', '?')}")

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
        try:
            os.remove(tmp_path)
        except:
            pass

# --- ⚙️ Settings Page ---
if page == "⚙️ Settings":
    st.title("⚙️ Settings")
    st.markdown("Configure OCR parameters and output preferences.")
    
    st.subheader("OCR Parameters")
    c1, c2, c3 = st.columns(3)
    with c1:
        contrast = st.slider("Contrast Boost", 1.0, 5.0, st.session_state.custom_config["contrast"], 0.1, help="Increase to make text darker against background.")
    with c2:
        threshold = st.slider("Binarization Threshold", 0, 255, st.session_state.custom_config["threshold"], 5, help="Pixel value cutoff for black/white conversion.")
    with c3:
        dpi = st.number_input("OCR DPI", 150, 600, st.session_state.custom_config["dpi"], 50, help="Higher DPI = slower but better accuracy.")
    
    st.subheader("Output")
    output_dir = st.text_input("Default Output Directory", st.session_state.custom_config["output_dir"])
    
    # Update session state immediately
    st.session_state.custom_config.update({
        "contrast": contrast,
        "threshold": threshold,
        "dpi": dpi,
        "output_dir": output_dir
    })
    
    st.info("Settings are automatically saved for this session.")

# --- 📊 Analysis Page ---
elif page == "📊 Analysis":
    st.title("📊 Analysis Dashboard")
    
    if not st.session_state.extraction_results:
        st.info("No data available. Please go to **Home** and extract some files first.")
    else:
        # Combine all dataframes
        all_dfs = []
        for res in st.session_state.extraction_results.values():
            if res["df"] is not None and not res["df"].empty:
                all_dfs.append(res["df"])
        
        if not all_dfs:
            st.warning("No valid data found in processed files.")
        else:
            combined_df = pd.concat(all_dfs, ignore_index=True)
            
            # Metrics
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Varieties", len(combined_df))
            m2.metric("Unique Crops", combined_df["Crop"].nunique())
            m3.metric("Applicants", combined_df["Applicant"].nunique())
            
            st.divider()
            
            c1, c2 = st.columns(2)
            
            with c1:
                st.subheader("Varieties by Crop")
                crop_counts = combined_df["Crop"].value_counts()
                st.bar_chart(crop_counts)
                
            with c2:
                st.subheader("Applicant Types")
                app_counts = combined_df["Applicant_Type"].value_counts()
                st.bar_chart(app_counts)
            
            st.subheader("Productivity Distribution (q/ha)")
            # Extract numeric productivity for histogram
            def parse_prod(x):
                try:
                    val = str(x).lower().replace("q/ha", "").strip()
                    return float(val)
                except:
                    return None
            
            combined_df["Yield_Q_Ha"] = combined_df["Productivity"].apply(parse_prod)
            
            # Filter out reasonable range for visualization
            valid_yields = combined_df["Yield_Q_Ha"].dropna()
            valid_yields = valid_yields[valid_yields < 200] # Remove extreme outliers
            
            if not valid_yields.empty:
                st.bar_chart(valid_yields)
            else:
                st.caption("No valid numeric productivity data found.")
            
            with st.expander("View Combined Data"):
                st.dataframe(combined_df)

# --- 🏠 Home Page ---
elif page == "🏠 Home":
    st.title("🌱 PVJ OCR Extractor")
    st.markdown("Upload **Plant Variety Journal (PVJ)** PDFs to extract data.")

    uploaded_files = st.file_uploader("Choose PDF files", type=["pdf"], accept_multiple_files=True)
    
    # Load settings
    defaults = st.session_state.custom_config

    if uploaded_files:
        if st.button(f"Start Extraction ({len(uploaded_files)} files)"):
            cfg = Config(
                DPI=defaults["dpi"],
                CONTRAST=defaults["contrast"],
                BIN_THRESHOLD=defaults["threshold"],
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
            st.success("Batch processing complete! Check the **Analysis** tab for insights.")

    # Results Display
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
                    
                    edited_df = st.data_editor(
                        df,
                        num_rows="dynamic",
                        use_container_width=True,
                        key=f"editor_{filename}"
                    )
                    
                    st.session_state.extraction_results[filename]["df"] = edited_df
                    
                    if st.button(f"Prepare Download for {filename}", key=f"btn_{filename}"):
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_xls:
                            excel_writer.write_full_workbook(
                                df=edited_df,
                                summaries=res["summaries"],
                                out_path=tmp_xls.name,
                                config=DEFAULTS 
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
