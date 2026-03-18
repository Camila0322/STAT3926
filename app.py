import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import plotly.express as px
import plotly.graph_objects as go
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta, timezone

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

def standardize_date(date_string):
    if not date_string or date_string == "NA": return "NA"
    try:
        clean_str = re.sub(r'^[a-zA-Z]+,\s*', '', date_string)
        clean_str = re.sub(r'\s+\d{1,2}:\d{2}\s+[APMpm]{2}$', '', clean_str)
        dt = datetime.strptime(clean_str.strip(), "%d %B %Y")
        return dt.strftime("%d-%m-%Y")
    except:
        try:
            dt = pd.to_datetime(date_string, errors='coerce')
            if pd.notna(dt): return dt.strftime("%d-%m-%Y")
        except:
            pass
    return date_string

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
        
        report_date_raw = re.search(r'Report date:\s*(.*?)(?=\s*Page:|\n)', raw_text, re.IGNORECASE)
        report_date_val = standardize_date(report_date_raw.group(1).strip() if report_date_raw else "NA")

        arrival_date_raw = re.search(r'Arrival date:\s*(.*?)(?=\s*\]|\s*Page:|\n)', raw_text, re.IGNORECASE)
        arrival_date_val = standardize_date(arrival_date_raw.group(1).strip() if arrival_date_raw else "NA")
        
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

        antibiotics_to_check = [
            "Amikacin", "Amoxicillin/Clavulanic acid", "Ampicillin", "Cefalexin", 
            "Cefazolin", "Cefovecin", "Cefoxitin", "Ceftiofur", "Chloramphenicol", 
            "Clindamycin", "Doxycycline", "Enrofloxacin", "Erythromycin", "Fusidic acid", 
            "Gentamicin", "Imipenem", "Marbofloxacin", "Neomycin", "Nitrofurantoin", 
            "Oxacillin", "Penicillin", "Polymyxin B", "Rifampicin", "Ticarcillin/clavulanic acid", 
            "Tobramycin", "Trimethoprim/sulpha", "Vancomycin"
        ]
        for block in blocks_to_process:
            sample_line = block.strip().split('\n')[0].strip()
            sample_type_val, sample_site_val = (sample_line.split(':', 1) + ["NA"])[:2] if ':' in sample_line else (sample_line, "NA")
            if sample_site_val == "NA":
                site_fallback = re.search(r'(Swab|Urine|Tissue|Fluid|Implant):\s*(.+)', block, re.IGNORECASE)
                if site_fallback: sample_type_val, sample_site_val = site_fallback.groups()
            
            sample_site_val = redact_text(sample_site_val).strip()
            sample_site_detailed_val = "NA"
            
            if sample_site_val and sample_site_val != "NA":
                parens_match = re.search(r'^(.*?)\s*\((.*?)\)', sample_site_val)
                if parens_match:
                    sample_site_val = parens_match.group(1).strip()
                    detailed_part = parens_match.group(2).strip()
                    if detailed_part:
                        sample_site_detailed_val = detailed_part[0].upper() + detailed_part[1:]
                else:
                    split_site = re.split(r'[,/:\-;|]', sample_site_val, maxsplit=1)
                    if len(split_site) > 1:
                        sample_site_val = split_site[0].strip()
                        detailed_part = split_site[1].strip()
                        detailed_part = re.sub(r'[\)\]\}]+$', '', detailed_part).strip()
                        if detailed_part:
                            sample_site_detailed_val = detailed_part[0].upper() + detailed_part[1:]
                
                if sample_site_val:
                    sample_site_val = sample_site_val[0].upper() + sample_site_val[1:]
                else:
                    sample_site_val = "NA"

            isolate_names = []
            for m in re.finditer(r'([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))\s*(?:\n\s*)*SUSCEPTIBILITY', block): isolate_names.append(m.group(1))
            for m in re.finditer(r'MALDI-TOF Identification\s*\n+\s*(?:\d+\.\s*(?:(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?)?)?([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            for m in re.finditer(r'\b[1-9]\.\s+([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE): isolate_names.append(m.group(1))
            
            unique_ids = sorted(list(set(isolate_names)), key=lambda x: block.find(x))
            all_identified_isolates.extend([clean_isolate_name(i) for i in unique_ids])

            for i, isolate_species in enumerate(unique_ids):
                iso_clean = clean_isolate_name(isolate_species)
                start_idx = block.find(isolate_species)
                end_idx = block.find(unique_ids[i+1], start_idx + len(isolate_species)) if i + 1 < len(unique_ids) else len(block)
                isolate_text = block[start_idx:end_idx]
                
                record = {
                    "Arrival Date": arrival_date_val, 
                    "Report Date": report_date_val,
                    "Lab Reference": lab_ref_val, 
                    "Species": species_val, 
                    "Breed": breed_val, 
                    "Age": age_val, 
                    "Sex": sex_val, 
                    "Neutered": neutered_val, 
                    "Sample Type": sample_type_val.strip(), 
                    "Site": sample_site_val, 
                    "Sample Site (Detailed)": sample_site_detailed_val, 
                    "Purity": "Mixed" if len(unique_ids)>1 else "Pure", 
                    "Isolate": iso_clean
                }
                
                has_sir = False
                for abx in antibiotics_to_check:
                    abx_esc = re.escape(abx).replace(r'Amoxicillin', r'Amox[iy]cillin').replace(r'Cefalexin', r'(?:Cefalexin|Cephalexin)')
                    match = re.search(rf'{abx_esc}(?:[^a-zA-Z]+)*\b(S|I|R|Susceptible|Intermediate|Resistant)\b', isolate_text, re.IGNORECASE)
                    if match:
                        record[abx] = match.group(1).upper()[0]
                        has_sir = True
                    else: record[abx] = "NA"
                
                if has_sir: extracted_data.append(record)

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
            new_records, dupes, skipped_msgs = [], [], []
            
            total_files = len(pdf_files)
            pb = st.progress(0, text=f"Initializing (0/{total_files})...")
            for i, f in enumerate(pdf_files):
                pb.progress((i)/total_files, text=f"Processing ({i+1}/{total_files}): {f.name}")
                try:
                    recs, skips, ref = parse_pdf_report(f)
                    if ref in processed_refs: dupes.append(f.name)
                    else:
                        if recs: new_records.extend(recs); processed_refs.add(ref)
                        if skips: skipped_msgs.append(f"**{f.name}** (Skipped: {', '.join(skips)})")
                except Exception as e: st.error(f"Error {f.name}: {str(e)}")
            pb.progress(1.0, text="✅ Done!")

            if new_records or not master_df.empty:
                final_df = pd.concat([master_df, pd.DataFrame(new_records)], ignore_index=True) if not master_df.empty else pd.DataFrame(new_records)
                final_df = final_df.drop_duplicates(subset=['Lab Reference', 'Sample Type', 'Site', 'Sample Site (Detailed)', 'Isolate'], keep='last')
                st.session_state['processed_data'] = final_df
                st.session_state['dupes_list'] = dupes
                st.session_state['skipped_msgs'] = skipped_msgs

    if 'processed_data' in st.session_state:
        final_df = st.session_state['processed_data']
        
        styled_df = final_df.style.map(lambda v: {'S': 'background-color: #C6EFCE', 'I': 'background-color: #FFEB9C', 'R': 'background-color: #FFC7CE'}.get(v, ''))
        st.dataframe(styled_df, use_container_width=True)
        
        buf = io.BytesIO()
        astag_colors = {
            "Penicillin": "FFC6EFCE", "Ampicillin": "FFC6EFCE", "Cefalexin": "FFC6EFCE", "Cefazolin": "FFC6EFCE", "Doxycycline": "FFC6EFCE", "Trimethoprim/sulpha": "FFC6EFCE", "Erythromycin": "FFC6EFCE", "Clindamycin": "FFC6EFCE", "Fusidic acid": "FFC6EFCE", "Chloramphenicol": "FFC6EFCE",
            "Amoxicillin/Clavulanic acid": "FFFFEB9C", "Ticarcillin/clavulanic acid": "FFFFEB9C", "Gentamicin": "FFFFEB9C", "Neomycin": "FFFFEB9C", "Tobramycin": "FFFFEB9C",
            "Enrofloxacin": "FFFFC7CE", "Marbofloxacin": "FFFFC7CE", "Cefovecin": "FFFFC7CE", "Ceftiofur": "FFFFC7CE", "Amikacin": "FFFFC7CE", "Imipenem": "FFFFC7CE", "Vancomycin": "FFFFC7CE", "Polymyxin B": "FFFFC7CE", "Rifampicin": "FFFFC7CE", "Oxacillin": "FFFFC7CE", "Nitrofurantoin": "FFFFC7CE"
        } 
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            styled_df.to_excel(writer, index=False, sheet_name="AMR Surveillance")
            ws = writer.sheets["AMR Surveillance"]
            for col_num, col_name in enumerate(final_df.columns, 1):
                if col_name in astag_colors:
                    ws.cell(1, col_num).fill = PatternFill(start_color=astag_colors[col_name], end_color=astag_colors[col_name], fill_type="solid")
        
        aus_time = datetime.now(timezone.utc) + timedelta(hours=10)
        current_date = aus_time.strftime("%d-%m-%Y")
        download_filename = f"AMR_Surveillance_{current_date}.xlsx"
        
        st.download_button("⬇️ Download Master Excel", buf.getvalue(), download_filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        if st.session_state.get('dupes_list'): 
            st.warning(f"**Skipped Duplicates:** {', '.join(st.session_state['dupes_list'])}")
        if st.session_state.get('skipped_msgs'): 
            st.info("### 📋 Skipped Data Summary")
            for item in st.session_state['skipped_msgs']: st.write(f"- {item}")

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
        x_cats = counts.index.tolist()
        y_vals = [int(v) for v in counts.values]
        max_y = max(y_vals) if y_vals else 10
        
        with col_chart:
            fig_species = go.Figure(data=[
                go.Bar(
                    x=x_cats,
                    y=y_vals,
                    marker_color='#002b5c', 
                    hovertemplate="<b>Species Identified:</b> %{x}<br><b>Number of Isolates:</b> %{y}<extra></extra>"
                )
            ])
            fig_species.update_layout(
                height=600,
                template="simple_white",
                xaxis_title="<b>Species Identified</b>",
                yaxis_title="<b>Total Number of Isolates</b>",
                font=dict(color="black", size=18),
                margin=dict(b=220, t=50, l=0, r=0)
            )
            fig_species.update_xaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            fig_species.update_yaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max_y * 1.1], rangemode="tozero")
            
            fig_species.add_annotation(
                text="Figure 1: Distribution of bacterial species identified across all processed clinical reports.",
                xref="paper", yref="paper", 
                x=0, y=-0.55, 
                showarrow=False, font=dict(size=14, color="gray"), align="left", xanchor="left", yanchor="top"
            )
            
            st.plotly_chart(fig_species, use_container_width=True)
            
        with col_data:
            st.markdown("**Data Verification Table**")
            st.dataframe(pd.DataFrame({"Bacterial Species": x_cats, "Total Number of Isolates": y_vals}), use_container_width=True, hide_index=True)
            
        st.divider()
        
        sir_cols = [c for c in df.columns if df[c].isin(['S', 'I', 'R']).any()]
        if sir_cols:
            st.subheader("Global Resistance Profiles")
            melted = df[sir_cols].melt(var_name="ABx", value_name="Res")
            melted = melted[melted["Res"].isin(["S", "I", "R"])]
            melted['Res'] = melted['Res'].map({'S': 'Susceptible', 'I': 'Intermediate', 'R': 'Resistant'})
            
            # 1. DODGED HISTOGRAM (COUNTS)
            fig_sir = px.histogram(
                melted, x="ABx", color="Res", barmode="group", 
                color_discrete_map={'Susceptible': '#2ca02c', 'Intermediate': '#ffcc00', 'Resistant': '#d62728'}, 
                category_orders={"Res": ["Resistant", "Intermediate", "Susceptible"]}, 
                template="simple_white"
            )
            
            fig_sir.update_traces(hovertemplate="<b>Antibiotic:</b> %{x}<br><b>Result:</b> %{data.name}<br><b>Count:</b> %{y}<extra></extra>")
            fig_sir.update_layout(
                height=600,
                xaxis_tickangle=-45, 
                font=dict(color="black", size=18), 
                legend=dict(
                    font=dict(size=16), 
                    title=dict(text="<b>Susceptibility</b>", font=dict(size=22))
                ),
                margin=dict(b=260, t=50, l=0, r=0)
            )
            fig_sir.update_xaxes(title_text="<b>Antibiotic</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            
            max_c = melted.groupby(['ABx', 'Res']).size().max() if not melted.empty else 10
            fig_sir.update_yaxes(title_text="<b>Count</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max_c * 1.1], rangemode="tozero")
            
            fig_sir.add_annotation(
                text="Figure 2: Overall antimicrobial susceptibility profiles (Green: Susceptible, Yellow: Intermediate, Red: Resistant).",
                xref="paper", yref="paper", 
                x=0, y=-0.75, 
                showarrow=False, font=dict(size=14, color="gray"), align="left", xanchor="left", yanchor="top"
            )
            
            st.plotly_chart(fig_sir, use_container_width=True)

            # 2. STACKED HISTOGRAM (PERCENTAGES)
            st.divider()
            st.header("Suggestions after consultation")
            st.markdown("Use this normalized percentage view to instantly evaluate the statistical probability of resistance for any given antibiotic, factoring in testing frequency differences.")
            
            fig_sir_pct = px.histogram(
                melted, x="ABx", color="Res", 
                barmode="relative", barnorm="percent", 
                color_discrete_map={'Susceptible': '#2ca02c', 'Intermediate': '#ffcc00', 'Resistant': '#d62728'}, 
                category_orders={"Res": ["Resistant", "Intermediate", "Susceptible"]}, 
                template="simple_white"
            )
            
            fig_sir_pct.update_traces(hovertemplate="<b>Antibiotic:</b> %{x}<br><b>Result:</b> %{data.name}<br><b>Percentage:</b> %{y:.1f}%<extra></extra>")
            fig_sir_pct.update_layout(
                height=600,
                xaxis_tickangle=-45, 
                font=dict(color="black", size=18), 
                legend=dict(
                    font=dict(size=16), 
                    title=dict(text="<b>Susceptibility</b>", font=dict(size=22))
                ),
                margin=dict(b=260, t=50, l=0, r=0)
            )
            fig_sir_pct.update_xaxes(title_text="<b>Antibiotic</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            fig_sir_pct.update_yaxes(title_text="<b>Percentage (%)</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, 100], rangemode="tozero")
            
            fig_sir_pct.add_annotation(
                text="Figure 3: Overall antimicrobial susceptibility profiles displayed as percentages (Green: Susceptible, Yellow: Intermediate, Red: Resistant).",
                xref="paper", yref="paper", 
                x=0, y=-0.75, 
                showarrow=False, font=dict(size=14, color="gray"), align="left", xanchor="left", yanchor="top"
            )
            
            st.plotly_chart(fig_sir_pct, use_container_width=True)
            
        # --- SAMPLE SITE DISTRIBUTION PLOT ---
        st.divider()
        st.subheader("Sample Site Distribution")
        
        clean_sites = df[~df["Site"].isin(["nan", "NA", "Na", ""])]
        site_counts = clean_sites["Site"].value_counts()
        x_site = site_counts.index.tolist()
        y_site = [int(v) for v in site_counts.values]
        max_y_site = max(y_site) if y_site else 10
        
        fig_site = go.Figure(data=[
            go.Bar(
                x=x_site,
                y=y_site,
                marker_color='#e64646', # --- UPDATED TO BUTTON RED ---
                hovertemplate="<b>Sample Site:</b> %{x}<br><b>Count:</b> %{y}<extra></extra>"
            )
        ])
        fig_site.update_layout(
            height=600,
            template="simple_white",
            xaxis_title="<b>Sample Site</b>",
            yaxis_title="<b>Count</b>",
            font=dict(color="black", size=18),
            margin=dict(b=180, t=50, l=0, r=0)
        )
        fig_site.update_xaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
        fig_site.update_yaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max_y_site * 1.1], rangemode="tozero")
        
        fig_site.add_annotation(
            text="Figure 4: Distribution of sample collection sites.",
            xref="paper", yref="paper", 
            x=0, y=-0.25, 
            showarrow=False, font=dict(size=14, color="gray"), align="left", xanchor="left", yanchor="top"
        )
        
        st.plotly_chart(fig_site, use_container_width=True)
                
        st.divider()
        st.subheader("Species-Specific Breed Prevalence")
        pc1, pc2 = st.columns(2)
        unique_demo = df.drop_duplicates(subset=['Lab Reference'])
        breed_pal = ['#1f77b4', '#9467bd', '#17becf', '#e377c2', '#8c564b', '#e64646', '#6a5acd', '#008b8b'] # --- ADDED RED TO PIE PALETTE ---
        
        canine_df = unique_demo[unique_demo["Species"].str.contains("Canine", case=False, na=False)]
        with pc1:
            if not canine_df.empty:
                fig_c = px.pie(canine_df, names='Breed', hole=0.4, title="<b>🐶 Canine Breeds</b>", template="simple_white", color_discrete_sequence=breed_pal)
                fig_c.update_traces(hovertemplate="<b>Breed:</b> %{label}<br><b>Count:</b> %{value}<extra></extra>", textfont_size=18)
                fig_c.update_layout(
                    font=dict(color="black", size=18),
                    margin=dict(b=130, t=50, l=0, r=0)
                )
                
                fig_c.add_annotation(
                    text="Figure 5(a): Demographic distribution of canine breeds per unique clinical case.",
                    xref="paper", yref="paper", 
                    x=0.75, y=-0.2, 
                    showarrow=False, font=dict(size=14, color="gray"), align="center", xanchor="center", yanchor="top"
                )
                
                st.plotly_chart(fig_c, use_container_width=True)
            else: st.info("No Canine data identified.")

        feline_df = unique_demo[unique_demo["Species"].str.contains("Feline", case=False, na=False)]
        with pc2:
            if not feline_df.empty:
                fig_f = px.pie(feline_df, names='Breed', hole=0.4, title="<b>🐱 Feline Breeds</b>", template="simple_white", color_discrete_sequence=breed_pal)
                fig_f.update_traces(hovertemplate="<b>Breed:</b> %{label}<br><b>Count:</b> %{value}<extra></extra>", textfont_size=18)
                fig_f.update_layout(
                    font=dict(color="black", size=18),
                    margin=dict(b=130, t=50, l=0, r=0)
                )
                
                fig_f.add_annotation(
                    text="Figure 5(b): Demographic distribution of feline breeds<br>per unique clinical case.",
                    xref="paper", yref="paper", 
                    x=0.5, y=-0.4, 
                    showarrow=False, font=dict(size=14, color="gray"), align="center", xanchor="center", yanchor="top"
                )
                
                st.plotly_chart(fig_f, use_container_width=True)
            else: st.info("No Feline data identified.")
            
    else:
        st.info("💡 Process data in tab 1 to unlock analytics.")
