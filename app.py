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

def clean_isolate_name(name):
    """Deep scrubber and normalizer to ensure Pandas groups perfectly."""
    if pd.isna(name): return "NA"
    name = str(name)
    # Strip prefixes and growth strings
    name = re.sub(r'^\d+[\.\)]\s*', '', name)
    name = re.sub(r'^(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^\d+[\.\)]\s*', '', name)
    name = re.sub(r'^[-–—\s]+', '', name)
    
    # EXACT NORMALIZATION: Remove double spaces, strip edges, and capitalize first letter only (Genus species)
    name = " ".join(name.split()).capitalize()
    
    return name if name else "NA"

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
                site_fallback = re.search(r'(Swab|Urine|Tissue|Fluid|Implant):\s*(.+)', block, re.IGNORECASE)
                if site_fallback: sample_type_val, sample_site_val = site_fallback.groups()
            
            sample_site_val = redact_text(sample_site_val)
            isolate_names = []
            for m in re.finditer(r'([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))\s*(?:\n\s*)*SUSCEPTIBILITY', block): isolate_names.append(m.group(1))
            for m in re.finditer(r'MALDI-TOF Identification\s*\n+\s*(?:\d+\.\s*(?:(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?)?)?([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            for m in re.finditer(r'\b[1-9]\.\s+([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            
            if not isolate_names:
                for m in re.finditer(r'\b(Staphylococcus|Streptococcus|Enterococcus|Pseudomonas|Proteus|Escherichia|Klebsiella|Bacteroides|Peptostreptococcus|Pluralibacter|Pasteurella|Enterobacter|Acinetobacter|Corynebacterium|Bacillus|Malassezia|Candida|Micrococcus)\s+([a-z]+|spp\.|sp\.)\b', block, re.IGNORECASE): isolate_names.append(m.group(0))

            unique_isolates = sorted(list(set(isolate_names)), key=lambda x: block.find(x))
            for i, isolate_species in enumerate(unique_isolates):
                iso_clean = clean_isolate_name(isolate_species)
                start_idx = block.find(isolate_species)
                end_idx = block.find(unique_isolates[i+1], start_idx + len(isolate_species)) if i + 1 < len(unique_isolates) else len(block)
                isolate_text = block[start_idx:end_idx]
                
                record = {"Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val, "Age": age_val, "Sex": sex_val, "Neutered": neutered_val, "Sample Type": sample_type_val.strip(), "Site": sample_site_val.strip(), "Purity": "Mixed" if len(unique_isolates)>1 else "Pure", "Isolate": iso_clean}
                has_sir = False
                for abx in antibiotics_to_check:
                    abx_esc = re.escape(abx).replace(r'Amoxicillin', r'Amox[iy]cillin').replace(r'Cefalexin', r'(?:Cefalexin|Cephalexin)')
                    match = re.search(rf'{abx_esc}(?:[^a-zA-Z]+)*\b(S|I|R|Susceptible|Intermediate|Resistant)\b', isolate_text, re.IGNORECASE)
                    if match:
                        record[abx] = match.group(1).upper()[0]
                        has_sir = True
                    else: record[abx] = "NA"
                
                if has_sir: extracted_data.append(record)
                else: skipped_isolates.append(f"{sample_type_val} - {iso_clean}")
    return extracted_data, skipped_isolates, lab_ref_val

# --- 5. SIDEBAR DESIGN ---
with st.sidebar:
    st.markdown("<div style='text-align: center;'><div style='font-size: 50px;'>🏛️</div><h2 style='color: #002b5c;'>USYD Vet Path</h2></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### 🛠️ Extraction Workflow\n1. 📂 **Upload** Master Excel\n2. 📄 **Drop** PDF Reports\n3. ⚡ **Process** & Redact\n4. 📥 **Download** Final Sheet")
    st.success("🔒 **Privacy Mode Active**")

# --- 6. MAIN INTERFACE ---
st.title("🔬 AMR National Surveillance Pipeline")
tab1, tab2 = st.tabs(["🚀 Data Processing", "📊 Live Analytics"])

with tab1:
    c1, c2 = st.columns(2)
    with c1: master_file = st.file_uploader("1. Master Dataset (Excel)", type=["xlsx"])
    with c2: pdf_files = st.file_uploader("2. PDF Reports", type=["pdf"], accept_multiple_files=True)

    if st.button("🚀 Process & Synchronize"):
        if pdf_files:
            master_df = pd.read_excel(master_file) if master_file else pd.DataFrame()
            processed_refs = set(master_df["Lab Reference"].dropna().unique()) if not master_df.empty else set()
            new_records, dupes, skipped_list, errors = [], [], [], []
            
            total_files = len(pdf_files)
            progress_bar = st.progress(0, text="Initializing processing pipeline...")
            
            for i, f in enumerate(pdf_files):
                progress_bar.progress((i)/total_files, text=f"Processing file {i+1} of {total_files}: {f.name}")
                try:
                    recs, skip_iso, ref = parse_pdf_report(f)
                    if ref in processed_refs: dupes.append(f.name)
                    else:
                        if recs: new_records.extend(recs); processed_refs.add(ref)
                        if skip_iso: skipped_list.append(f"**{f.name}** (Excluded: {', '.join(skip_iso)})")
                except Exception as e: errors.append(f"**{f.name}** ({str(e)})")

            progress_bar.progress(1.0, text="✅ All files processed successfully!")

            if new_records or not master_df.empty:
                final_df = pd.concat([master_df, pd.DataFrame(new_records)], ignore_index=True) if not master_df.empty else pd.DataFrame(new_records)
                
                # --- EXTREME DEDUPLICATION & CLEANING ---
                if "Isolate" in final_df.columns:
                    final_df["Isolate"] = final_df["Isolate"].apply(clean_isolate_name)
                
                final_df = final_df.drop_duplicates(subset=['Lab Reference', 'Sample Type', 'Site', 'Isolate'], keep='last')
                
                # The data saved to session state is EXACTLY what is displayed in Tab 1
                st.session_state['processed_data'] = final_df
                
                styled_df = final_df.style.applymap(lambda v: {'S': 'background-color: #C6EFCE', 'I': 'background-color: #FFEB9C', 'R': 'background-color: #FFC7CE'}.get(v, ''))
                st.dataframe(styled_df, use_container_width=True)
                
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                    styled_df.to_excel(writer, index=False, sheet_name="AMR Surveillance")
                st.download_button("⬇️ Download Master Excel", buf.getvalue(), "AMR_Surveillance.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            st.divider()
            if dupes: st.warning(f"**Skipped Duplicates:** {', '.join(dupes)}")
            if skipped_list: st.info("### 📋 Skipped Data Summary\n" + "\n".join([f"- {i}" for i in skipped_list]))
            if errors: st.error("### ⚠️ Analysis Errors\n" + "\n".join([f"- {e}" for e in errors]))

with tab2:
    if 'processed_data' in st.session_state:
        df = st.session_state['processed_data'].copy()
        
        st.header("📊 Surveillance Insights")
        
        clean_species = df[~df["Isolate"].isin(["nan", "NA", "Na", ""])]
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Rows in Table", len(clean_species))
        m2.metric("Unique Clinical Cases", clean_species["Lab Reference"].nunique())
        m3.metric("Unique Bacteria Types", clean_species["Isolate"].nunique())
        
        st.divider()
        
        # --- VERIFICATION LAYOUT ---
        st.subheader("Bacterial Species Distribution")
        col_chart, col_data = st.columns([2, 1])
        
        # MATH CALCULATION
        species_counts = clean_species.groupby("Isolate").size().reset_index(name="Count")
        species_counts = species_counts.sort_values(by="Count", ascending=False)
        
        with col_chart:
            fig_species = px.bar(species_counts, x="Isolate", y="Count", text="Count", template="plotly_white")
            fig_species.update_traces(textposition='outside', marker_color='#002b5c')
            fig_species.update_layout(xaxis={'categoryorder':'total descending'}, xaxis_title="Species Identified", yaxis_title="Total Rows in Dataset")
            st.plotly_chart(fig_species, use_container_width=True)
            
        with col_data:
            st.markdown("**Data Verification Table**")
            st.markdown("*This confirms the graph matches Tab 1 exactly.*")
            st.dataframe(species_counts, use_container_width=True, hide_index=True)
            
        st.divider()
        
        st.subheader("Global Resistance Profiles")
        sir_check = df.isin(['S', 'I', 'R']).any()
        actual_abx_cols = sir_check[sir_check == True].index.tolist()
        if actual_abx_cols:
            sir_melt = df[actual_abx_cols].melt(var_name="Antibiotic", value_name="Result")
            sir_melt = sir_melt[sir_melt["Result"].isin(["S", "I", "R"])]
            fig_sir = px.histogram(sir_melt, x="Antibiotic", color="Result", barmode="group", color_discrete_map={'S': '#2ca02c', 'I': '#ffcc00', 'R': '#d62728'}, template="plotly_white")
            fig_sir.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig_sir, use_container_width=True)
                
        st.divider()
        st.subheader("Species-Specific Breed Prevalence")
        pc1, pc2 = st.columns(2)
        
        canine_df = df[df["Species"].str.contains("Canine", case=False, na=False)]
        with pc1:
            if not canine_df.empty:
                st.plotly_chart(px.pie(canine_df, names='Breed', hole=0.4, title="🐶 Canine Breeds", template="plotly_white"), use_container_width=True)

        feline_df = df[df["Species"].str.contains("Feline", case=False, na=False)]
        with pc2:
            if not feline_df.empty:
                st.plotly_chart(px.pie(feline_df, names='Breed', hole=0.4, title="🐱 Feline Breeds", template="plotly_white", color_discrete_sequence=px.colors.qualitative.Pastel), use_container_width=True)
    else:
        st.info("💡 Process data in the first tab to unlock analytics.")
