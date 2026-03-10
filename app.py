import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import plotly.express as px

# --- 1. SET PAGE CONFIG (MUST BE FIRST) ---
st.set_page_config(
    page_title="AMR National Surveillance | USYD",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. PROFESSIONAL HD THEMING (CSS) ---
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #e64646; color: white; font-weight: bold;
    }
    .stDownloadButton>button { background-color: #002b5c; color: white; }
    [data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
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
        
        # Privacy Redaction for metadata only
        safe_text = redact_text(full_text)
        
        # Dynamic Sample Type Detection (Jumps over blank lines)
        sample_type_match = re.search(r'SAMPLE\s*\n+\s*([^\n]+)', full_text)
        sample_type_val = sample_type_match.group(1).strip() if sample_type_match else "Unknown"

        sample_site = re.search(r'Swab:\s*(.+)', full_text)
        sample_site_val = sample_site.group(1).strip() if sample_site else "NA"

        # --- IMPROVED Isolate Chunking Logic (UNREDACTED text) ---
        isolate_pattern = r'\d+\.\s*(?:Heavy|Moderate|Light)\s*growth\s*-\s*([^\n]+)'
        parts = re.split(isolate_pattern, full_text)
        
        if len(parts) < 2:
            isolate_pattern_complex = r'(?:Heavy|Moderate|Light)\s*growth(?:.*?Identification)?\s*\n\s*([A-Z][a-z]+\s+[a-z]+)'
            parts = re.split(isolate_pattern_complex, full_text, flags=re.DOTALL)

        num_isolates = len(parts) // 2
        purity_val = "Mixed" if num_isolates > 1 else "Pure" if num_isolates == 1 else "NA"

        antibiotics_to_check = [
            "Penicillin", "Clindamycin", "Ticarcillin/clavulanic acid",
            "Ampicillin", "Amoxicillin/Clavulanic acid", "Amikacin",
            "Oxacillin", "Gentamicin (High Level)", "Gentamicin", "Imipenem", 
            "Chloramphenicol", "Trimethoprim/sulpha", "Vancomycin", 
            "Erythromycin", "Cefoxitin", "Rifampicin", "Doxycycline", 
            "Cefalexin", "Cefazolin", "Cefovecin", "Neomycin", "Ceftiofur",
            "Tobramycin", "Enrofloxacin", "Polymyxin B", "Marbofloxacin", 
            "Fusidic acid", "Nitrofurantoin"
        ]
        
        for i in range(1, len(parts), 2):
            isolate_species = parts[i].strip()
            isolate_text = parts[i+1]
            record = {
                "Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val, 
                "Age": age_val, "Sex": sex_val, "Neutered": neutered_val, 
                "Sample Type": sample_type_val, "Site": sample_site_val, 
                "Purity": purity_val, "Isolate": isolate_species
            }
            
            for abx in antibiotics_to_check:
                abx_parts = re.split(r'[\s/]+', abx)
                abx_pattern = r'[\s/]*'.join([re.escape(p) for p in abx_parts])
                
                match = re.search(rf'{abx_pattern}(?:[^a-zA-Z]+|(?:ug|mcg|mg|ml|L|MIC)\b)*\b(S|I|R|Susceptible|Intermediate|Resistant)\b', isolate_text, re.IGNORECASE)
                
                if match:
                    record[abx] = match.group(1).upper()[0]
                else:
                    record[abx] = "NA"
                    
            extracted_data.append(record)
    return extracted_data

# --- 5. SIDEBAR DESIGN (FIXED ICON) ---
with st.sidebar:
    # Reliable HTML-based badge instead of hotlinking external images
    st.markdown("""
        <div style="text-align: center; margin-bottom: 20px;">
            <div style="font-size: 50px; line-height: 1;">🏛️</div>
            <h2 style="color: #002b5c; margin-top: 10px; font-weight: bold;">USYD Vet Path</h2>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### 🛠️ Extraction Workflow")
    st.write("1. 📂 **Upload** Master Excel")
    st.write("2. 📄 **Drop** PDF Lab Reports")
    st.write("3. ⚡ **Process** & Redact")
    st.write("4. 📥 **Download** Final Sheet")
    st.markdown("---")
    st.success("🔒 **Privacy Mode Active:** Vets and Owner names are automatically redacted.")
    st.caption("Developed for Katherine Muscat | STAT3926 Project")

# --- 6. MAIN INTERFACE TABS ---
st.title("🔬 AMR National Surveillance Pipeline")
tab1, tab2 = st.tabs(["🚀 Data Processing", "📊 Live Analytics"])

with tab1:
    c1, c2 = st.columns(2)
    with c1: master_file = st.file_uploader("1. Existing Master Dataset (Excel)", type=["xlsx"])
    with c2: pdf_files = st.file_uploader("2. New PDF Reports", type=["pdf"], accept_multiple_files=True)

    if st.button("🚀 Process & Synchronize Dataset"):
        if pdf_files:
            processed_refs = set()
            master_df = pd.read_excel(master_file) if master_file else pd.DataFrame()
            if not master_df.empty and "Lab Reference" in master_df.columns:
                processed_refs = set(master_df["Lab Reference"].dropna().unique())

            new_records = []
            with st.spinner("Extracting isolates..."):
                for f in pdf_files:
                    try:
                        recs = parse_pdf_report(f)
                        if recs and recs[0]["Lab Reference"] not in processed_refs:
                            new_records.extend(recs)
                            processed_refs.add(recs[0]["Lab Reference"])
                    except Exception as e: 
                        st.error(f"Error processing {f.name}: {e}")

            if new_records or not master_df.empty:
                new_batch_df = pd.DataFrame(new_records)
                final_df = pd.concat([master_df, new_batch_df], ignore_index=True) if not master_df.empty else new_batch_df
                st.session_state['processed_data'] = final_df
                
                def color_sri(val):
                    colors = {'S': 'background-color: #C6EFCE; color: #006100', 'I': 'background-color: #FFEB9C; color: #9C5700', 'R': 'background-color: #FFC7CE; color: #9C0006'}
                    return colors.get(val, '')

                st.success(f"Successfully processed {len(new_records)} isolates.")
                st.dataframe(final_df.style.applymap(color_sri), use_container_width=True)
                
                buf = io.BytesIO()
                final_df.to_excel(buf, index=False)
                st.download_button("⬇️ Download Master Excel", buf.getvalue(), "AMR_Surveillance.xlsx", "application/vnd.ms-excel")
        else:
            st.error("Please upload PDFs to begin.")

with tab2:
    if 'processed_data' in st.session_state:
        df = st.session_state['processed_data']
        st.header("📊 Surveillance Insights")
        
        # Row 1: Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Isolates", len(df))
        m2.metric("Unique Cases", df["Lab Reference"].nunique())
        
        # Clean the column robustly as strings to prevent Pandas indexing errors
        df["Isolate"] = df["Isolate"].astype(str).str.strip()
        clean_species = df[(df["Isolate"] != "nan") & (df["Isolate"] != "NA") & (df["Isolate"] != "")]
        m3.metric("Bacterial Species", clean_species["Isolate"].nunique())
        st.divider()
        
        # Row 2: Charts
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.subheader("Bacterial Species Distribution")
            
            # FIXED CHART: Robust resetting of index and defining text explicitely 
            species_counts = clean_species["Isolate"].value_counts().rename_axis("Bacterial Species").reset_index(name="Isolate Count")
            
            fig_species = px.bar(
                species_counts, 
                x="Bacterial Species", 
                y="Isolate Count", 
                color="Bacterial Species", 
                text="Isolate Count", # Explicit mapping prevents text_auto rendering bugs
                color_discrete_sequence=px.colors.qualitative.Pastel, 
                template="plotly_white"
            )
            fig_species.update_layout(showlegend=False, xaxis={'categoryorder':'total descending'})
            st.plotly_chart(fig_species, use_container_width=True)

        with col_c2:
            st.subheader("Susceptibility Profiles")
            sir_check = df.isin(['S', 'I', 'R']).any()
            actual_abx_cols = sir_check[sir_check == True].index.tolist()
            if actual_abx_cols:
                sir_melt = df[actual_abx_cols].melt(var_name="Antibiotic", value_name="Result")
                sir_melt = sir_melt[sir_melt["Result"].isin(["S", "I", "R"])]
                fig_sir = px.histogram(sir_melt, x="Antibiotic", color="Result", barmode="group",
                                       color_discrete_map={'S': '#2ca02c', 'I': '#ffcc00', 'R': '#d62728'}, template="plotly_white")
                fig_sir.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig_sir, use_container_width=True)
            
        st.subheader("Breed Prevalence")
        st.plotly_chart(px.pie(df, names='Breed', hole=0.4, template="plotly_white"), use_container_width=True)
    else:
        st.info("💡 Process data in the first tab to unlock analytics.")
