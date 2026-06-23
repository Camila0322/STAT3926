import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import openpyxl
import plotly.express as px
import plotly.graph_objects as go
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta, timezone

# ============================================================================
# 1. PAGE CONFIG
# ============================================================================
st.set_page_config(
    page_title="AMR National Surveillance | USYD",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# 2. PROFESSIONAL THEME
# ============================================================================
NAVY = "#002b5c"
NAVY_HOVER = "#013a7a"
ACCENT = "#b3122b"
INK = "#1f2933"
MUTED = "#5b6770"
LINE = "#e3e8ee"
CANVAS = "#f4f6f8"

st.markdown(f"""
    <style>
    html, body, [class*="css"] {{
        font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        color: {INK};
    }}
    .stApp {{ background-color: {CANVAS}; }}
    .block-container {{ padding-top: 2.2rem; max-width: 1300px; }}

    /* Header banner */
    .amr-header {{
        border-bottom: 3px solid {NAVY};
        padding-bottom: 0.9rem; margin-bottom: 1.6rem;
    }}
    .amr-header h1 {{
        color: {NAVY}; font-size: 1.85rem; font-weight: 650;
        margin: 0; letter-spacing: -0.01em;
    }}
    .amr-header p {{ color: {MUTED}; font-size: 0.95rem; margin: 0.25rem 0 0 0; }}

    h2, h3 {{ color: {NAVY}; font-weight: 600; }}

    /* Buttons */
    .stButton>button {{
        width: 100%; border-radius: 6px; height: 3em; border: none;
        background-color: {NAVY}; color: #ffffff; font-weight: 600; letter-spacing: 0.01em;
        transition: background-color 0.15s ease;
    }}
    .stButton>button:hover {{ background-color: {NAVY_HOVER}; color: #ffffff; }}
    .stDownloadButton>button {{
        border-radius: 6px; background-color: #ffffff; color: {NAVY};
        border: 1.5px solid {NAVY}; font-weight: 600;
    }}
    .stDownloadButton>button:hover {{ background-color: {NAVY}; color: #ffffff; }}

    /* Sidebar */
    [data-testid="stSidebar"] {{ background-color: #ffffff; border-right: 1px solid {LINE}; }}
    [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ color: {NAVY}; }}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{ gap: 0.4rem; border-bottom: 1px solid {LINE}; }}
    .stTabs [data-baseweb="tab"] {{
        font-weight: 600; color: {MUTED}; padding: 0.5rem 1rem;
    }}
    .stTabs [aria-selected="true"] {{ color: {NAVY}; }}

    /* Metric cards */
    [data-testid="stMetric"] {{
        background: #ffffff; border: 1px solid {LINE}; border-radius: 8px;
        padding: 1rem 1.2rem;
    }}
    [data-testid="stMetricValue"] {{ color: {NAVY}; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{ color: {MUTED}; }}

    /* Uploaders */
    [data-testid="stFileUploader"] {{
        background: #ffffff; border: 1px solid {LINE}; border-radius: 8px; padding: 0.6rem;
    }}
    .legend-chip {{
        display:inline-block; width:12px; height:12px; border-radius:3px;
        margin-right:6px; vertical-align:middle;
    }}
    </style>
""", unsafe_allow_html=True)

# ============================================================================
# 3. CONFIGURATION
# ============================================================================
# Antibiotic columns sit in pairs in the AST sheet, starting at column 13 (0-based):
# (zone-diameter measurement, S/I/R interpretation). We read the SECOND of each pair.
# Keyed by POSITION (not header text) because older tabs label cefazolin "CZ 30"
# and 2025/2026 use "CZN 30" — same drug, same column.
AST_FIRST_ABX_COL = 13
AST_CP_COL = 1
AST_ISOLATE_COL = 10
AST_SKIP_SHEETS = {"MALDI ID NAME LIST"}

CANON_ABBREVS = [
    "AM10", "AMC30", "CZN 30", "CL30", "CAZ30", "CVN30", "DO30", "SXT", "ENR5",
    "MAR", "GM 10", "C30", "P10", "F/M300", "N30", "OX1", "FOX30", "CC2", "E15",
    "TIC75", "TIM85", "S5", "CN 120", "RD5", "FA10", "AN30", "IPM10", "VA30",
]

# Final metadata columns (all from the PDF), in order.
META_COLUMNS = [
    "Arrival Date", "Report Date", "Lab Reference", "Species", "Breed", "Age",
    "Sex", "Neutered", "Sample Type", "Site", "Sample Site (Detailed)", "Purity", "Isolate",
]

# Antibiotic-class importance colours, keyed by AST abbreviation (Green/Yellow/Red).
# CAZ30, FOX30, TIC75 and S5 left uncoloured pending confirmation from Bianca.
GREEN = "FFC6EFCE"; YELLOW = "FFFFEB9C"; RED = "FFFFC7CE"
ABX_HEADER_COLORS = {
    "AM10": GREEN, "CZN 30": GREEN, "CL30": GREEN, "DO30": GREEN, "SXT": GREEN,
    "C30": GREEN, "P10": GREEN, "CC2": GREEN, "E15": GREEN, "FA10": GREEN,
    "AMC30": YELLOW, "GM 10": YELLOW, "N30": YELLOW, "TIM85": YELLOW, "CN 120": YELLOW,
    "ENR5": RED, "MAR": RED, "CVN30": RED, "OX1": RED, "F/M300": RED,
    "RD5": RED, "AN30": RED, "IPM10": RED, "VA30": RED,
}
SIR_FILL = {"S": "background-color: #C6EFCE", "I": "background-color: #FFEB9C", "R": "background-color: #FFC7CE"}

# ============================================================================
# 4. MODEL LOADING
# ============================================================================
@st.cache_resource
def load_nlp():
    return spacy.load("en_core_web_sm")
nlp = load_nlp()

# ============================================================================
# 5. HELPERS
# ============================================================================
def normalize_cp(value):
    if value is None:
        return None
    m = re.search(r'(\d{2}-\d{4,5})', str(value))
    return m.group(1) if m else None


def redact_text(text):
    if not isinstance(text, str):
        return "NA"
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "GPE", "LOC"]:
            text = text.replace(ent.text, "[REDACTED]")
    return text


def standardize_age(age_string):
    if not age_string:
        return "NA"
    years, months = 0, 0
    ym = re.search(r'(\d+)\s*(y|year|years)', age_string, re.IGNORECASE)
    if ym:
        years = int(ym.group(1))
    mm = re.search(r'(\d+)\s*(m|month|months)', age_string, re.IGNORECASE)
    if mm:
        months = int(mm.group(1))
    return f"{years}Y {months}M"


def standardize_date(date_string):
    if not date_string or date_string == "NA":
        return "NA"
    try:
        clean = re.sub(r'^[a-zA-Z]+,\s*', '', date_string)
        clean = re.sub(r'\s+\d{1,2}:\d{2}\s+[APMpm]{2}$', '', clean)
        return datetime.strptime(clean.strip(), "%d %B %Y").strftime("%Y%m%d")
    except Exception:
        try:
            dt = pd.to_datetime(date_string, errors='coerce')
            if pd.notna(dt):
                return dt.strftime("%Y%m%d")
        except Exception:
            pass
    return date_string


def clean_boilerplate(text):
    junk = ["SYDNEY SCHOOL", "FACULTY OF VET", "PATHOLOGY DIAGNOSTIC", "UNIVERSITY OF SYDNEY",
            "CRICOS", "ABN 15", "FINAL REPORT"]
    out = []
    for line in text.split('\n'):
        l = line.strip()
        if not l:
            continue
        if any(j.lower() in l.lower() for j in junk):
            continue
        if re.search(r'Page:\s*\d+|T[: \s]*02\s*9351|date:|Ref:', l, re.IGNORECASE):
            continue
        out.append(l)
    return "\n".join(out)


def clean_isolate_name(name):
    if pd.isna(name):
        return "NA"
    name = str(name)
    name = re.sub(r'^\d+[\.\)]\s*', '', name)
    name = re.sub(r'^(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^\d+[\.\)]\s*', '', name)
    name = re.sub(r'^[-–—\s]+', '', name)
    name = " ".join(name.split()).capitalize()
    return name if name else "NA"


# ============================================================================
# 6. PDF METADATA EXTRACTION  (everything except antibiotic results)
# ============================================================================
def parse_pdf_metadata(file_object):
    """Return a list of per-isolate metadata records (the 13 META_COLUMNS, plus
       internal _cp_key / _isolate_key for matching to the AST sheet)."""
    records = []
    with pdfplumber.open(file_object) as pdf:
        raw_text = "".join((page.extract_text() or "") + "\n" for page in pdf.pages)

    cp_key = normalize_cp(re.search(r'Our Ref:\s*(?:CP\s*)?(\d{2}-\d{4,5})', raw_text, re.IGNORECASE))
    lab_ref_val = f"CP {cp_key}" if cp_key else "NA"

    rd = re.search(r'Report date:\s*(.*?)(?=\s*Page:|\n)', raw_text, re.IGNORECASE)
    report_date_val = standardize_date(rd.group(1).strip() if rd else "NA")

    ad = re.search(r'Arrival date:\s*(.*?)(?=\s*\]|\s*Page:|\n)', raw_text, re.IGNORECASE)
    arrival_date_val = standardize_date(ad.group(1).strip() if ad else "NA")

    sb = re.search(r'(Canine|Feline)[\s\-]+([a-zA-Z\s\-]+?)(?=\s*(?:\n|Male|Female|\d+\s*Years?|Our Ref|$))', raw_text, re.IGNORECASE)
    species_val = sb.group(1).strip().capitalize() if sb else "NA"
    breed_val = sb.group(2).strip(" -") if sb else "NA"

    age = re.search(r'(\d+\s*(?:Years?|Months?|Weeks?))', raw_text, re.IGNORECASE)
    age_val = standardize_age(age.group(1)) if age else "NA"

    g = re.search(r'(Male Neutered|Female Spayed|Male|Female)', raw_text, re.IGNORECASE)
    if g and "Neutered" in g.group(1):
        sex_val, neutered_val = "Male", "Yes"
    elif g and "Spayed" in g.group(1):
        sex_val, neutered_val = "Female", "Yes"
    elif g:
        sex_val, neutered_val = g.group(1).capitalize(), "No"
    else:
        sex_val, neutered_val = "NA", "NA"

    clean_text = clean_boilerplate(raw_text)
    sample_blocks = re.split(r'^SAMPLE(?:\s+\d+)?\s*$', clean_text, flags=re.IGNORECASE | re.MULTILINE)
    blocks = sample_blocks[1:] if len(sample_blocks) > 1 else [clean_text]

    for block in blocks:
        sample_line = block.strip().split('\n')[0].strip()
        sample_type_val, sample_site_val = (sample_line.split(':', 1) + ["NA"])[:2] if ':' in sample_line else (sample_line, "NA")
        if sample_site_val == "NA":
            sf = re.search(r'(Swab|Urine|Tissue|Fluid|Implant):\s*(.+)', block, re.IGNORECASE)
            if sf:
                sample_type_val, sample_site_val = sf.groups()

        sample_site_val = redact_text(sample_site_val).strip()
        sample_site_detailed_val = "NA"
        if sample_site_val and sample_site_val != "NA":
            pm = re.search(r'^(.*?)\s*\((.*?)\)', sample_site_val)
            if pm:
                sample_site_val = pm.group(1).strip()
                dp = pm.group(2).strip()
                if dp:
                    sample_site_detailed_val = dp[0].upper() + dp[1:]
            else:
                ss = re.split(r'[,/:\-;|]', sample_site_val, maxsplit=1)
                if len(ss) > 1:
                    sample_site_val = ss[0].strip()
                    dp = re.sub(r'[\)\]\}]+$', '', ss[1].strip()).strip()
                    if dp:
                        sample_site_detailed_val = dp[0].upper() + dp[1:]
            sample_site_val = (sample_site_val[0].upper() + sample_site_val[1:]) if sample_site_val else "NA"

        names = []
        for m in re.finditer(r'([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))\s*(?:\n\s*)*SUSCEPTIBILITY', block):
            names.append(m.group(1))
        for m in re.finditer(r'MALDI-TOF Identification\s*\n+\s*(?:\d+\.\s*(?:(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?)?)?([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE):
            names.append(m.group(1))
        for m in re.finditer(r'\b[1-9]\.\s+([A-Z][a-z]+\s+(?:sp\.|spp\.|[a-z]+))', block, re.IGNORECASE):
            names.append(m.group(1))

        unique_ids = sorted(set(names), key=lambda x: block.find(x))
        purity = "Mixed" if len([u for u in unique_ids if clean_isolate_name(u) != "NA"]) > 1 else "Pure"

        for iso in unique_ids:
            iso_clean = clean_isolate_name(iso)
            if iso_clean == "NA":
                continue
            records.append({
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
                "Purity": purity,
                "Isolate": iso_clean,
                "_cp_key": cp_key,
                "_isolate_key": iso_clean.strip().lower(),
            })

    return records


# ============================================================================
# 7. AST ANTIBIOTIC LOOKUP
# ============================================================================
def build_ast_lookup(file_object):
    """Return {(cp_key, isolate_lower): {abbrev: S/I/R}} from every year tab."""
    wb = openpyxl.load_workbook(file_object, read_only=True, data_only=True)
    sir_cols = {abx: AST_FIRST_ABX_COL + 1 + 2 * i for i, abx in enumerate(CANON_ABBREVS)}
    lookup = {}
    for sheet_name in wb.sheetnames:
        if sheet_name in AST_SKIP_SHEETS:
            continue
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = rows[0]
        if not header or len(header) <= AST_CP_COL or str(header[AST_CP_COL]).strip().upper() != "CP NUMBER":
            continue
        for row in rows[1:]:
            if len(row) <= AST_CP_COL or not row[AST_CP_COL]:
                continue
            cp_key = normalize_cp(row[AST_CP_COL])
            iso = row[AST_ISOLATE_COL] if AST_ISOLATE_COL < len(row) else None
            if not cp_key or not iso:
                continue
            key = (cp_key, str(iso).strip().lower())
            result = {abx: (row[si] if si < len(row) and row[si] in ("S", "I", "R") else "NA")
                      for abx, si in sir_cols.items()}
            lookup.setdefault(key, result)  # first occurrence wins
    return lookup


# ============================================================================
# 8. MERGE
# ============================================================================
def build_dataframe(pdf_records, ast_lookup):
    """Attach AST antibiotic results to each PDF isolate row. Keep only isolates
       that have a matching AST row; report the rest as skipped."""
    rows, skipped = [], []
    for rec in pdf_records:
        key = (rec["_cp_key"], rec["_isolate_key"])
        if key not in ast_lookup:
            skipped.append(f'{rec["Lab Reference"]} — {rec["Isolate"]}')
            continue
        merged = {col: rec[col] for col in META_COLUMNS}
        merged.update(ast_lookup[key])
        rows.append(merged)
    df = pd.DataFrame(rows, columns=META_COLUMNS + CANON_ABBREVS)
    return df, skipped


def build_excel(df):
    styled = df.style.map(lambda v: SIR_FILL.get(v, ''))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        styled.to_excel(writer, index=False, sheet_name="AMR Surveillance")
        ws = writer.sheets["AMR Surveillance"]
        for col_num, col_name in enumerate(df.columns, 1):
            if col_name in ABX_HEADER_COLORS:
                fill = ABX_HEADER_COLORS[col_name]
                ws.cell(1, col_num).fill = PatternFill(start_color=fill, end_color=fill, fill_type="solid")
    return buf.getvalue()


# ============================================================================
# 9. SIDEBAR
# ============================================================================
with st.sidebar:
    st.markdown(f"<h3 style='margin-bottom:0;color:{NAVY};'>USYD · Veterinary Pathology</h3>"
                f"<p style='color:{MUTED};font-size:0.85rem;margin-top:0.2rem;'>AMR Surveillance Pipeline</p>",
                unsafe_allow_html=True)
    st.divider()
    st.markdown("**Workflow**")
    st.markdown(
        "1. Upload Bianca's AST LOGGING sheet\n"
        "2. Add the matching PDF report(s)\n"
        "3. Process — matched on CP number & isolate\n"
        "4. Download the master sheet")
    st.divider()
    st.markdown("**Result key**")
    st.markdown(
        f"<span class='legend-chip' style='background:#C6EFCE;'></span>Susceptible (S)<br>"
        f"<span class='legend-chip' style='background:#FFEB9C;'></span>Intermediate (I)<br>"
        f"<span class='legend-chip' style='background:#FFC7CE;'></span>Resistant (R)",
        unsafe_allow_html=True)
    st.divider()
    st.caption("Metadata is read from the PDF report. Antibiotic results are read from the AST sheet.")

# ============================================================================
# 10. MAIN
# ============================================================================
st.markdown(
    "<div class='amr-header'><h1>AMR National Surveillance Pipeline</h1>"
    "<p>Antimicrobial susceptibility surveillance · Sydney School of Veterinary Science</p></div>",
    unsafe_allow_html=True)

tab1, tab2 = st.tabs(["Data Processing", "Analytics"])

with tab1:
    c1, c2, c3 = st.columns(3)
    with c1:
        ast_file = st.file_uploader("AST LOGGING sheet (Excel)", type=["xlsx"])
    with c2:
        pdf_files = st.file_uploader("PDF report(s)", type=["pdf"], accept_multiple_files=True)
    with c3:
        master_file = st.file_uploader("Existing master (optional)", type=["xlsx"])

    if st.button("Process & Synchronise"):
        if not ast_file:
            st.error("Please upload Bianca's AST LOGGING sheet.")
        elif not pdf_files:
            st.error("Please upload at least one PDF report.")
        else:
            ast_lookup = build_ast_lookup(ast_file)
            pdf_records, bad = [], []
            total = len(pdf_files)
            pb = st.progress(0.0, text=f"Reading reports (0/{total})…")
            for i, f in enumerate(pdf_files):
                pb.progress(i / total, text=f"Reading ({i + 1}/{total}): {f.name}")
                try:
                    pdf_records.extend(parse_pdf_metadata(f))
                except Exception as e:
                    bad.append(f"{f.name}: {e}")
            pb.progress(1.0, text="Done")

            final_df, skipped = build_dataframe(pdf_records, ast_lookup)

            if final_df.empty:
                st.warning("No isolates matched between the PDF(s) and the AST sheet. Check the CP numbers and isolate names line up.")
            else:
                if master_file:
                    try:
                        master_df = pd.read_excel(master_file)
                        final_df = pd.concat([master_df, final_df], ignore_index=True)
                        final_df = final_df.drop_duplicates(
                            subset=['Lab Reference', 'Sample Type', 'Site', 'Sample Site (Detailed)', 'Isolate'],
                            keep='last')
                    except Exception as e:
                        st.error(f"Could not read master sheet: {e}")
                st.session_state['processed_data'] = final_df
                st.session_state['skipped'] = skipped
                st.session_state['bad'] = bad

    if 'processed_data' in st.session_state:
        final_df = st.session_state['processed_data']
        st.dataframe(final_df.style.map(lambda v: SIR_FILL.get(v, '')), use_container_width=True)

        aus_time = datetime.now(timezone.utc) + timedelta(hours=10)
        fname = f"AMR_Surveillance_{aus_time.strftime('%Y%m%d')}.xlsx"
        st.download_button("Download master Excel", build_excel(final_df), fname,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        if st.session_state.get('skipped'):
            st.info("Isolates with no matching AST row (not included): "
                    + ", ".join(st.session_state['skipped']))
        if st.session_state.get('bad'):
            for b in st.session_state['bad']:
                st.error(b)

with tab2:
    if 'processed_data' not in st.session_state:
        st.info("Process data in the first tab to unlock analytics.")
    else:
        df = st.session_state['processed_data'].copy()
        clean = df[~df["Isolate"].isin(["nan", "NA", "Na", ""])]

        m1, m2, m3 = st.columns(3)
        m1.metric("Total isolates", len(clean))
        m2.metric("Unique clinical cases", clean["Lab Reference"].nunique())
        m3.metric("Unique bacteria types", clean["Isolate"].nunique())

        st.divider()
        st.subheader("Bacterial species distribution")
        col_chart, col_data = st.columns([2, 1])
        counts = clean["Isolate"].value_counts()
        x_cats, y_vals = counts.index.tolist(), [int(v) for v in counts.values]
        max_y = max(y_vals) if y_vals else 10
        with col_chart:
            fig = go.Figure(data=[go.Bar(x=x_cats, y=y_vals, marker_color=NAVY,
                hovertemplate="<b>Species:</b> %{x}<br><b>Isolates:</b> %{y}<extra></extra>")])
            fig.update_layout(height=560, template="simple_white",
                xaxis_title="<b>Species identified</b>", yaxis_title="<b>Number of isolates</b>",
                font=dict(color=INK, size=15), margin=dict(b=200, t=30, l=0, r=0))
            fig.update_xaxes(tickangle=-40, showline=True, linewidth=1.5, linecolor=INK)
            fig.update_yaxes(showline=True, linewidth=1.5, linecolor=INK, range=[0, max_y * 1.15])
            fig.add_annotation(text="Figure 1. Distribution of bacterial species across processed reports.",
                xref="paper", yref="paper", x=0, y=-0.42, showarrow=False,
                font=dict(size=12, color=MUTED), align="left", xanchor="left", yanchor="top")
            st.plotly_chart(fig, use_container_width=True)
        with col_data:
            st.markdown("**Verification table**")
            st.dataframe(pd.DataFrame({"Bacterial species": x_cats, "Isolates": y_vals}),
                         use_container_width=True, hide_index=True)

        # Bacterial species per host species
        st.divider()
        st.subheader("Species distribution per host species")
        host_species = [s for s in clean["Species"].unique() if s not in ("NA", "nan")]
        hcols = st.columns(max(len(host_species), 1))
        for col, host in zip(hcols, host_species):
            sub = clean[clean["Species"] == host]
            sc = sub["Isolate"].value_counts()
            with col:
                figh = go.Figure(data=[go.Bar(
                    x=[int(v) for v in sc.values], y=sc.index.tolist(), orientation='h',
                    marker_color=NAVY,
                    hovertemplate="<b>%{y}</b><br>Isolates: %{x}<extra></extra>")])
                figh.update_layout(height=360, template="simple_white", title=f"<b>{host}</b>",
                    xaxis_title="<b>Isolates</b>", font=dict(color=INK, size=13),
                    margin=dict(l=0, r=10, t=40, b=40))
                figh.update_yaxes(autorange="reversed")
                st.plotly_chart(figh, use_container_width=True)

        # Resistance profiles
        st.divider()
        sir_cols = [c for c in df.columns if df[c].isin(['S', 'I', 'R']).any()]
        if sir_cols:
            st.subheader("Global resistance profiles")
            melted = df[sir_cols].melt(var_name="ABx", value_name="Res")
            melted = melted[melted["Res"].isin(["S", "I", "R"])]
            melted['Res'] = melted['Res'].map({'S': 'Susceptible', 'I': 'Intermediate', 'R': 'Resistant'})
            cmap = {'Susceptible': '#2ca02c', 'Intermediate': '#e0a800', 'Resistant': ACCENT}

            fig_sir = px.histogram(melted, x="ABx", color="Res", barmode="group",
                color_discrete_map=cmap, category_orders={"Res": ["Resistant", "Intermediate", "Susceptible"]},
                template="simple_white")
            fig_sir.update_traces(hovertemplate="<b>%{x}</b><br>%{data.name}: %{y}<extra></extra>")
            fig_sir.update_layout(height=520, xaxis_tickangle=-45, font=dict(color=INK, size=14),
                legend=dict(title="<b>Susceptibility</b>"), margin=dict(b=160, t=30, l=0, r=0))
            max_c = melted.groupby(['ABx', 'Res']).size().max() if not melted.empty else 10
            fig_sir.update_yaxes(title_text="<b>Count</b>", range=[0, max_c * 1.15])
            fig_sir.update_xaxes(title_text="<b>Antibiotic</b>")
            fig_sir.add_annotation(text="Figure 2. Antimicrobial susceptibility counts per antibiotic.",
                xref="paper", yref="paper", x=0, y=-0.55, showarrow=False,
                font=dict(size=12, color=MUTED), align="left", xanchor="left", yanchor="top")
            st.plotly_chart(fig_sir, use_container_width=True)

            st.divider()
            st.subheader("Resistance profiles (normalised %)")
            fig_pct = px.histogram(melted, x="ABx", color="Res", barmode="relative", barnorm="percent",
                color_discrete_map=cmap, category_orders={"Res": ["Resistant", "Intermediate", "Susceptible"]},
                template="simple_white")
            fig_pct.update_traces(hovertemplate="<b>%{x}</b><br>%{data.name}: %{y:.1f}%<extra></extra>")
            fig_pct.update_layout(height=520, xaxis_tickangle=-45, font=dict(color=INK, size=14),
                legend=dict(title="<b>Susceptibility</b>"), margin=dict(b=160, t=30, l=0, r=0))
            fig_pct.update_yaxes(title_text="<b>Percentage (%)</b>", range=[0, 100])
            fig_pct.update_xaxes(title_text="<b>Antibiotic</b>")
            st.plotly_chart(fig_pct, use_container_width=True)

        # Sample site
        st.divider()
        st.subheader("Sample site distribution")
        clean_sites = df[~df["Site"].isin(["nan", "NA", "Na", ""])]
        s_counts = clean_sites["Site"].value_counts()
        figs = go.Figure(data=[go.Bar(x=s_counts.index.tolist(), y=[int(v) for v in s_counts.values],
            marker_color=ACCENT, hovertemplate="<b>%{x}</b><br>Count: %{y}<extra></extra>")])
        figs.update_layout(height=480, template="simple_white", xaxis_title="<b>Sample site</b>",
            yaxis_title="<b>Count</b>", font=dict(color=INK, size=14), margin=dict(b=150, t=30, l=0, r=0))
        figs.update_xaxes(tickangle=-40, showline=True, linewidth=1.5, linecolor=INK)
        figs.update_yaxes(showline=True, linewidth=1.5, linecolor=INK)
        st.plotly_chart(figs, use_container_width=True)
