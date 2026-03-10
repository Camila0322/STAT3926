import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import os

# --- 1. SET PAGE CONFIG (MUST BE FIRST) ---
st.set_page_config(
    page_title="AMR National Surveillance | USYD",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CUSTOM CSS FOR HD THEMING ---
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

# --- 4. CORE FUNCTIONS (Redact, Standardize, Parse) ---
def redact_text(text):
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "GPE", "LOC"]: 
            text = text.replace(ent.text, "[REDACTED]")
    return text

def standardize_age(age_string):
    if not age_string: return "NA"
    years, months = 0, 0
    year_match = re.search(r'(\d+)\s*(y|year|years)', age_string, re.IGNORECASE)
    if year_match: years = int(year_match.group(1))
    month_match = re.search(r'(\d+)\s*(m|month|months)', age_string, re.IGNORECASE)
    if month_match: months = int(month_match.group(1))
    if years == 0 and months == 0: return age_string 
    return f"{years}Y {months}M"

def parse_pdf_report(file_object):
    extracted_data = []
    with pdfplumber.open(file_object) as pdf:
        full_text = "".join(page.extract_text() + "\n" for page in pdf.pages)
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
        
        safe_text = redact_text(full_text)
        sample_site = re.search(r'Swab:\s*(.+)', safe_text)
        sample_site_val = sample_site.group(1).strip() if sample_site else "NA"

        isolate_pattern = r'\d+\.\s*(?:Heavy|Moderate|Light)\s*growth\s*-\s*([^\n]+)'
        parts = re.split(isolate_pattern, safe_text)
        num_isolates = len(parts) // 2
        purity_val = "Mixed" if num_isolates > 1 else "Pure" if num_isolates == 1 else "NA"

        abx_list = ["Penicillin", "Ampicillin", "Amoxicillin/Clavulanic acid", "Oxacillin", "Gentamicin", "Enrofloxacin", "Cefalexin", "Cefovecin"]
        
        for i in range(1, len(parts), 2):
            record = {
                "Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val, "Age": age_val,
                "Sex": sex_val, "Neutered": neutered_val, "Site": sample_site_val, "Purity": purity_val,
                "Isolate": parts[i].strip()
            }
            for abx in abx_list:
                match = re.search(rf'{re.escape(abx)}[^a-zA-Z]*([SIR])\b', parts[i+1], re.IGNORECASE)
                record[abx] = match.group(1).upper() if match else "NA"
            extracted_data.append(record)
    return extracted_data

# --- 5. SIDEBAR INSTRUCTIONS ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/en/thumb/5/50/University_of_Sydney_logo.svg/1200px-University_of_Sydney_logo.svg.png", width=150)
    st.title("User Instructions")
    st.info("""
    **Step 1:** Upload the current Master Excel file (if you have one).
    
    **Step 2:** Upload the new PDF diagnostic reports.
    
    **Step 3:** Click 'Process' to merge data. Duplicate lab references will be automatically skipped.
    
    **Step 4:** Download the updated surveillance sheet.
    """)
    st.divider()
    st.caption("Developed for Katherine Muscat | USYD Veterinary Pathology")

# --- 6. MAIN INTERFACE TABS ---
st.title("🔬 Antimicrobial Resistance Pipeline")
st.subheader("Automated Data Extraction & National Surveillance Logging")

tab1, tab2 = st.tabs(["🚀 Data Processing", "📊 Live Stats"])

with tab1:
    c1, c2 = st.columns(2)
    with c1:
        master_file = st.file_uploader("1. Existing Master Dataset (Excel)", type=["xlsx"])
    with c2:
        pdf_files = st.file_uploader("2. New PDF Reports (Multiple)", type=["pdf"], accept_multiple_files=True)

    if st.button("🚀 Process & Sync Data"):
        if pdf_files:
            processed_refs = set()
            master_df = pd.read_excel(master_file) if master_file else pd.DataFrame()
            if not master_df.empty and "Lab Reference" in master_df.columns:
                processed_refs = set(master_df["Lab Reference"].dropna().unique())

            new_records, skipped, failed = [], [], []

            with st.spinner("Analyzing isolates and redacting privacy data..."):
                for f in pdf_files:
                    try:
                        recs = parse_pdf_report(f)
                        if recs and recs[0]["Lab Reference"] not in processed_refs:
                            new_records.extend(recs)
                            processed_refs.add(recs[0]["Lab Reference"])
                        else:
                            skipped.append(f.name)
                    except:
                        failed.append(f.name)

            if new_records:
                new_df = pd.DataFrame(new_records)
                final_df = pd.concat([master_df, new_df], ignore_index=True) if not master_df.empty else new_df
                
                # SRI Color Styling
                def color_sri(val):
                    colors = {'S': 'background-color: #d1f2d1', 'I': 'background-color: #fff4cc', 'R': 'background-color: #ffdce0'}
                    return colors.get(val, '')

                styled_df = final_df.style.applymap(color_sri)
                
                st.success(f"Successfully added {len(new_records)} isolates.")
                st.dataframe(styled_df, use_container_width=True)

                # Export
                buf = io.BytesIO()
                styled_df.to_excel(buf, index=False)
                st.download_button("⬇️ Download Master Surveillance Sheet", buf.getvalue(), "AMR_Master_Updated.xlsx", "application/vnd.ms-excel")
            else:
                st.warning("No new unique records found.")

with tab2:
    st.write("This section will provide a visual summary of the resistance trends once data is processed.")
    # Placeholder for future HD-level Plotly charts
    st.metric(label="Total Isolates Processed", value="--")


