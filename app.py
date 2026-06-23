import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
import openpyxl
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

# ============================================================================
# CONFIGURATION
# ============================================================================
# Metadata columns pulled from Bianca's AST LOGGING sheet (by 0-based column index).
# These match the fixed left-hand columns of every year sheet.
AST_META_COLS = {
    0: "Date Received",
    1: "CP Number",          # used as the matching key (PDF "Our Ref")
    2: "Name",
    3: "Clinic",
    4: "External Reference",
    5: "Species",
    6: "Breed",
    7: "Sex",
    8: "Sample Type",
    9: "Site",
    10: "Isolate",
    11: "MALDI Score",
}
# First antibiotic column in the AST sheet (0-based). From here on, columns come
# in pairs: (zone-diameter measurement, S/I/R interpretation). We take the SECOND
# column of each pair as the result.
AST_FIRST_ABX_COL = 13

# Canonical antibiotic abbreviations, in the fixed column order of the AST sheet.
# We key by POSITION (not the per-sheet header text) because Bianca's older tabs
# label cefazolin "CZ 30" while 2025/2026 use "CZN 30" — same column, same drug.
# Each abbreviation occupies a pair of columns (measurement, then S/I/R).
CANON_ABBREVS = [
    "AM10", "AMC30", "CZN 30", "CL30", "CAZ30", "CVN30", "DO30", "SXT", "ENR5",
    "MAR", "GM 10", "C30", "P10", "F/M300", "N30", "OX1", "FOX30", "CC2", "E15",
    "TIC75", "TIM85", "S5", "CN 120", "RD5", "FA10", "AN30", "IPM10", "VA30",
]

# Sheets in the AST workbook that are NOT year data and should be skipped.
AST_SKIP_SHEETS = {"MALDI ID NAME LIST"}

# Antibiotic-class importance colours, keyed by the AST abbreviation.
# Mirrors the colour scheme of the original report (Green=Low, Yellow=Medium, Red=High).
# NOTE: CAZ30, FOX30, TIC75 and S5 are left uncoloured pending confirmation from Bianca.
GREEN = "FFC6EFCE"; YELLOW = "FFFFEB9C"; RED = "FFFFC7CE"
ABX_HEADER_COLORS = {
    # Low importance (green)
    "AM10": GREEN, "CZN 30": GREEN, "CL30": GREEN, "DO30": GREEN, "SXT": GREEN,
    "C30": GREEN, "P10": GREEN, "CC2": GREEN, "E15": GREEN, "FA10": GREEN,
    # Medium importance (yellow)
    "AMC30": YELLOW, "GM 10": YELLOW, "N30": YELLOW, "TIM85": YELLOW, "CN 120": YELLOW,
    # High importance (red)
    "ENR5": RED, "MAR": RED, "CVN30": RED, "OX1": RED, "F/M300": RED,
    "RD5": RED, "AN30": RED, "IPM10": RED, "VA30": RED,
}

# S/I/R cell fill colours (body of the table).
SIR_FILL = {"S": "background-color: #C6EFCE", "I": "background-color: #FFEB9C", "R": "background-color: #FFC7CE"}


# ============================================================================
# 3. CORE PROCESSING FUNCTIONS
# ============================================================================
def normalize_cp(value):
    """Normalize a CP/Our Ref value to the bare 'YY-NNNNN' key used for matching."""
    if value is None:
        return None
    m = re.search(r'(\d{2}-\d{4,5})', str(value))
    return m.group(1) if m else None


def standardize_age(age_string):
    if not age_string:
        return "NA"
    years, months = 0, 0
    year_match = re.search(r'(\d+)\s*(y|year|years)', age_string, re.IGNORECASE)
    if year_match:
        years = int(year_match.group(1))
    month_match = re.search(r'(\d+)\s*(m|month|months)', age_string, re.IGNORECASE)
    if month_match:
        months = int(month_match.group(1))
    return f"{years}Y {months}M"


def standardize_date(date_string):
    if not date_string or date_string == "NA":
        return "NA"
    try:
        clean_str = re.sub(r'^[a-zA-Z]+,\s*', '', date_string)
        clean_str = re.sub(r'\s+\d{1,2}:\d{2}\s+[APMpm]{2}$', '', clean_str)
        dt = datetime.strptime(clean_str.strip(), "%d %B %Y")
        return dt.strftime("%Y%m%d")
    except Exception:
        try:
            dt = pd.to_datetime(date_string, errors='coerce')
            if pd.notna(dt):
                return dt.strftime("%Y%m%d")
        except Exception:
            pass
    return date_string


def parse_pdf_report(file_object):
    """From the PDF we now extract ONLY what the AST sheet lacks:
       the CP/Our Ref (for matching), the animal's Age, and the Report Date."""
    with pdfplumber.open(file_object) as pdf:
        raw_text = "".join((page.extract_text() or "") + "\n" for page in pdf.pages)

    cp_key = normalize_cp(re.search(r'Our Ref:\s*(?:CP\s*)?(\d{2}-\d{4,5})', raw_text, re.IGNORECASE))

    report_date_raw = re.search(r'Report date:\s*(.*?)(?=\s*Page:|\n)', raw_text, re.IGNORECASE)
    report_date_val = standardize_date(report_date_raw.group(1).strip() if report_date_raw else "NA")

    age_raw = re.search(r'(\d+\s*(?:Years?|Months?|Weeks?))', raw_text, re.IGNORECASE)
    age_val = standardize_age(age_raw.group(1)) if age_raw else "NA"

    return cp_key, {"Age": age_val, "Report Date": report_date_val}


def parse_ast_sheet(file_object):
    """Read every year sheet in Bianca's AST LOGGING workbook and return one
       record per isolate row: metadata + S/I/R per antibiotic abbreviation.
       Returns (records, abbrev_order)."""
    wb = openpyxl.load_workbook(file_object, read_only=True, data_only=True)
    records = []

    # Pair each canonical antibiotic to its S/I/R column (the SECOND of its pair).
    # Position is stable across all year tabs, so we don't rely on header text.
    sir_cols = {abx: AST_FIRST_ABX_COL + 1 + 2 * i for i, abx in enumerate(CANON_ABBREVS)}

    for sheet_name in wb.sheetnames:
        if sheet_name in AST_SKIP_SHEETS:
            continue
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = rows[0]
        # Confirm this looks like a data sheet (has CP NUMBER in column 1).
        if not header or len(header) < 2 or str(header[1]).strip().upper() != "CP NUMBER":
            continue

        for row in rows[1:]:
            if len(row) < 2 or not row[1]:
                continue
            cp_key = normalize_cp(row[1])
            rec = {"_cp_key": cp_key, "CP Number": f"CP {cp_key}" if cp_key else "NA"}
            for idx, name in AST_META_COLS.items():
                if name == "CP Number":
                    continue
                rec[name] = row[idx] if idx < len(row) and row[idx] is not None else "NA"
            for abx, si in sir_cols.items():
                v = row[si] if si < len(row) else None
                rec[abx] = v if v in ("S", "I", "R") else "NA"
            records.append(rec)

    return records, list(CANON_ABBREVS)


def build_dataframe(ast_records, abbrev_order, pdf_lookup):
    """Merge AST isolate rows with Age + Report Date from the matched PDFs."""
    meta_order = ["Report Date", "CP Number", "Date Received", "Name", "Clinic",
                  "External Reference", "Species", "Breed", "Sex", "Age",
                  "Sample Type", "Site", "Isolate", "MALDI Score"]
    rows = []
    for rec in ast_records:
        pdf_info = pdf_lookup.get(rec["_cp_key"], {"Age": "NA", "Report Date": "NA"})
        merged = {}
        merged["Report Date"] = pdf_info["Report Date"]
        merged["Age"] = pdf_info["Age"]
        for col in meta_order:
            if col in ("Report Date", "Age"):
                continue
            merged[col] = rec.get(col, "NA")
        for abx in abbrev_order:
            merged[abx] = rec.get(abx, "NA")
        rows.append(merged)

    column_order = meta_order + abbrev_order
    df = pd.DataFrame(rows, columns=column_order)
    return df


def build_excel(df, abbrev_order):
    """Write the styled master Excel: S/I/R cell colours + antibiotic header colours."""
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
# 4. SIDEBAR
# ============================================================================
with st.sidebar:
    st.markdown("<div style='text-align: center;'><div style='font-size: 50px;'>🏛️</div><h2 style='color: #002b5c;'>USYD Vet Path</h2></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### 🛠️ Extraction Workflow\n"
                "1. 📊 **Upload** Bianca's AST LOGGING sheet\n"
                "2. 📄 **Drop** the matching PDF report(s)\n"
                "3. ⚡ **Process** & match on CP number\n"
                "4. 📥 **Download** Final Sheet")
    st.info("S/I/R results come from the AST sheet. Age & report date come from the PDF.")

# ============================================================================
# 5. MAIN INTERFACE
# ============================================================================
st.title("🔬 AMR National Surveillance Pipeline")
tab1, tab2 = st.tabs(["🚀 Data Processing", "📊 Live Analytics"])

with tab1:
    c1, c2, c3 = st.columns(3)
    with c1:
        ast_file = st.file_uploader("1. AST LOGGING sheet (Excel)", type=["xlsx"])
    with c2:
        pdf_files = st.file_uploader("2. PDF Report(s)", type=["pdf"], accept_multiple_files=True)
    with c3:
        master_file = st.file_uploader("3. Existing Master (optional)", type=["xlsx"])

    if st.button("🚀 Process & Synchronize"):
        if not ast_file:
            st.error("Please upload Bianca's AST LOGGING sheet.")
        elif not pdf_files:
            st.error("Please upload at least one PDF report.")
        else:
            # Build the Age / Report Date lookup from the PDFs, keyed by CP number.
            pdf_lookup, no_cp = {}, []
            for f in pdf_files:
                try:
                    cp_key, info = parse_pdf_report(f)
                    if cp_key:
                        pdf_lookup[cp_key] = info
                    else:
                        no_cp.append(f.name)
                except Exception as e:
                    st.error(f"Error reading {f.name}: {e}")

            ast_records, abbrev_order = parse_ast_sheet(ast_file)

            # Keep only AST rows whose CP number matches an uploaded PDF.
            matched = [r for r in ast_records if r["_cp_key"] in pdf_lookup]
            matched_cps = {r["_cp_key"] for r in matched}
            unmatched_pdfs = [cp for cp in pdf_lookup if cp not in matched_cps]

            if not matched:
                st.warning("No AST rows matched the uploaded PDF(s). Check the CP numbers line up.")
            else:
                final_df = build_dataframe(matched, abbrev_order, pdf_lookup)

                # Optionally append to an existing master sheet.
                if master_file:
                    try:
                        master_df = pd.read_excel(master_file)
                        final_df = pd.concat([master_df, final_df], ignore_index=True)
                        final_df = final_df.drop_duplicates(
                            subset=['CP Number', 'Sample Type', 'Site', 'Isolate'], keep='last')
                    except Exception as e:
                        st.error(f"Could not read master sheet: {e}")

                st.session_state['processed_data'] = final_df
                st.session_state['abbrev_order'] = abbrev_order
                st.session_state['no_cp'] = no_cp
                st.session_state['unmatched_pdfs'] = unmatched_pdfs

    if 'processed_data' in st.session_state:
        final_df = st.session_state['processed_data']
        abbrev_order = st.session_state['abbrev_order']

        styled_df = final_df.style.map(lambda v: SIR_FILL.get(v, ''))
        st.dataframe(styled_df, use_container_width=True)

        aus_time = datetime.now(timezone.utc) + timedelta(hours=10)
        download_filename = f"AMR_Surveillance_{aus_time.strftime('%Y%m%d')}.xlsx"
        st.download_button("⬇️ Download Master Excel",
                           build_excel(final_df, abbrev_order),
                           download_filename,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        if st.session_state.get('unmatched_pdfs'):
            st.warning(f"PDF(s) with no matching AST row: {', '.join(st.session_state['unmatched_pdfs'])}")
        if st.session_state.get('no_cp'):
            st.info(f"Could not read a CP number from: {', '.join(st.session_state['no_cp'])}")

with tab2:
    if 'processed_data' in st.session_state:
        df = st.session_state['processed_data'].copy()
        st.header("📊 Surveillance Insights")

        clean_species = df[~df["Isolate"].isin(["nan", "NA", "Na", ""])]

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Number of Isolates", len(clean_species))
        m2.metric("Unique Clinical Cases", clean_species["CP Number"].nunique())
        m3.metric("Unique Bacteria Types", clean_species["Isolate"].nunique())

        st.divider()
        st.subheader("Bacterial Species Distribution")
        col_chart, col_data = st.columns([2, 1])

        counts = clean_species["Isolate"].value_counts()
        x_cats = counts.index.tolist()
        y_vals = [int(v) for v in counts.values]
        max_y = max(y_vals) if y_vals else 10

        with col_chart:
            fig_species = go.Figure(data=[go.Bar(
                x=x_cats, y=y_vals, marker_color='#002b5c',
                hovertemplate="<b>Species Identified:</b> %{x}<br><b>Number of Isolates:</b> %{y}<extra></extra>")])
            fig_species.update_layout(height=600, template="simple_white",
                xaxis_title="<b>Species Identified</b>", yaxis_title="<b>Total Number of Isolates</b>",
                font=dict(color="black", size=18), margin=dict(b=220, t=50, l=0, r=0))
            fig_species.update_xaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            fig_species.update_yaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max_y * 1.1], rangemode="tozero")
            fig_species.add_annotation(text="Figure 1: Distribution of bacterial species identified across all processed clinical reports.",
                xref="paper", yref="paper", x=0, y=-0.55, showarrow=False, font=dict(size=14, color="gray"), align="left", xanchor="left", yanchor="top")
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

            fig_sir = px.histogram(melted, x="ABx", color="Res", barmode="group",
                color_discrete_map={'Susceptible': '#2ca02c', 'Intermediate': '#ffcc00', 'Resistant': '#d62728'},
                category_orders={"Res": ["Resistant", "Intermediate", "Susceptible"]}, template="simple_white")
            fig_sir.update_traces(hovertemplate="<b>Antibiotic:</b> %{x}<br><b>Result:</b> %{data.name}<br><b>Count:</b> %{y}<extra></extra>")
            fig_sir.update_layout(height=600, xaxis_tickangle=-45, font=dict(color="black", size=18),
                legend=dict(font=dict(size=16), title=dict(text="<b>Susceptibility</b>", font=dict(size=22))), margin=dict(b=260, t=50, l=0, r=0))
            fig_sir.update_xaxes(title_text="<b>Antibiotic</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            max_c = melted.groupby(['ABx', 'Res']).size().max() if not melted.empty else 10
            fig_sir.update_yaxes(title_text="<b>Count</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max_c * 1.1], rangemode="tozero")
            fig_sir.add_annotation(text="Figure 2: Overall antimicrobial susceptibility profiles (Green: Susceptible, Yellow: Intermediate, Red: Resistant).",
                xref="paper", yref="paper", x=0, y=-0.75, showarrow=False, font=dict(size=14, color="gray"), align="left", xanchor="left", yanchor="top")
            st.plotly_chart(fig_sir, use_container_width=True)

            st.divider()
            st.subheader("Resistance Profiles (Normalized %)")
            fig_pct = px.histogram(melted, x="ABx", color="Res", barmode="relative", barnorm="percent",
                color_discrete_map={'Susceptible': '#2ca02c', 'Intermediate': '#ffcc00', 'Resistant': '#d62728'},
                category_orders={"Res": ["Resistant", "Intermediate", "Susceptible"]}, template="simple_white")
            fig_pct.update_traces(hovertemplate="<b>Antibiotic:</b> %{x}<br><b>Result:</b> %{data.name}<br><b>Percentage:</b> %{y:.1f}%<extra></extra>")
            fig_pct.update_layout(height=600, xaxis_tickangle=-45, font=dict(color="black", size=18),
                legend=dict(font=dict(size=16), title=dict(text="<b>Susceptibility</b>", font=dict(size=22))), margin=dict(b=260, t=50, l=0, r=0))
            fig_pct.update_xaxes(title_text="<b>Antibiotic</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
            fig_pct.update_yaxes(title_text="<b>Percentage (%)</b>", title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, 100], rangemode="tozero")
            st.plotly_chart(fig_pct, use_container_width=True)

        st.divider()
        st.subheader("Sample Site Distribution")
        clean_sites = df[~df["Site"].isin(["nan", "NA", "Na", ""])]
        site_counts = clean_sites["Site"].value_counts()
        x_site = site_counts.index.tolist()
        y_site = [int(v) for v in site_counts.values]
        max_y_site = max(y_site) if y_site else 10
        fig_site = go.Figure(data=[go.Bar(x=x_site, y=y_site, marker_color='#e64646',
            hovertemplate="<b>Sample Site:</b> %{x}<br><b>Count:</b> %{y}<extra></extra>")])
        fig_site.update_layout(height=600, template="simple_white", xaxis_title="<b>Sample Site</b>", yaxis_title="<b>Count</b>",
            font=dict(color="black", size=18), margin=dict(b=180, t=50, l=0, r=0))
        fig_site.update_xaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black')
        fig_site.update_yaxes(title_font=dict(size=20), tickfont=dict(size=16), showline=True, linewidth=2, linecolor='black', range=[0, max_y_site * 1.1], rangemode="tozero")
        st.plotly_chart(fig_site, use_container_width=True)
    else:
        st.info("💡 Process data in tab 1 to unlock analytics.")
