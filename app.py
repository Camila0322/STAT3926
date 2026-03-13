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
    """Redacts sensitive human/location names for privacy compliance."""
    if not isinstance(text, str): return "NA"
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
    return f"{years}Y {months}M"

def clean_boilerplate(text):
    """Stitches clinical data across page breaks by removing redundant headers/footers."""
    lines = text.split('\n')
    scrubbed_lines = []
    # Targeted strings from the provided PDF sources [cite: 1, 34, 73, 114, 151, 184, 223, 289, 323, 348, 383, 411]
    junk_strings = [
        "SYDNEY SCHOOL", "FACULTY OF VET", "PATHOLOGY DIAGNOSTIC", 
        "UNIVERSITY OF SYDNEY", "CRICOS", "ABN 15", "FINAL REPORT", 
        "MICROBIOLOGY REPORT", "Evelyn Williams Building", "McMaster Building"
    ]
    for line in lines:
        line_clean = line.strip()
        if not line_clean: continue
        if any(j.lower() in line_clean.lower() for j in junk_strings): continue
        # Matches patterns like "Page: 1 of 5" or phone numbers [cite: 31, 37, 59]
        if re.search(r'Page:\s*\d+|T[: \s]*02\s*9351|date:|Ref:', line_clean, re.IGNORECASE): continue
        scrubbed_lines.append(line_clean)
    return "\n".join(scrubbed_lines)

def parse_pdf_report(file_object):
    """Extracts metadata and susceptibility from PDF robustly."""
    extracted_data = []
    skipped_isolates = []
    with pdfplumber.open(file_object) as pdf:
        raw_text = "".join(page.extract_text() + "\n" for page in pdf.pages)
        
        # Metadata Extraction [cite: 30, 57, 130, 204, 297, 357]
        lab_ref = re.search(r'Our Ref:\s*([A-Z0-9]+\s*[\d\-]+|[A-Z0-9\-]+)', raw_text)
        lab_ref_val = lab_ref.group(1).strip() if lab_ref else "NA"
        
        # Species/Breed [cite: 11, 192, 293, 352]
        species_breed = re.search(r'(Canine|Feline)[\s\-]+([a-zA-Z\s\-]+?)(?=\s*(?:\n|Male|Female|\d+\s*Years?|Our Ref|$))', raw_text, re.IGNORECASE)
        species_val = species_breed.group(1).strip() if species_breed else "NA"
        breed_val = species_breed.group(2).strip(" -") if species_breed else "NA"
        
        age_raw = re.search(r'(\d+\s*(?:Years?|Months?|Weeks?))', raw_text, re.IGNORECASE)
        age_val = standardize_age(age_raw.group(1)) if age_raw else "NA"
        
        gender_raw = re.search(r'(Male Neutered|Female Spayed|Male|Female)', raw_text, re.IGNORECASE)
        if gender_raw:
            g_str = gender_raw.group(1).title()
            sex_val = "Male" if "Male" in g_str else "Female"
            neutered_val = "Yes" if ("Neutered" in g_str or "Spayed" in g_str) else "No"
        else:
            sex_val, neutered_val = "NA", "NA"

        clean_text = clean_boilerplate(raw_text)
        # Split by SAMPLE markers, ensuring it's the full line [cite: 14, 95, 195, 213, 301, 360]
        sample_blocks = re.split(r'^SAMPLE(?:\s+\d+)?\s*$', clean_text, flags=re.IGNORECASE | re.MULTILINE)
        blocks_to_process = sample_blocks[1:] if len(sample_blocks) > 1 else [clean_text]

        antibiotics_to_check = [
            "Penicillin", "Clindamycin", "Ticarcillin/clavulanic acid", "Ampicillin", 
            "Amoxicillin/Clavulanic acid", "Amikacin", "Oxacillin", "Gentamicin", 
            "Imipenem", "Chloramphenicol", "Trimethoprim/sulpha", "Vancomycin", 
            "Erythromycin", "Cefoxitin", "Rifampicin", "Doxycycline", "Cefalexin", 
            "Cefazolin", "Cefovecin", "Neomycin", "Ceftiofur", "Tobramycin", 
            "Enrofloxacin", "Polymyxin B", "Marbofloxacin", "Fusidic acid", "Nitrofurantoin"
        ]

        for block in blocks_to_process:
            # Check for negative growth explicitly [cite: 200, 212, 219, 250, 424]
            if re.search(r'No\s+significant\s+growth|No\s+bacteria\s+have\s+been\s+isolated', block, re.IGNORECASE): continue
            
            sample_line = block.strip().split('\n')[0].strip()
            # Handle Swab: Right ear mass format [cite: 15, 96, 302, 361]
            sample_type_val, sample_site_val = (sample_line.split(':', 1) + ["NA"])[:2] if ':' in sample_line else (sample_line, "NA")
            
            if sample_site_val == "NA":
                site_fallback = re.search(r'(Swab|Urine|Tissue|Fluid|Implant):\s*(.+)', block, re.IGNORECASE)
                if site_fallback:
                    sample_type_val, sample_site_val = site_fallback.groups()

            sample_site_val = redact_text(sample_site_val)

            # Isolate Detection anchors [cite: 24, 33, 63, 93, 104, 133, 139, 245, 309, 370, 400, 403]
            isolate_names = []
            for m in re.finditer(r'([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))\s*(?:\n\s*)*SUSCEPTIBILITY', block):
                isolate_names.append(m.group(1))
            for m in re.finditer(r'MALDI-TOF Identification\s*\n+\s*(?:\d+\.\s*)?([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE):
                isolate_names.append(m.group(1))
            for m in re.finditer(r'\b[1-9]\.\s+(?:(?:Heavy|Moderate|Light|Mixed)\s*growth\s*-\s*)?([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE):
                isolate_names.append(m.group(1))
            
            if not isolate_names:
                for m in re.finditer(r'\b(Staphylococcus|Enterococcus|Pseudomonas|Proteus|Escherichia|Klebsiella|Pluralibacter|Bacteroides|Peptostreptococcus)\s+([a-z]+|spp\.|sp\.)\b', block, re.IGNORECASE):
                    isolate_names.append(m.group(0))

            unique_isolates = sorted(list(set(isolate_names)), key=lambda x: block.find(x))
            purity_val = "Mixed" if len(unique_isolates) > 1 else "Pure" if len(unique_isolates) == 1 else "NA"
            
            for i, iso in enumerate(unique_isolates):
                start_idx = block.find(iso)
                end_idx = block.find(unique_isolates[i+1], start_idx + len(iso)) if i + 1 < len(unique_isolates) else len(block)
                isolate_text = block[start_idx:end_idx]
                
                record = {
                    "Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val, 
                    "Age": age_val, "Sex": sex_val, "Neutered": neutered_val, 
                    "Sample Type": sample_type_val.strip(), "Site": sample_site_val.strip(), 
                    "Purity": purity_val, "Isolate": iso
                }
                
                has_sir = False
                for abx in antibiotics_to_check:
                    # Adaptive regex for spelling variants [cite: 26, 61, 65, 106, 135, 247, 311, 373, 402, 405]
                    abx_esc = re.escape(abx).replace(r'Amoxicillin', r'Amox[iy]cillin').replace(r'Cefalexin', r'(?:Cefalexin|Cephalexin)')
                    match = re.search(rf'{abx_esc}(?:[^a-zA-Z]+)*\b(S|I|R|Susceptible|Intermediate|Resistant)\b', isolate_text, re.IGNORECASE)
                    if match:
                        record[abx] = match.group(1).upper()[0]
                        has_sir = True
                    else: record[abx] = "NA"
                
                if has_sir: extracted_data.append(record)
                else: skipped_isolates.append(f"{sample_type_val.strip()} - {iso}")
                
    return extracted_data, skipped_isolates, lab_ref_val

# --- 5. INTERFACE ---
st.title("🔬 AMR National Surveillance Pipeline")
tab1, tab2 = st.tabs(["🚀 Data Processing", "📊 Live Analytics"])

with tab1:
    c1, c2 = st.columns(2)
    master_file = c1.file_uploader("1. Existing Master Dataset (Excel)", type=["xlsx"])
    pdf_files = c2.file_uploader("2. New PDF Reports", type=["pdf"], accept_multiple_files=True)

    if st.button("🚀 Process Reports"):
        if pdf_files:
            new_recs, skipped_summary = [], []
            total = len(pdf_files)
            pb = st.progress(0)
            
            for i, f in enumerate(pdf_files):
                pb.progress((i)/total, text=f"Scanning: {f.name}")
                recs, skip, ref = parse_pdf_report(f)
                new_recs.extend(recs)
                if skip: skipped_summary.append(f"**{f.name}** (Excluded: {', '.join(skip)})")
            
            pb.progress(1.0, text="✅ Processing Complete")

            if new_recs:
                final_df = pd.DataFrame(new_recs)
                st.session_state['processed_data'] = final_df
                
                # --- FIX: PROPER PINNING LOGIC ---
                styled_view = final_df.style.applymap(lambda v: {
                    'S': 'background-color: #C6EFCE; color: #006100', 
                    'I': 'background-color: #FFEB9C; color: #9C5700', 
                    'R': 'background-color: #FFC7CE; color: #9C0006'
                }.get(v, ''))
                
                st.dataframe(
                    styled_view,
                    use_container_width=True,
                    column_config={
                        "Lab Reference": st.column_config.Column(pinned=True)
                    }
                )
                
                buf = io.BytesIO()
                # ASTAG color coding logic
                astag_colors = {
                    "Penicillin": "FFC6EFCE", "Ampicillin": "FFC6EFCE", "Cefalexin": "FFC6EFCE", 
                    "Amoxicillin/Clavulanic acid": "FFFFEB9C", "Gentamicin": "FFFFEB9C",
                    "Enrofloxacin": "FFFFC7CE", "Nitrofurantoin": "FFFFC7CE", "Imipenem": "FFFFC7CE"
                }
                with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                    styled_view.to_excel(writer, index=False, sheet_name="AMR")
                    ws = writer.sheets["AMR"]
                    for col_num, col_name in enumerate(final_df.columns, 1):
                        if col_name in astag_colors:
                            ws.cell(1, col_num).fill = PatternFill(start_color=astag_colors[col_name], end_color=astag_colors[col_name], fill_type="solid")
                
                st.download_button("⬇️ Download Excel", buf.getvalue(), "AMR_Surveillance.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            if skipped_summary:
                st.info("### 📋 Skipped Data Summary\n" + "\n".join([f"- {s}" for s in skipped_summary]))

with tab2:
    if 'processed_data' in st.session_state:
        df = st.session_state['processed_data']
        st.header("📊 Surveillance Insights")
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Isolates", len(df))
        m2.metric("Unique Cases", df["Lab Reference"].nunique())
        df["Isolate"] = df["Isolate"].astype(str).str.strip()
        clean_species = df[(df["Isolate"] != "nan") & (df["Isolate"] != "NA") & (df["Isolate"] != "")]
        m3.metric("Bacterial Species", clean_species["Isolate"].nunique())
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.subheader("Bacterial Species Distribution")
            species_counts = clean_species["Isolate"].value_counts().reset_index()
            species_counts.columns = ["Bacterial Species", "Isolate Count"]
            fig_species = px.bar(species_counts, x="Bacterial Species", y="Isolate Count", text="Isolate Count", template="plotly_white")
            fig_species.update_traces(marker_color='#002b5c')
            st.plotly_chart(fig_species, use_container_width=True)
        with col_c2:
            st.subheader("Susceptibility Profiles")
            sir_check = df.isin(['S', 'I', 'R']).any()
            actual_abx_cols = sir_check[sir_check == True].index.tolist()
            if actual_abx_cols:
                sir_melt = df[actual_abx_cols].melt(var_name="Antibiotic", value_name="Result")
                sir_melt = sir_melt[sir_melt["Result"].isin(["S", "I", "R"])]
                fig_sir = px.histogram(sir_melt, x="Antibiotic", color="Result", barmode="group", color_discrete_map={'S': '#2ca02c', 'I': '#ffcc00', 'R': '#d62728'}, template="plotly_white")
                st.plotly_chart(fig_sir, use_container_width=True)
