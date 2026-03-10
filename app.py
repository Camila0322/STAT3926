import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import os
import plotly.express as px

# --- 1. SET PAGE CONFIG (MUST BE THE ABSOLUTE FIRST ST COMMAND) ---
st.set_page_config(
    page_title="AMR National Surveillance | USYD",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. PROFESSIONAL HD THEMING (CSS) ---
st.markdown("""
    <style>
    .main {
        background-color: #f5f7f9;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        background-color: #e64646;
        color: white;
        font-weight: bold;
    }
    .stDownloadButton>button {
        background-color: #002b5c;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. MODEL LOADING ---
@st.cache_resource
def load_nlp():
    return spacy.load("en_core_web_sm")
nlp = load_nlp()

# --- 4. CORE PROCESSING FUNCTIONS ---
def redact_text(text):
    """Redacts sensitive human/location names for privacy compliance."""
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "GPE", "LOC"]: 
            text = text.replace(ent.text, "[REDACTED]")
    return text

def standardize_age(age_string):
    """Standardizes age formats to 'XY XM'."""
    if not age_string: return "NA"
    years, months = 0, 0
    year_match = re.search(r'(\d+)\s*(y|year|years)', age_string, re.IGNORECASE)
    if year_match: years = int(year_match.group(1))
    month_match = re.search(r'(\d+)\s*(m|month|months)', age_string, re.IGNORECASE)
    if month_match: months = int(month_match.group(1))
    if years == 0 and months == 0: return age_string 
    return f"{years}Y {months}M"

def parse_pdf_report(file_object):
    """Extracts metadata and susceptibility from PDF."""
    extracted_data = []
    with pdfplumber.open(file_object) as pdf:
        full_text = "".join(page.extract_text() + "\n" for page in pdf.pages)
        
        # Metadata Extraction
        lab_ref = re.search(r'Our Ref:\s*([A-Z0-9]+\s*[\d\-]+|[A-Z0-9\-]+)', full_text)
        lab_ref_val = lab_ref.group(1).strip() if lab_ref else "NA"
        
        species_breed = re.search(r'(Canine|Feline)\s+([a-zA-Z\s\-]+?)(?=\s+(?:Male|Female|\d+\s*Years?|Our Ref|Your Ref|$))', full_text, re.IGNORECASE)
        species_val = species_breed.group(1).strip() if species_breed else "NA"
        breed_val = species_breed.group(2).strip(" -") if species_breed else "NA"
        
        age_raw = re.search(r'(\d+\s*Years?)', full_text)
        age_val = standardize_age(age_raw.group(1)) if age_raw else "NA"
        
        gender_raw = re.search(r'(Male Neutered|Female Spayed|Male|Female)', full_text)
        sex_val, neutered_val = "NA", "NA"
        if gender_raw:
            g_str = gender_raw.group(1)
            sex_val = "Male" if "Male" in g_str else "Female"
            neutered_val = "Yes" if ("Neutered" in g_str or "Spayed" in g_str) else "No"
        
        # Privacy Redaction
        safe_text = redact_text(full_text)
        sample_site = re.search(r'Swab:\s*(.+)', safe_text)
        sample_site_val = sample_site.group(1).strip() if sample_site else "NA"

        # Isolate Chunking
        isolate_pattern = r'\d+\.\s*(?:Heavy|Moderate|Light)\s*growth\s*-\s*([^\n]+)'
        parts = re.split(isolate_pattern, safe_text)
        num_isolates = len(parts) // 2
        purity_val = "Mixed" if num_isolates > 1 else "Pure" if num_isolates == 1 else "NA"

        abx_list = ["Penicillin", "Ampicillin", "Amoxicillin/Clavulanic acid", "Oxacillin", 
                    "Gentamicin", "Enrofloxacin", "Cefalexin", "Cefovecin", "Chloramphenicol",
                    "Doxycycline", "Trimethoprim/sulpha"]
        
        for i in range(1, len(parts), 2):
            isolate_species = parts[i].strip()
            isolate_text = parts[i+1]
            record = {
                "Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val, 
                "Age": age_val, "Sex": sex_val, "Neutered": neutered_val, 
                "Site": sample_site_val, "Purity": purity_val, "Isolate": isolate_species
            }
            for abx in abx_list:
                match = re.search(rf'{re.escape(abx)}[^a-zA-Z]*([SIR])\b', isolate_text, re.IGNORECASE)
                record[abx] = match.group(1).upper() if match else "NA"
            extracted_data.append(record)
    return extracted_data

# --- 5. SIDEBAR DESIGN ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/en/thumb/5/50/University_of_Sydney_logo.svg/1200px-University_of_Sydney_logo.svg.png", width=180)
    st.title("Admin Panel")
    st.markdown("---")
    st.info("""
    **Workflow:**
    1. Upload Master Dataset (if available).
    2. Drop new PDF Lab Reports.
    3. The system redacts names and checks for duplicate Lab References.
    4. Download the updated National Surveillance File.
    """)
    st.markdown("---")
    st.caption("Developed for Katherine Muscat | USYD Veterinary Pathology")

# --- 6. MAIN INTERFACE TABS ---
st.title("🔬 AMR National Surveillance Pipeline")
st.subheader("Data Extraction & Clinical Analytics Dashboard")

tab1, tab2 = st.tabs(["🚀 Data Processing", "📊 Live Analytics"])

with tab1:
    c1, c2 = st.columns(2)
    with c1:
        master_file = st.file_uploader("1. Existing Master Dataset (Excel)", type=["xlsx"])
    with c2:
        pdf_files = st.file_uploader("2. New PDF Reports", type=["pdf"], accept_multiple_files=True)

    if st.button("🚀 Process & Synchronize Dataset"):
        if pdf_files:
            processed_refs = set()
            master_df = pd.read_excel(master_file) if master_file else pd.DataFrame()
            if not master_df.empty and "Lab Reference" in master_df.columns:
                processed_refs = set(master_df["Lab Reference"].dropna().unique())

            new_records, skipped, failed = [], [], []

            with st.spinner("Extracting isolates and applying privacy redaction..."):
                for f in pdf_files:
                    try:
                        recs = parse_pdf_report(f)
                        if recs:
                            if recs[0]["Lab Reference"] not in processed_refs:
                                new_records.extend(recs)
                                processed_refs.add(recs[0]["Lab Reference"])
                            else:
                                skipped.append(f.name)
                        else:
                            failed.append(f.name)
                    except Exception:
                        failed.append(f.name)

            if new_records or not master_df.empty:
                new_batch_df = pd.DataFrame(new_records)
                final_df = pd.concat([master_df, new_batch_df], ignore_index=True) if not master_df.empty else new_batch_df
                
                # Save to session state for the Analytics tab
                st.session_state['processed_data'] = final_df

                def color_sri(val):
                    colors = {'S': 'background-color: #C6EFCE; color: #006100', 
                              'I': 'background-color: #FFEB9C; color: #9C5700', 
                              'R': 'background-color: #FFC7CE; color: #9C0006'}
                    return colors.get(val, '')

                styled_df = final_df.style.applymap(color_sri)
                
                st.success(f"Successfully processed {len(new_records)} new isolates.")
                st.dataframe(styled_df, use_container_width=True)

                buf = io.BytesIO()
                styled_df.to_excel(buf, index=False, engine='openpyxl')
                st.download_button("⬇️ Download Master Surveillance Sheet", buf.getvalue(), "AMR_Surveillance_Updated.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            if skipped: st.warning(f"Skipped {len(skipped)} duplicate reports.")
            if failed: st.error(f"Failed to process: {', '.join(failed)}")
        else:
            st.error("Please upload PDF reports to begin.")

with tab2:
    if 'processed_data' in st.session_state:
        df = st.session_state['processed_data']
        st.header("📊 Surveillance Insights")
        
        # Metrics
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Total Bacterial Isolates", len(df))
        col_m2.metric("Unique Cases", df["Lab Reference"].nunique())
        col_m3.metric("Species Tracked", df["Isolate"].nunique())

        st.divider()
        
        # Charts
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.subheader("Bacterial Species Distribution")
            fig_species = px.bar(df["Isolate"].value_counts().reset_index(), x="Isolate", y="count", 
                                 labels={'count': 'Frequency'}, color="Isolate", template="plotly_white")
            st.plotly_chart(fig_species, use_container_width=True)

        with chart_col2:
            st.subheader("Susceptibility Profiles (S/I/R)")
            abx_cols = [c for c in df.columns if any(a in c for a in ["Ampicillin", "Enrofloxacin", "Cefalexin", "Oxacillin"])]
            sir_melt = df[abx_cols].melt(var_name="Antibiotic", value_name="Result")
            sir_melt = sir_melt[sir_melt["Result"].isin(["S", "I", "R"])]
            fig_sir = px.histogram(sir_melt, x="Antibiotic", color="Result", barmode="group",
                                   color_discrete_map={'S': '#2ca02c', 'I': '#ffcc00', 'R': '#d62728'}, template="plotly_white")
            st.plotly_chart(fig_sir, use_container_width=True)
            
        st.subheader("Breed Prevalence in Dataset")
        fig_breed = px.pie(df, names='Breed', hole=0.3, template="plotly_white")
        st.plotly_chart(fig_breed, use_container_width=True)
    else:
        st.info("💡 Process your data in the first tab to unlock live analytics.")
