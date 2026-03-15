import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import plotly.express as px
import plotly.graph_objects as go
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
    if pd.isna(name): return "NA"
    name = str(name)
    name = re.sub(r'^\d+[\.\)]\s*', '', name)
    name = re.sub(r'^(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^\d+[\.\)]\s*', '', name)
    name = re.sub(r'^[-–—\s]+', '', name)
    name = " ".join(name.split()).capitalize()
    return name if name else "NA"

def parse_pdf_report(file_object):
    extracted_data = []
    all_identified_isolates = []
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
            
            sample_site_val = redact_text(sample_site_val).strip()
            if sample_site_val and sample_site_val != "NA":
                sample_site_val = sample_site_val[0].upper() + sample_site_val[1:]

            # 1. FIND ALL IDENTIFIED ISOLATES (INCLUDING CHERRY'S LIST)
            isolate_names = []
            for m in re.finditer(r'([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))\s*(?:\n\s*)*SUSCEPTIBILITY', block): isolate_names.append(m.group(1))
            for m in re.finditer(r'MALDI-TOF Identification\s*\n+\s*(?:\d+\.\s*(?:(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?)?)?([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            for m in re.finditer(r'\b[1-9]\.\s+([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            
            unique_ids = sorted(list(set(isolate_names)), key=lambda x: block.find(x))
            all_identified_isolates.extend([clean_isolate_name(i) for i in unique_ids])

            # 2. CHECK WHICH ONES HAVE TABLES
            for i, isolate_species in enumerate(unique_ids):
                iso_clean = clean_isolate_name(isolate_species)
                start_idx = block.find(isolate_species)
                end_idx = block.find(unique_ids[i+1], start_idx + len(isolate_species)) if i + 1 < len(unique_ids) else len(block)
                isolate_text = block[start_idx:end_idx]
                
                record = {"Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val, "Age": age_val, "Sex": sex_val, "Neutered": neutered_val, "Sample Type": sample_type_val.strip(), "Site": sample_site_val, "Purity": "Mixed" if len(unique_ids)>1 else "Pure", "Isolate": iso_clean}
                has_sir = False
                for abx in antibiotics_to_check:
                    abx_esc = re.escape(abx).replace(r'Amoxicillin', r'Amox[iy]cillin').replace(r'Cefalexin', r'(?:Cefalexin|Cephalexin)')
                    match = re.search(rf'{abx_esc}(?:[^a-zA-Z]+)*\b(S|I|R|Susceptible|Intermediate|Resistant)\b', isolate_text, re.IGNORECASE)
                    if match:
                        record[abx] = match.group(1).upper()[0]
                        has_sir = True
                    else: record[abx] = "NA"
                
                if has_sir: extracted_data.append(record)

    # 3. COMPARE IDENTIFIED VS PROCESSED TO FIND SKIPS
    processed_isolates = [r["Isolate"] for r in extracted_data]
    skipped_list = [iso for iso in list(set(all_identified_isolates)) if iso not in processed_isolates]
    
    return extracted_data, skipped_list, lab_ref_val

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
            progress_bar = st.progress(0, text="Initializing...")
            
            for i, f in enumerate(pdf_files):
                progress_bar.progress((i)/total_files, text=f"Processing: {f.name}")
                try:
                    recs, skip_iso, ref = parse_pdf_report(f)
                    if ref in processed_refs: dupes.append(f.name)
                    else:
                        if recs: new_records.extend(recs); processed_refs.add(ref)
                        if skip_iso:
                            skipped_list.append(f"**{f.name}** (Skipped: {', '.join(skip_iso)})")
                except Exception as e: errors.append(f"**{f.name}** ({str(e)})")

            progress_bar.progress(1.0, text="✅ Done!")

            if new_records or not master_df.empty:
                final_df = pd.concat([master_df, pd.DataFrame(new_records)], ignore_index=True) if not master_df.empty else pd.DataFrame(new_records)
                final_df = final_df.drop_duplicates(subset=['Lab Reference', 'Sample Type', 'Site', 'Isolate'], keep='last')
                st.session_state['processed_data'] = final_df
                
                styled_df = final_df.style.map(lambda v: {'S': 'background-color: #C6EFCE', 'I': 'background-color: #FFEB9C', 'R': 'background-color: #FFC7CE'}.get(v, ''))
                st.dataframe(styled_df, use_container_width=True)
                
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                    styled_df.to_excel(writer, index=False, sheet_name="AMR Surveillance")
                st.download_button("⬇️ Download Master Excel", buf.getvalue(), "AMR_Surveillance.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            if dupes: st.warning(f"**Skipped Duplicates:** {', '.join(dupes)}")
            if skipped_list: 
                st.info("### 📋 Skipped Data Summary")
                for item in skipped_list: st.write(f"- {item}")

with tab2:
    if 'processed_data' in st.session_state:
        df = st.session_state['processed_data'].copy()
        st.header("📊 Surveillance Insights")
        clean_species = df[~df["Isolate"].isin(["nan", "NA", "Na", ""])]
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Number of Isolates", len(clean_species))
        m2.metric("Unique Clinical Cases", clean_species["Lab Reference"].nunique())
        m3.metric("Unique Bacteria Types", clean_species["Isolate"].nunique())
        
        st.divider()
        st.subheader("Bacterial Species Distribution")
        col_chart, col_data = st.columns([2, 1])
        counts = clean_species["Isolate"].value_counts()
        x_cats, y_vals = counts.index.tolist(), [int(v) for v in counts.values]
        
        with col_chart:
            fig_species = go.Figure(data=[go.Bar(x=x_cats, y=y_vals, marker_color='#002b5c', hovertemplate="<b>Species Identified:</b> %{x}<br><b>Number of Isolates:</b> %{y}<extra></extra>")])
            fig_species.update_layout(template="simple_white", xaxis_title="<b>Species Identified</b>", yaxis_title="<b>Total Number of Isolates</b>", font=dict(color="black", size=18))
            fig_species.update_xaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            fig_species.update_yaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max(y_vals)*1.15 if y_vals else 10])
            st.plotly_chart(fig_species, use_container_width=True)
            
        with col_data:
            st.dataframe(pd.DataFrame({"Isolate": x_cats, "Count": y_vals}), use_container_width=True, hide_index=True)
            
        st.divider()
        st.subheader("Global Resistance Profiles")
        sir_check = df.isin(['S', 'I', 'R']).any()
        actual_abx_cols = sir_check[sir_check == True].index.tolist()
        if actual_abx_cols:
            sir_melt = df[actual_abx_cols].melt(var_name="Antibiotic", value_name="Result")
            sir_melt = sir_melt[sir_melt["Result"].isin(["S", "I", "R"])]
            sir_melt['Result'] = sir_melt['Result'].map({'S': 'Sensitive', 'I': 'Intermediate', 'R': 'Resistant'})
            fig_sir = px.histogram(sir_melt, x="Antibiotic", color="Result", barmode="group", color_discrete_map={'Sensitive': '#2ca02c', 'Intermediate': '#ffcc00', 'Resistant': '#d62728'}, category_orders={"Result": ["Resistant", "Intermediate", "Sensitive"]}, template="simple_white")
            fig_sir.update_traces(hovertemplate="<b>Antibiotic:</b> %{x}<br><b>Result:</b> %{data.name}<br><b>Count:</b> %{y}<extra></extra>")
            fig_sir.update_layout(xaxis_tickangle=-45, font=dict(color="black", size=18), legend=dict(font=dict(size=16), title_font_size=18))
            fig_sir.update_xaxes(title_text="<b>Antibiotic</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            max_c = sir_melt.groupby(['Antibiotic', 'Result']).size().max() if not sir_melt.empty else 10
            fig_sir.update_yaxes(title_text="<b>Count</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max_c*1.15])
            st.plotly_chart(fig_sir, use_container_width=True)
                
        st.divider()
        st.subheader("Species-Specific Breed Prevalence")
        pc1, pc2 = st.columns(2)
        unique_demo = df.drop_duplicates(subset=['Lab Reference'])
        breed_colors = ['#1f77b4', '#9467bd', '#17becf', '#e377c2', '#8c564b', '#002b5c', '#6a5acd', '#008b8b']
        
        canine_df = unique_demo[unique_demo["Species"].str.contains("Canine", case=False, na=False)]
        with pc1:
            if not canine_df.empty:
                fig_c = px.pie(canine_df, names='Breed', hole=0.4, title="<b>🐶 Canine Breeds</b>", template="simple_white", color_discrete_sequence=breed_colors)
                fig_c.update_traces(hovertemplate="<b>Breed:</b> %{label}<br><b>Count:</b> %{value}<extra></extra>", textfont_size=18)
                fig_c.update_layout(font=dict(color="black", size=18))
                st.plotly_chart(fig_c, use_container_width=True)

        feline_df = unique_demo[unique_demo["Species"].str.contains("Feline", case=False, na=False)]
        with pc2:
            if not feline_df.empty:
                fig_f = px.pie(feline_df, names='Breed', hole=0.4, title="<b>🐱 Feline Breeds</b>", template="simple_white", color_discrete_sequence=breed_colors)
                fig_f.update_traces(hovertemplate="<b>Breed:</b> %{label}<br><b>Count:</b> %{value}<extra></extra>", textfont_size=18)
                fig_f.update_layout(font=dict(color="black", size=18))
                st.plotly_chart(fig_f, use_container_width=True)
    else:
        st.info("💡 Process data in the first tab to unlock analytics.")
