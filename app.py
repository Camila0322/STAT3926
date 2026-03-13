import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import plotly.express as px
from openpyxl.styles import PatternFill, Font

# --- 1. SET PAGE CONFIG ---
st.set_page_config(
    page_title="AMR National Surveillance | USYD",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. PROFESSIONAL HD THEMING ---
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
    if not isinstance(text, str): return "NA"
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
    return f"{years}Y {months}M"

def clean_boilerplate(text):
    lines = text.split('\n')
    scrubbed_lines = []
    junk_strings = ["SYDNEY SCHOOL", "FACULTY OF VET", "PATHOLOGY DIAGNOSTIC", "UNIVERSITY OF SYDNEY", "CRICOS", "ABN 15", "FINAL REPORT"]
    for line in lines:
        line_clean = line.strip()
        if not line_clean: continue
        if any(j.lower() in line_clean.lower() for j in junk_strings): continue
        if re.search(r'Page:\s*\d+|T[: \s]*02\s*9351|date:|Ref:', line_clean, re.IGNORECASE): continue
        scrubbed_lines.append(line_clean)
    return "\n".join(scrubbed_lines)

def parse_pdf_report(file_object):
    extracted_data = []
    skipped_isolates = []
    with pdfplumber.open(file_object) as pdf:
        raw_text = "".join(page.extract_text() + "\n" for page in pdf.pages)
        lab_ref = re.search(r'Our Ref:\s*([A-Z0-9]+\s*[\d\-]+|[A-Z0-9\-]+)', raw_text)
        lab_ref_val = lab_ref.group(1).strip() if lab_ref else "NA"
        species_breed = re.search(r'(Canine|Feline)[\s\-]+([a-zA-Z\s\-]+?)(?=\s*(?:\n|Male|Female|\d+\s*Years?|Our Ref|$))', raw_text, re.IGNORECASE)
        species_val = species_breed.group(1).strip() if species_breed else "NA"
        breed_val = species_breed.group(2).strip(" -") if species_breed else "NA"
        age_raw = re.search(r'(\d+\s*(?:Years?|Months?|Weeks?))', raw_text, re.IGNORECASE)
        age_val = standardize_age(age_raw.group(1)) if age_raw else "NA"
        gender_raw = re.search(r'(Male Neutered|Female Spayed|Male|Female)', raw_text, re.IGNORECASE)
        sex_val, neutered_val = ("Male", "Yes") if gender_raw and "Neutered" in gender_raw.group(1) else ("Female", "Yes") if gender_raw and "Spayed" in gender_raw.group(1) else (gender_raw.group(1), "No") if gender_raw else ("NA", "NA")
        
        clean_text = clean_boilerplate(raw_text)
        sample_blocks = re.split(r'^SAMPLE(?:\s+\d+)?\s*$', clean_text, flags=re.IGNORECASE | re.MULTILINE)
        blocks_to_process = sample_blocks[1:] if len(sample_blocks) > 1 else [clean_text]

        antibiotics_to_check = ["Penicillin", "Clindamycin", "Ticarcillin/clavulanic acid", "Ampicillin", "Amoxicillin/Clavulanic acid", "Amikacin", "Oxacillin", "Gentamicin", "Imipenem", "Chloramphenicol", "Trimethoprim/sulpha", "Vancomycin", "Erythromycin", "Cefoxitin", "Rifampicin", "Doxycycline", "Cefalexin", "Cefazolin", "Cefovecin", "Neomycin", "Ceftiofur", "Tobramycin", "Enrofloxacin", "Polymyxin B", "Marbofloxacin", "Fusidic acid", "Nitrofurantoin"]

        for block in blocks_to_process:
            sample_line = block.strip().split('\n')[0].strip()
            sample_type_val, sample_site_val = (sample_line.split(':', 1) + ["NA"])[:2] if ':' in sample_line else (sample_line, "NA")
            if sample_site_val == "NA":
                site_fallback = re.search(r'(Swab|Urine|Tissue|Implant):\s*(.+)', block, re.IGNORECASE)
                if site_fallback: sample_type_val, sample_site_val = site_fallback.groups()
            
            sample_site_val = redact_text(sample_site_val)
            isolate_names = []
            # Extract species without capturing the preceding number
            for m in re.finditer(r'([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))\s*(?:\n\s*)*SUSCEPTIBILITY', block): isolate_names.append(m.group(1))
            for m in re.finditer(r'MALDI-TOF Identification\s*\n+\s*(?:\d+\.\s*)?([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            for m in re.finditer(r'\b[1-9]\.\s+([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            if not isolate_names:
                for m in re.finditer(r'\b(Staphylococcus|Enterococcus|Pseudomonas|Proteus|Escherichia|Klebsiella|Pluralibacter|Bacteroides|Peptostreptococcus)\s+([a-z]+|spp\.|sp\.)\b', block, re.IGNORECASE): isolate_names.append(m.group(0))

            unique_isolates = sorted(list(set(isolate_names)), key=lambda x: block.find(x))
            for i, isolate_species in enumerate(unique_isolates):
                start_idx = block.find(isolate_species)
                end_idx = block.find(unique_isolates[i+1], start_idx + len(isolate_species)) if i + 1 < len(unique_isolates) else len(block)
                isolate_text = block[start_idx:end_idx]
                record = {"Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val, "Age": age_val, "Sex": sex_val, "Neutered": neutered_val, "Sample Type": sample_type_val.strip(), "Site": sample_site_val.strip(), "Isolate": isolate_species}
                has_sir = False
                for abx in antibiotics_to_check:
                    abx_esc = re.escape(abx).replace(r'Amoxicillin', r'Amox[iy]cillin').replace(r'Cefalexin', r'(?:Cefalexin|Cephalexin)')
                    match = re.search(rf'{abx_esc}(?:[^a-zA-Z]+)*\b(S|I|R|Susceptible|Intermediate|Resistant)\b', isolate_text, re.IGNORECASE)
                    if match:
                        record[abx] = match.group(1).upper()[0]
                        has_sir = True
                    else: record[abx] = "NA"
                if has_sir: extracted_data.append(record)
                else: skipped_isolates.append(f"{sample_type_val.strip()} - {isolate_species}")
    return extracted_data, skipped_isolates, lab_ref_val

# --- 5. INTERFACE ---
st.title("🔬 AMR National Surveillance Pipeline")
tab1, tab2 = st.tabs(["🚀 Data Processing", "📊 Live Analytics"])

with tab1:
    c1, c2 = st.columns(2)
    master_file = c1.file_uploader("1. Existing Master Dataset (Excel)", type=["xlsx"])
    pdf_files = c2.file_uploader("2. New PDF Reports", type=["pdf"], accept_multiple_files=True)

    if st.button("🚀 Process & Synchronize"):
        if pdf_files:
            master_df = pd.read_excel(master_file) if master_file else pd.DataFrame()
            new_records, skipped_summary = [], []
            total = len(pdf_files)
            pb = st.progress(0)
            
            for i, f in enumerate(pdf_files):
                pb.progress((i)/total, text=f"Scanning: {f.name}")
                recs, skip, ref = parse_pdf_report(f)
                new_records.extend(recs)
                if skip: skipped_summary.append(f"**{f.name}** (Excluded: {', '.join(skip)})")
            
            pb.progress(1.0, text="✅ Done!")

            final_df = pd.concat([master_df, pd.DataFrame(new_records)], ignore_index=True) if not master_df.empty else pd.DataFrame(new_records)
            st.session_state['processed_data'] = final_df
            
            st.dataframe(final_df.style.applymap(lambda v: {'S': 'background-color: #C6EFCE', 'I': 'background-color: #FFEB9C', 'R': 'background-color: #FFC7CE'}.get(v, '')), column_config={"Lab Reference": st.column_config.TextColumn(pinned=True)})
            
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                final_df.to_excel(writer, index=False, sheet_name="AMR")
            st.download_button("⬇️ Download Master Excel", buf.getvalue(), "AMR_Surveillance.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            if skipped_summary:
                st.info("### 📋 Skipped Data Summary\n" + "\n".join([f"- {s}" for s in skipped_summary]))

with tab2:
    if 'processed_data' in st.session_state:
        df = st.session_state['processed_data']
        st.header("📊 Global Surveillance Analytics")
        # Global frequency counting logic
        species_counts = df["Isolate"].value_counts().reset_index()
        species_counts.columns = ["Bacterial Species", "Global Count"]
        
        st.plotly_chart(px.bar(species_counts, x="Bacterial Species", y="Global Count", text="Global Count", template="plotly_white", color_discrete_sequence=['#002b5c']), use_container_width=True)
    else:
        st.info("💡 Process data to unlock analytics.")
