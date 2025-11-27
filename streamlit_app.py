import streamlit as st
import io
import pandas as pd
import os
import tempfile
import shutil
from typing import List, Dict, Any
import plotly.express as px
import plotly.graph_objects as go

# Internal modules
import extractor
import excel_writer
from config import DEFAULTS, Config

# Page Config
st.set_page_config(
    page_title="PVJ Research Extractor",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Load Custom CSS ---
def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

try:
    local_css("style.css")
except FileNotFoundError:
    pass # Fallback if css not found

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

def get_combined_dataframe():
    all_dfs = []
    for res in st.session_state.extraction_results.values():
        if res["df"] is not None and not res["df"].empty:
            all_dfs.append(res["df"])
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()

# --- Sidebar Navigation ---
with st.sidebar:
    st.title("🌿 PVJ Research")
    st.markdown("---")
    selected_page = st.radio(
        "Navigate", 
        ["Home", "Extractor", "Analytics", "Data Explorer", "Settings"],
        index=0
    )
    
    st.markdown("---")
    st.caption("Project Status")
    if st.session_state.extraction_results:
        st.success(f"{len(st.session_state.extraction_results)} Files Processed")
    else:
        st.info("Ready to extract")

# --- 🏠 Home Page ---
if selected_page == "Home":
    st.title("Welcome to PVJ Research Extractor")
    st.markdown("""
    ### Transform Plant Variety Journals into Actionable Data
    
    This tool is designed to assist researchers in extracting, analyzing, and visualizing data from Plant Variety Journals (PVJ).
    
    **Key Features:**
    - **📄 Intelligent OCR**: Extracts structured data from PDF journals.
    - **📊 Analytics Dashboard**: Visualize crop distribution, applicant trends, and productivity.
    - **🔍 Data Explorer**: Interactive search and filtering of extracted varieties.
    - **💾 Excel Export**: Download clean, structured datasets.
    
    **Get Started:**
    Go to the **Extractor** tab to upload your PDF files.
    """)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info("**Step 1: Upload**\n\nUpload your PVJ PDF files in the Extractor tab.")
    with c2:
        st.info("**Step 2: Process**\n\nOur engine extracts varieties, crops, and applicants.")
    with c3:
        st.info("**Step 3: Analyze**\n\nExplore trends and export data for your research.")

# --- 📄 Extractor Page ---
elif selected_page == "Extractor":
    st.title("📄 PDF Extractor")
    st.markdown("Upload your PVJ documents to begin extraction.")
    
    uploaded_files = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True)
    
    # Load settings
    defaults = st.session_state.custom_config

    if uploaded_files:
        col1, col2 = st.columns([1, 3])
        with col1:
            start_btn = st.button(f"🚀 Start Extraction", use_container_width=True)
        
        if start_btn:
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
            # Combine results
            final_df = get_combined_dataframe()
            
            if not final_df.empty:
                # 1. Save to Server Output Directory
                out_dir = defaults.get("output_dir", "")
                
                if out_dir:
                    try:
                        os.makedirs(out_dir, exist_ok=True)
                        timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
                        save_name = f"PVJ_Extracted_{timestamp}.xlsx"
                        saved_path = os.path.join(out_dir, save_name)
                        
                        final_df.to_excel(saved_path, index=False)
                        st.success(f"✅ Saved results to server: `{saved_path}`")
                    except Exception as e:
                        st.error(f"Could not save to server directory: {e}")

                # 2. Provide Download Button
                with io.BytesIO() as buffer:
                    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                        final_df.to_excel(writer, index=False, sheet_name='Extracted Data')
                    
                    st.download_button(
                        label="⬇️ Download All Results (Excel)",
                        data=buffer.getvalue(),
                        file_name=f"PVJ_Extracted_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

            st.balloons()
            st.success("Batch processing complete! Head to **Analytics** or **Data Explorer**.")

    # Mini-preview of results
    if st.session_state.extraction_results:
        st.divider()
        st.subheader("Recent Extractions")
        for filename, res in st.session_state.extraction_results.items():
            with st.expander(f"📄 {filename} ({len(res['df'])} varieties)"):
                st.dataframe(res['df'].head(5), use_container_width=True)

# --- 📊 Analytics Page ---
elif selected_page == "Analytics":
    st.title("📊 Research Analytics")
    
    df = get_combined_dataframe()
    
    if df.empty:
        st.warning("No data available. Please extract some files first.")
    else:
        # Top Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Varieties", len(df))
        m2.metric("Unique Crops", df["Crop"].nunique())
        m3.metric("Applicants", df["Applicant"].nunique())
        m4.metric("Avg Productivity", f"{df['Productivity'].str.extract(r'(\d+)').astype(float).mean().iloc[0]:.1f} q/ha" if not df.empty else "N/A")
        
        st.markdown("---")
        
        # Charts
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("Crop Distribution")
            crop_counts = df["Crop"].value_counts().reset_index()
            crop_counts.columns = ["Crop", "Count"]
            fig_crop = px.pie(crop_counts, values='Count', names='Crop', hole=0.4, color_discrete_sequence=px.colors.sequential.Teal)
            st.plotly_chart(fig_crop, use_container_width=True)
            
        with c2:
            st.subheader("Applicant Types")
            app_counts = df["Applicant_Type"].value_counts().reset_index()
            app_counts.columns = ["Type", "Count"]
            fig_app = px.bar(app_counts, x='Type', y='Count', color='Type', color_discrete_sequence=px.colors.qualitative.Prism)
            st.plotly_chart(fig_app, use_container_width=True)
        
        st.subheader("Productivity Analysis")
        
        # Parse productivity for chart
        def parse_prod(x):
            try:
                val = str(x).lower().replace("q/ha", "").strip()
                return float(val)
            except:
                return None
        
        df["Yield_Q_Ha"] = df["Productivity"].apply(parse_prod)
        valid_yields = df.dropna(subset=["Yield_Q_Ha"])
        valid_yields = valid_yields[valid_yields["Yield_Q_Ha"] < 200]
        
        if not valid_yields.empty:
            fig_hist = px.histogram(valid_yields, x="Yield_Q_Ha", color="Crop", nbins=20, title="Yield Distribution (q/ha)", color_discrete_sequence=px.colors.sequential.Viridis)
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("Insufficient productivity data for visualization.")

# --- 🔍 Data Explorer Page ---
elif selected_page == "Data Explorer":
    st.title("🔍 Data Explorer")
    
    df = get_combined_dataframe()
    
    if df.empty:
        st.warning("No data available.")
    else:
        # Filters
        c1, c2, c3 = st.columns(3)
        with c1:
            crops = ["All"] + list(df["Crop"].unique())
            sel_crop = st.selectbox("Filter by Crop", crops)
        with c2:
            types = ["All"] + list(df["Applicant_Type"].unique())
            sel_type = st.selectbox("Filter by Applicant Type", types)
        with c3:
            search = st.text_input("Search Variety or Applicant", "")
            
        # Apply filters
        filtered_df = df.copy()
        if sel_crop != "All":
            filtered_df = filtered_df[filtered_df["Crop"] == sel_crop]
        if sel_type != "All":
            filtered_df = filtered_df[filtered_df["Applicant_Type"] == sel_type]
        if search:
            filtered_df = filtered_df[
                filtered_df["Variety_Name"].str.contains(search, case=False, na=False) | 
                filtered_df["Applicant"].str.contains(search, case=False, na=False)
            ]
            
        st.markdown(f"**Showing {len(filtered_df)} varieties**")
        
        # Editable Dataframe
        edited_df = st.data_editor(
            filtered_df,
            num_rows="dynamic",
            use_container_width=True,
            key="data_explorer_editor"
        )
        
        # Export
        if st.button("💾 Export Filtered Data to Excel"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_xls:
                # Simple export for now, or use excel_writer if needed
                edited_df.to_excel(tmp_xls.name, index=False)
                tmp_xls_path = tmp_xls.name
            
            with open(tmp_xls_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download Excel",
                    data=f,
                    file_name="pvj_filtered_data.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

# --- ⚙️ Settings Page ---
elif selected_page == "Settings":
    st.title("⚙️ Configuration")
    
    st.subheader("OCR Engine Parameters")
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Image Pre-processing**")
        contrast = st.slider("Contrast Boost", 1.0, 5.0, st.session_state.custom_config["contrast"], 0.1)
        threshold = st.slider("Binarization Threshold", 0, 255, st.session_state.custom_config["threshold"], 5)
        
    with c2:
        st.markdown("**Recognition Settings**")
        dpi = st.number_input("Scan DPI", 150, 600, st.session_state.custom_config["dpi"], 50)
        output_dir = st.text_input("Output Directory", st.session_state.custom_config["output_dir"], help="Path on the server to save results. For local downloads, use the Download button after extraction.")
    
    if st.button("Save Settings"):
        st.session_state.custom_config.update({
            "contrast": contrast,
            "threshold": threshold,
            "dpi": dpi,
            "output_dir": output_dir
        })
        st.success("Settings saved successfully!")

