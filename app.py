import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
import os
import base64
import openpyxl
import plotly.graph_objects as go
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from datetime import datetime, timedelta, timezone

# ============================================================================
# 1. PAGE CONFIG
# ============================================================================
st.set_page_config(
    page_title="AST National Surveillance | USYD",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# 2. THEME (University of Sydney blue, white canvas, no gradients)
# ============================================================================
BLUE_900 = "#0a2540"; BLUE_800 = "#103a6b"; BLUE_700 = "#14539a"
BLUE_600 = "#1d6fd6"; BLUE_500 = "#2f88e6"; BLUE_300 = "#93c2f4"
BLUE_50 = "#eef5fd"; INK = "#141414"; MUTED = "#141414"
LINE = "#e2eaf3"; CANVAS = "#ffffff"; WHITE = "#ffffff"

# Organism / category sequence: one blue family.
BLUE_SEQ = ["#1d6fd6", "#103a6b", "#2f88e6", "#5aa2ee", "#0a2540", "#14539a", "#93c2f4", "#3f97ea"]
# S / I / R keep their clinical colours.
SIR_CMAP = {"Susceptible": "#1aa260", "Intermediate": "#e0a400", "Resistant": "#d63a4a"}

st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
    html, body, [class*="css"], .stApp {{
        font-family:'Inter',-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
        color:{INK}; font-size:16px;
    }}
    .stApp {{ background-color:{CANVAS}; }}
    .block-container {{ padding-top:1.4rem; max-width:1340px; }}
    .amr-hero {{
        position:relative; overflow:hidden; background:{BLUE_600};
        border-radius:18px; padding:2rem 2.2rem; margin-bottom:1.6rem;
        box-shadow:0 8px 22px rgba(29,111,214,0.20);
    }}
    .amr-hero h1 {{ color:{WHITE}; font-size:2.35rem; font-weight:800; margin:0;
        letter-spacing:-0.025em; line-height:1.12; }}
    .amr-eyebrow {{ display:inline-block; color:#bcd6f7; font-size:0.82rem; font-weight:700;
        letter-spacing:0.14em; text-transform:uppercase; margin-bottom:0.5rem; }}
    .amr-logo {{ position:absolute; top:1.9rem; right:2.2rem; height:48px; z-index:3; opacity:0.97; }}
    @media (max-width:640px) {{ .amr-logo {{ position:static; height:40px;
        margin-bottom:0.9rem; display:block; }} }}
    .sec {{ display:flex; align-items:center; gap:0.7rem; font-size:1.55rem; font-weight:800;
        color:{BLUE_800}; letter-spacing:-0.015em; margin:0.2rem 0 1rem 0; }}
    .sec-bar {{ width:6px; height:27px; border-radius:6px; background:{BLUE_600}; display:inline-block; }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background:transparent; border:none !important; box-shadow:none !important; padding:0 !important; }}
    [data-testid="stPlotlyChart"] {{ background:{WHITE}; border:1px solid {LINE};
        border-radius:14px; box-shadow:0 3px 14px rgba(46,45,44,0.05); padding:0.6rem 0.8rem; }}
    [data-testid="stDataFrame"] {{ border-radius:12px; overflow:hidden;
        border:1px solid {LINE}; box-shadow:0 3px 14px rgba(46,45,44,0.05); }}
    .stButton>button {{ width:100%; border-radius:11px; height:3.2em; border:none;
        background:{BLUE_600}; color:{WHITE}; font-weight:700; font-size:1.05rem;
        box-shadow:0 4px 12px rgba(29,111,214,0.22); transition:all 0.16s ease; }}
    .stButton>button:hover {{ background:{BLUE_700};
        box-shadow:0 6px 16px rgba(29,111,214,0.30); transform:translateY(-1px); color:{WHITE}; }}
    .stDownloadButton>button {{ border-radius:11px; background:{WHITE}; color:{BLUE_700};
        border:1.6px solid {BLUE_500}; font-weight:700; height:3em; }}
    .stDownloadButton>button:hover {{ background:{BLUE_600}; color:{WHITE}; border-color:{BLUE_600}; }}
    [data-testid="stSidebar"] {{ background:{WHITE}; border-right:1px solid {LINE}; }}
    [data-testid="stSidebar"] h3 {{ color:{BLUE_800}; }}
    .stTabs [data-baseweb="tab-list"] {{ gap:0.5rem; border-bottom:2px solid {LINE}; }}
    .stTabs [data-baseweb="tab"] {{ font-weight:700; font-size:1.04rem; color:{MUTED}; padding:0.6rem 1.2rem; }}
    .stTabs [aria-selected="true"] {{ color:{BLUE_600}; }}
    .stTabs [data-baseweb="tab-highlight"] {{ background:{BLUE_600}; height:3px; border-radius:3px; }}
    [data-testid="stFileUploader"] {{ background:transparent; border:none; padding:0; }}
    [data-testid="stFileUploaderDropzone"] {{
        background:{BLUE_50}; border:1.4px dashed {BLUE_300}; border-radius:11px;
        padding:0.5rem 0.9rem; min-height:auto; }}
    [data-testid="stFileUploaderDropzoneInstructions"] span,
    [data-testid="stFileUploaderDropzoneInstructions"] small {{ font-size:0.74rem; }}
    [data-testid="stFileUploaderDropzone"] button {{ font-size:0.78rem; padding:0.2rem 0.7rem; }}
    .legend-chip {{ display:inline-block; width:14px; height:14px; border-radius:4px;
        margin-right:8px; vertical-align:middle; }}
    .kpi {{ background:{WHITE}; border:1px solid {LINE}; border-radius:16px;
        padding:1.1rem 1.25rem; box-shadow:0 3px 14px rgba(46,45,44,0.06);
        display:flex; flex-direction:column; justify-content:center; text-align:center;
        min-height:150px; }}
    .kpi-body {{ margin:0; }}
    .kpi-num {{ font-size:3rem; font-weight:900; line-height:1; color:{INK}; }}
    .kpi-lab {{ font-size:1.12rem; font-weight:800; color:{INK}; margin-top:0.35rem; }}
    .kpi-total {{ background:{BLUE_600}; border:none;
        box-shadow:0 6px 16px rgba(29,111,214,0.24); }}
    .kpi-total .kpi-num {{ color:{WHITE}; font-size:3.4rem; }}
    .kpi-total .kpi-lab {{ color:{WHITE}; }}
    .callout {{ background:{WHITE}; border:1px solid {LINE}; border-radius:13px;
        padding:0.9rem 1.15rem; margin:0.6rem 0; box-shadow:0 2px 10px rgba(46,45,44,0.05); }}
    .callout-head {{ display:flex; align-items:center; gap:0.55rem; font-weight:800;
        font-size:1.06rem; color:{INK}; }}
    .callout-dot {{ width:11px; height:11px; border-radius:50%; display:inline-block; flex:0 0 auto; }}
    .callout-count {{ margin-left:auto; border-radius:999px; padding:0.12rem 0.7rem;
        font-size:0.82rem; font-weight:800; line-height:1.4; }}
    .callout ol, .callout ul {{ margin:0.6rem 0 0.1rem 1.3rem; color:{INK}; }}
    .callout li {{ margin:0.2rem 0; padding-left:0.15rem; }}
    .mode-note {{ background:{BLUE_50}; border:1px solid {LINE}; border-left:4px solid {BLUE_500};
        border-radius:12px; padding:0.75rem 1.05rem; color:{INK}; margin:0.3rem 0 0.2rem 0; }}
    hr {{ border-color:{LINE}; }}
    </style>
""", unsafe_allow_html=True)


def section(title, note=None):
    st.markdown(f"<div class='sec'><span class='sec-bar'></span>{title}</div>", unsafe_allow_html=True)
    if note:
        st.markdown(f"<div style='color:{MUTED};font-size:0.95rem;margin:-0.7rem 0 1rem 1.1rem;'>{note}</div>",
                    unsafe_allow_html=True)


def render_callout(title, items, accent, tint, ordered=True):
    tag = "ol" if ordered else "ul"
    lis = "".join(f"<li>{it}</li>" for it in items)
    st.markdown(
        f"<div class='callout' style='border-left:4px solid {accent};'>"
        f"<div class='callout-head'>"
        f"<span class='callout-dot' style='background:{accent};'></span>{title}"
        f"<span class='callout-count' style='background:{tint};color:{accent};'>{len(items)}</span>"
        f"</div><{tag}>{lis}</{tag}></div>",
        unsafe_allow_html=True)


def style_fig(fig, height, bottom=40):
    fig.update_layout(
        height=height, template="simple_white", plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color=INK, size=17, family="Inter"), margin=dict(b=bottom, t=24, l=4, r=4),
        hoverlabel=dict(font=dict(size=16, color=INK, family="Inter"), bgcolor="white", bordercolor=LINE),
    )
    fig.update_xaxes(showline=True, linewidth=1.4, linecolor="#9a948e", tickfont=dict(size=16, color=INK))
    fig.update_yaxes(showline=True, linewidth=1.4, linecolor="#9a948e", gridcolor=LINE, tickfont=dict(size=16, color=INK))
    return fig


def set_titles(fig, xtitle="", ytitle=""):
    """Set axis titles with an explicit black font (update_layout resets the colour)."""
    fig.update_xaxes(title=dict(text=xtitle, font=dict(size=16, color=INK)))
    fig.update_yaxes(title=dict(text=ytitle, font=dict(size=16, color=INK)))


@st.cache_data
def logo_data_uri():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("usyd_logo_white.png", "assets/usyd_logo_white.png"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return "data:image/png;base64," + base64.b64encode(fh.read()).decode()
    return None


# ============================================================================
# 3. CONFIGURATION
# ============================================================================
AST_FIRST_ABX_COL = 13
AST_CP_COL = 1
AST_ISOLATE_COL = 10
AST_CLINIC_COL = 3
AST_MALDI_SCORE_COL = 11
AST_DATE_COL = 0
AST_SPECIES_COL = 5
AST_BREED_COL = 6
AST_SEX_COL = 7
AST_SAMPLE_COL = 8
AST_SITE_COL = 9
AST_SKIP_SHEETS = {"MALDI ID NAME LIST"}

CANON_ABBREVS = [
    "AM10", "AMC30", "CZN 30", "CL30", "CAZ30", "CVN30", "DO30", "SXT", "ENR5",
    "MAR", "GM 10", "C30", "P10", "F/M300", "N30", "OX1", "FOX30", "CC2", "E15",
    "TIC75", "TIM85", "S5", "CN 120", "RD5", "FA10", "AN30", "IPM10", "VA30",
]

# Disk code -> full antibiotic name for display (clinicians don't read disk codes).
ABX_FULL = {
    "AM10": "Ampicillin", "AMC30": "Amoxicillin-clavulanate", "CZN 30": "Cefazolin",
    "CL30": "Cefalexin", "CAZ30": "Ceftazidime", "CVN30": "Cefovecin", "DO30": "Doxycycline",
    "SXT": "Trimethoprim-sulfamethoxazole", "ENR5": "Enrofloxacin", "MAR": "Marbofloxacin",
    "GM 10": "Gentamicin", "C30": "Chloramphenicol", "P10": "Penicillin",
    "F/M300": "Nitrofurantoin", "N30": "Neomycin", "OX1": "Oxacillin", "FOX30": "Cefoxitin",
    "CC2": "Clindamycin", "E15": "Erythromycin", "TIC75": "Ticarcillin",
    "TIM85": "Ticarcillin-clavulanate", "S5": "Streptomycin", "CN 120": "Gentamicin (high-level)",
    "RD5": "Rifampicin", "FA10": "Fusidic acid", "AN30": "Amikacin", "IPM10": "Imipenem",
    "VA30": "Vancomycin", "Ceftiofur": "Ceftiofur", "Polymyxin B": "Polymyxin B",
    "Pradofloxacin": "Pradofloxacin", "Tobramycin": "Tobramycin",
}

PDF_COLUMNS = [
    "Arrival Date", "Report Date", "Lab Reference", "Species", "Breed", "Age",
    "Sex", "Neutered", "Sample Type", "Site", "Sample Site (Detailed)", "Purity", "Isolate",
]

# Full antibiotic names as they appear on the PDF report -> AST sheet abbreviation.
# Used to read the susceptibility table from the report when the AST sheet has no row.
PDF_ABX_MAP = {
    "penicillin": "P10", "clindamycin": "CC2", "ticarcillin/clavulanic acid": "TIM85",
    "ticarcillin": "TIC75", "ampicillin": "AM10", "amoxicillin/clavulanic acid": "AMC30",
    "amoxicillin/clavulanate": "AMC30", "amikacin": "AN30", "oxacillin": "OX1",
    "gentamicin": "GM 10", "gentamicin 120": "CN 120", "high level gentamicin": "CN 120",
    "gentamicin (high level)": "CN 120", "gentamicin high level": "CN 120", "gentamicin (high)": "CN 120",
    "imipenem": "IPM10", "chloramphenicol": "C30", "trimethoprim/sulpha": "SXT",
    "trimethoprim/sulphamethoxazole": "SXT", "trimethoprim-sulfamethoxazole": "SXT",
    "vancomycin": "VA30", "erythromycin": "E15", "cefoxitin": "FOX30", "rifampicin": "RD5",
    "doxycycline": "DO30", "cefalexin": "CL30", "cephalexin": "CL30", "cefazolin": "CZN 30",
    "cephazolin": "CZN 30", "ceftazidime": "CAZ30", "neomycin": "N30", "enrofloxacin": "ENR5",
    "marbofloxacin": "MAR", "fusidic acid": "FA10", "cefovecin": "CVN30", "streptomycin": "S5",
    "nitrofurantoin": "F/M300",
    "ceftiofur": "Ceftiofur", "polymyxin b": "Polymyxin B",
    "pradofloxacin": "Pradofloxacin", "tobramycin": "Tobramycin",
}

# Antibiotics tested on the PDF reports that have no column in the AST logging sheet.
# These are filled from the report only (the sheet never carries a value for them).
# Kept as full names until Kate confirms the preferred abbreviations.
REPORT_ONLY_ABX = ["Ceftiofur", "Polymyxin B", "Pradofloxacin", "Tobramycin"]
ALL_ABX = CANON_ABBREVS + REPORT_ONLY_ABX

OUTPUT_COLUMNS = [
    "Arrival Date", "Report Date", "Lab Reference", "Clinic", "Species", "Breed", "Age",
    "Sex", "Neutered", "Sample Type", "Site", "Sample Site (Detailed)", "Purity",
    "Isolate", "Gram reaction", "MALDI Score",
] + ALL_ABX

GRAM_POSITIVE_GENERA = {
    "actinomyces", "aerococcus", "anaerococcus", "arcanobacterium", "atopobium",
    "bacillus", "brevibacterium", "cellulosimicrobium", "clostridioides", "clostridium",
    "corynebacterium", "cutibacterium", "dermatophilus", "enterococcus", "erysipelothrix",
    "exiguobacterium", "facklamia", "finegoldia", "gemella", "globicatella",
    "granulicatella", "helcococcus", "kocuria", "lactiplantibacillus", "lactobacillus",
    "lactococcus", "leuconostoc", "ligilactobacillus", "limosilactobacillus", "listeria",
    "lysinibacillus", "macrococcus", "mammaliicoccus", "micrococcus", "mycobacterium",
    "nocardia", "nocardiopsis", "paenarthrobacter", "paenibacillus", "paeniclostridium",
    "pediococcus", "peptoniphilus", "peptostreptococcus", "priestia", "propionibacterium",
    "pseudarthrobacter", "rhodococcus", "rossellomorea", "rothia", "schaalia",
    "staphylococcus", "streptococcus", "streptomyces", "terrisporobacter", "trueperella",
    "vagococcus", "weissella", "winkia",
}
GRAM_NEGATIVE_GENERA = {
    "achromobacter", "acinetobacter", "actinobacillus", "aeromonas", "alcaligenes",
    "arcobacter", "avibacterium", "bacteroides", "bartonella", "bibersteinia",
    "bordetella", "brevundimonas", "brucella", "burkholderia", "campylobacter",
    "capnocytophaga", "chryseobacterium", "citrobacter", "comamonas", "cronobacter",
    "dichelobacter", "edwardsiella", "eikenella", "elizabethkingia", "empedobacter",
    "enterobacter", "escherichia", "filobacterium", "flavobacterium", "francisella",
    "frederiksenia", "fusobacterium", "gallibacterium", "haemophilus", "hafnia",
    "helicobacter", "histophilus", "klebsiella", "kluyvera", "lelliottia", "leptospira",
    "lonepinella", "mannheimia", "moraxella", "morganella", "neisseria", "ochrobactrum",
    "oligella", "ornithobacterium", "pantoea", "pasteurella", "phocoenobacter",
    "photobacterium", "plesiomonas", "pluralibacter", "porphyromonas", "prevotella",
    "proteus", "providencia", "pseudescherichia", "pseudomonas", "psychrobacter",
    "raoultella", "riemerella", "rodentibacter", "salmonella", "serratia", "shewanella",
    "shigella", "sphingomonas", "stenotrophomonas", "taylorella", "veillonella", "vibrio",
    "wohlfahrtiimonas", "yersinia", "yokenella",
}


def gram_status(isolate):
    if not isolate or str(isolate).strip() in ("NA", "nan", "Na", ""):
        return "NA"
    genus = str(isolate).strip().split()[0].strip(".,;:").lower()
    if genus in GRAM_POSITIVE_GENERA:
        return "Positive"
    if genus in GRAM_NEGATIVE_GENERA:
        return "Negative"
    return "NA"


def cell_css(v):
    if v == "S":
        return "background-color: #C6EFCE"
    if v == "I":
        return "background-color: #FFEB9C"
    if v == "R":
        return "background-color: #FFC7CE"
    if v == "INTR":
        return "background-color: #BFE3F7"
    if v is None or v == "" or v == "NA" or (isinstance(v, float) and pd.isna(v)):
        return ""
    return "background-color: #FF2D2D; color: white; font-weight: 700"


VALID_SIR = {"S", "I", "R", "INTR"}


# ============================================================================
# 4. HELPERS
# ============================================================================
def normalize_cp(value):
    if value is None:
        return None
    m = re.search(r'(\d{2}-\d{4,5})', str(value))
    return m.group(1) if m else None


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
    if isinstance(date_string, datetime):
        return date_string.strftime("%Y%m%d")
    try:
        clean = re.sub(r'^[a-zA-Z]+,\s*', '', str(date_string))
        clean = re.sub(r'\s+\d{1,2}:\d{2}\s+[APMpm]{2}$', '', clean)
        return datetime.strptime(clean.strip(), "%d %B %Y").strftime("%Y%m%d")
    except Exception:
        try:
            dt = pd.to_datetime(date_string, errors='coerce')
            if pd.notna(dt):
                return dt.strftime("%Y%m%d")
        except Exception:
            pass
    return str(date_string)


# Breed variants that should collapse to one label (keys are lower-case base forms).
BREED_SYNONYMS = {
    "labrador": "Labrador Retriever",
    "english cocker spaniel": "Cocker Spaniel",
    "dsh": "Domestic Shorthair",
    "dlh": "Domestic Longhair",
    "domestic short hair": "Domestic Shorthair",
    "domestic long hair": "Domestic Longhair",
    "staffy": "Staffordshire Bull Terrier",
}


def normalize_breed(breed):
    """Tidy a breed so variants match: title-case, standardise the crossbreed
    marker to a trailing ' X', and map known synonyms to one canonical name."""
    if breed is None:
        return "NA"
    b = re.sub(r'\s+', ' ', str(breed)).strip()
    if not b or b.upper() in ("NA", "N/A"):
        return "NA"
    base = re.sub(r'[\s(]*\b(x|cross|crossbreed)\b[\s)]*$', '', b, flags=re.IGNORECASE).strip()
    return BREED_SYNONYMS.get(base.lower(), base.title())


def clinic_from_report(raw_text):
    m = re.search(r"\bREP\s*ORT\s*\n\s*(.+)", raw_text)
    if not m:
        return "NA"
    line = re.sub(r'\s+', ' ', m.group(1)).strip()
    # Layout is "<CLINIC CODE> <Surname>, <First name>". The clinic is the leading
    # run of all-caps tokens; the owner name that follows is Title case with a comma.
    tokens = []
    for tok in line.split(' '):
        if ',' in tok:
            break
        core = tok.strip(".'-’")
        if core and core == core.upper() and re.search(r'[A-Z]', core) and not re.search(r'\d', core):
            tokens.append(core)
        else:
            break
    c = " ".join(tokens).strip(' .,-')
    if c and len(c) <= 30:
        return c
    return "NA"


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


# Bacterial isolate name normalization: fixes spelling variants (and casing) so the
# same organism does not appear as several isolate types. Edit these maps as needed.
GENUS_FIX = {
    "staphyloccus": "Staphylococcus", "staphylococus": "Staphylococcus",
    "staphyloccocus": "Staphylococcus", "staphylococccus": "Staphylococcus",
    "streptococccus": "Streptococcus", "streptoccocus": "Streptococcus",
    "streptoccoccus": "Streptococcus", "streptococus": "Streptococcus",
    "pseudomona": "Pseudomonas", "pseudomonos": "Pseudomonas",
    "escherchia": "Escherichia", "echerichia": "Escherichia",
    "enterococccus": "Enterococcus", "enterococus": "Enterococcus",
}
SPECIES_FIX = {
    "dysagalactiae": "dysgalactiae", "pseudointermedius": "pseudintermedius",
    "baumanii": "baumannii", "bugundensis": "bugandensis",
    "pneumonaie": "pneumoniae", "maltophila": "maltophilia",
}
# Old name -> current name, by genus (S. intermedius group in companion animals).
SPECIES_MERGE = {("staphylococcus", "intermedius"): "pseudintermedius"}
# A trailing standalone roman numeral or single letter is a MALDI confidence /
# isolate code ("Pasteurella multocida I"), not part of the species name.
_TRAIL_CODE = re.compile(r'(?i)^(i{1,3}|iv|v|[a-z])$')


def normalize_organism(org):
    if org is None:
        return "NA"
    o = re.sub(r'\s+', ' ', str(org)).strip()
    if not o or o.upper() in ("NA", "N/A"):
        return "NA"
    # Any spelling of (pseud)(o)(-/ )inte(r)medius -> pseudintermedius (S. intermedius group).
    o = re.sub(r'pseud[o]?[\s\-]*inte[r]?medius', 'pseudintermedius', o, flags=re.IGNORECASE)
    o = re.sub(r'(staph\w*\s+)inte[r]?medius\b', r'\1pseudintermedius', o, flags=re.IGNORECASE)
    words = o.split()
    if len(words) >= 3 and _TRAIL_CODE.match(words[-1]):
        words = words[:-1]
    genus = GENUS_FIX.get(words[0].lower(), words[0].capitalize())
    gkey = genus.lower()
    out = [genus]
    for i, w in enumerate(words[1:]):
        parts = []
        for p in w.split("/"):          # species may be slash-joined alternatives
            pl = SPECIES_FIX.get(p.lower(), p.lower())
            if i == 0:
                pl = SPECIES_MERGE.get((gkey, pl), pl)
            parts.append(pl)
        out.append("/".join(parts))
    return " ".join(out)


def clean_isolate_name(name):
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return "NA"
    name = str(name)
    name = re.sub(r'^\d+\s*[\.\)]\s*', '', name)
    name = re.sub(r'^(?:Heavy|Moderate|Light|Scanty|Profuse|Abundant|Mixed)\s*growth\s*(?:of\s*)?(?:[-–—]\s*)?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^\d+\s*[\.\)]\s*', '', name)
    name = re.sub(r'^[-–—\s]+', '', name)
    name = " ".join(name.split()).capitalize()
    if not name:
        return "NA"
    NON_ORGANISM = {
        "gram positive", "gram negative", "gram positive cocci", "gram negative rods",
        "gram variable", "no growth", "no significant growth", "no bacterial growth",
        "mixed growth", "mixed culture", "contaminant", "normal flora", "skin flora",
    }
    if name.lower() in NON_ORGANISM:
        return "NA"
    return normalize_organism(name)


def cell_or_na(row, idx):
    if len(row) <= idx or row[idx] in (None, ""):
        return "NA"
    return re.sub(r'\s+', ' ', str(row[idx])).strip()


def parse_ast_sex(raw):
    """AST sheet sex codes: MN = male neutered, FS = female spayed, M/F = entire."""
    s = str(raw).strip().upper()
    if s in ("UNK", "UNKNOWN"):
        return "Unknown", "Unknown"
    if s in ("NA", "N/A", ""):
        return "NA", "NA"
    sex = "Male" if s[0] == "M" else ("Female" if s[0] == "F" else s)
    neutered = "Yes" if s in ("MN", "FS", "FN", "MC", "DESEXED", "NEUTERED", "SPAYED") else "No"
    return sex, neutered


# Different wordings for the same anatomical site, collapsed onto one label.
# Keys are lowercase; add or adjust entries here as Kate confirms them.
SITE_SYNONYMS = {
    "foot": "Foot", "feet": "Foot",
    "belly": "Abdomen", "ventrum": "Abdomen",
    "back": "Dorsum", "dorsum": "Dorsum",
    "axilla": "Axilla", "axila": "Axilla",
    "nail bed": "Nail bed", "nailbed": "Nail bed",
}

# Anatomical direction / plane words. When one of these sits in front of a site word
# ("Ventral abdomen", "Lateral carpus") it is a modifier: the word after it is the
# site and the direction moves to the detailed column. Laterality is handled here too.
SITE_MODIFIERS = {
    "lt": "Left", "rt": "Right",
    "left": "Left", "right": "Right", "bilateral": "Bilateral",
    "ventral": "Ventral", "dorsal": "Dorsal", "lateral": "Lateral",
    "medial": "Medial", "cranial": "Cranial", "caudal": "Caudal",
    "rostral": "Rostral", "proximal": "Proximal", "distal": "Distal",
}
LATERALITY = {"Left", "Right", "Bilateral"}
_MOD_RE = re.compile(r'\b(' + '|'.join(SITE_MODIFIERS) + r')\b', flags=re.IGNORECASE)

# Lesion / finding words (not an anatomical site) and procedure / sample-handling
# words. These never win over a real site: when the main text is only these and a
# real site sits alongside, the site is kept and these move to the detailed column.
LESION_WORDS = {
    "abscess", "sinus", "discharging", "draining", "discharge", "mass", "lesion",
    "wound", "ulcer", "ulcerated", "nodule", "swelling", "cyst", "fistula", "pustule",
    "pus", "exudate", "lump", "growth", "tract", "tracts", "scab", "crust", "erosion",
    "papule", "purulent",
}
PROCEDURE_WORDS = {
    "flush", "flushed", "flushing", "debridement", "debride", "debrided", "lavage",
    "biopsy", "aspirate", "aspiration", "wash", "washed", "voided", "cysto", "op",
    "surgical", "repair", "culture", "exit", "pre", "post", "free", "catch", "punch",
    "swab", "swabs", "gel", "plain", "tube", "site", "area", "screw", "screws",
    "from", "and", "teca", "tecalo", "tecabo", "bo",
}
_QUALIFIER = LESION_WORDS | PROCEDURE_WORDS
# Separators split site from detail: comma / colon / semicolon / pipe / slash, or a
# SPACED hyphen. A word-internal hyphen (PRE-LAVAGE, PERI-ORAL) is NOT a split point.
_SPLIT_RE = re.compile(r'\s*[,:;|/]\s*|\s+-\s+')
_TOKEN_RE = re.compile(r"[A-Za-z]+")
_COUNT_RE = re.compile(r'^\d+\s*x$', flags=re.IGNORECASE)


def _strippable(word):
    """A count prefix (3X) or a word made only of lesion / procedure tokens."""
    if _COUNT_RE.match(word):
        return True
    alts = [a.lower() for a in _TOKEN_RE.findall(word)]
    return bool(alts) and all(a in _QUALIFIER for a in alts)


def _classify(text):
    core = _MOD_RE.sub(' ', text)
    toks = [t.lower() for t in _TOKEN_RE.findall(core)]
    if not toks:
        return 'modifier' if _TOKEN_RE.findall(text) else 'empty'
    if all(t in LESION_WORDS for t in toks):
        return 'lesion'
    if all(t in PROCEDURE_WORDS for t in toks):
        return 'procedure'
    return 'site'


def _cap_detail(text):
    text = text.strip(" ,;-/&+")
    if not text:
        return "NA"
    return ", ".join(p.strip().capitalize() for p in text.split(",") if p.strip()) or "NA"


def _cap_phrase(text):
    """Whole phrase in sentence case, kept as one unit (not comma-split)."""
    text = re.sub(r'\s+', ' ', re.sub(r'[&/+]', ' ', text)).strip(" ,;-/&+")
    return (text[0].upper() + text[1:].lower()) if text else "NA"


def _join(a, b):
    parts = [p for p in (a, b) if p and p != "NA"]
    return ", ".join(parts)


def clean_site(raw):
    """Main site + detail from a free-text site field. A parenthetical or post-separator
    fragment becomes the detail; the part that is a real anatomical site is kept while
    lesion / procedure / laterality words move to the detailed column."""
    s = str(raw).strip() if raw not in (None, "") else ""
    if not s or s.upper() in ("NA", "N/A"):
        return "NA", "NA"
    # A whole field that is only a collection method / procedure (CYSTO, FREE CATCH,
    # PUNCH BIOPSY, VOIDED) is not a site: keep it, as one phrase, in the detail.
    if "(" not in s and not _SPLIT_RE.search(s) and _classify(s) == "procedure":
        return "NA", _cap_phrase(s)
    detail = ""
    m = re.search(r'^(.*?)\s*\((.*?)\)', s)
    if m and (m.group(1).strip() or m.group(2).strip()):
        main = m.group(1).strip()
        after = s[m.end():].strip()
        detail = m.group(2).strip()
        s = main or after
    else:
        parts = _SPLIT_RE.split(s, maxsplit=1)
        if len(parts) > 1:
            s = parts[0].strip()
            detail = re.sub(r'[\)\]\}]+$', '', parts[1].strip()).strip()

    # Of the two parts, keep whichever is the better anatomical site.
    if detail:
        rank = {'site': 3, 'lesion': 2, 'procedure': 1, 'modifier': 0, 'empty': 0}
        if rank[_classify(detail)] > rank[_classify(s)]:
            s, detail = detail, s

    # Strip leading / trailing qualifier words (POST-OP ABDOMINAL CAVITY -> Abdominal).
    words = s.split()
    lead = []
    while len(words) > 1 and _strippable(words[0]):
        lead.append(words.pop(0))
    trail = []
    while len(words) > 1 and _strippable(words[-1]):
        trail.insert(0, words.pop())
    if lead or trail:
        s = " ".join(words)
        detail = _join(detail, " ".join(lead + trail))

    # Direction / laterality words are modifiers: the word after them is the site.
    found = [SITE_MODIFIERS[w.lower()] for w in _MOD_RE.findall(s)]
    core = re.sub(r'[&/+]', ' ', _MOD_RE.sub(' ', s))
    core = re.sub(r'\s+', ' ', core).strip(" -,&/+")
    mod_text = ", ".join(dict.fromkeys(found))
    if found:
        if core:
            detail = _join(mod_text, detail)
            s = core
        elif all(f in LATERALITY for f in found):
            detail = _join(mod_text, detail)   # lone laterality is not a site
            s = ""
        # else: keep a bare plane word (e.g. "Ventral") as the site

    s = re.sub(r'^[^0-9A-Za-z]+|[^0-9A-Za-z]+$', '', s).strip()
    cls = _classify(s) if s else 'empty'
    if cls in ('procedure', 'empty') or (cls == 'modifier' and s.capitalize() in LATERALITY):
        if s and cls != 'empty':
            detail = _join(detail, s)
        s = ""

    s = (s[0].upper() + s[1:].lower()) if s else "NA"
    s = SITE_SYNONYMS.get(s.lower().strip(), s)
    detail = _cap_detail(detail)
    return s, detail


# ============================================================================
# 6. PDF METADATA + SUSCEPTIBILITY EXTRACTION
# ============================================================================
def _parse_susc_table(table):
    """Read a report's susceptibility grid: rows of (name, S/I/R) pairs."""
    res = {}
    for row in table:
        for i in range(0, len(row) - 1, 2):
            name = re.sub(r'\s+', ' ', (row[i] or "").strip().lower())
            letter = (row[i + 1] or "").strip().upper()
            abbr = PDF_ABX_MAP.get(name)
            if abbr and letter in ("S", "I", "R"):
                res.setdefault(abbr, letter)
    return res


def _susc_organism(text):
    """True organism heading (2-3 words, known genus) for associating a table."""
    c = clean_isolate_name(text)
    if c == "NA":
        return None
    toks = c.split()
    if not toks or len(toks) > 3:
        return None
    genus = toks[0].lower().strip(".,;:")
    if genus in GRAM_POSITIVE_GENERA or genus in GRAM_NEGATIVE_GENERA:
        return c.lower()
    return None


def _extract_susceptibility(pdf):
    """Map organism (full name or genus) -> {abbrev: S/I/R} from the report tables,
    associating each susceptibility table with the nearest organism heading above it."""
    import bisect
    orgs, tables = [], []
    for pi, page in enumerate(pdf.pages):
        base = pi * 1000000
        try:
            for ln in page.extract_text_lines():
                og = _susc_organism(ln.get("text", "").strip())
                if og:
                    orgs.append((base + ln["top"], og))
        except Exception:
            pass
        try:
            for w in page.extract_words():
                t = w["text"].strip()
                if len(t) >= 5 and t[:1].isupper() and t.isalpha():
                    g = t.lower()
                    if g in GRAM_POSITIVE_GENERA or g in GRAM_NEGATIVE_GENERA:
                        orgs.append((base + w["top"] + 0.1, g))
        except Exception:
            pass
        try:
            for tb in sorted(page.find_tables(), key=lambda t: t.bbox[1]):
                res = _parse_susc_table(tb.extract())
                if res:
                    tables.append((base + tb.bbox[1], res))
        except Exception:
            pass
    orgs.sort(key=lambda x: x[0])
    order_keys = [o for o, _ in orgs]
    susc = {}
    for torder, res in tables:
        i = bisect.bisect_left(order_keys, torder) - 1
        if i >= 0:
            iso = orgs[i][1]
            d = susc.setdefault(iso, {})
            for k, v in res.items():
                d.setdefault(k, v)
    return susc


def susc_for(iso_key, susc):
    """Look up a record's susceptibility by full name, then by genus as a fallback."""
    if not susc:
        return {}
    if iso_key in susc:
        return susc[iso_key]
    genus = iso_key.split()[0] if iso_key else ""
    if genus in susc:
        return susc[genus]
    cand = [k for k in susc if k.split() and k.split()[0] == genus]
    if len(cand) == 1:
        return susc[cand[0]]
    return {}


def parse_pdf_metadata(file_object):
    records = []
    with pdfplumber.open(file_object) as pdf:
        raw_text = "".join((page.extract_text() or "") + "\n" for page in pdf.pages)
        susc = _extract_susceptibility(pdf)
    clinic_val = clinic_from_report(raw_text)

    # Lab Reference (CP number): try the labelled form first, then any CP in the text,
    # then a bare CP-shaped token, and finally the filename (named with the CP).
    fname = getattr(file_object, "name", "") or getattr(file_object, "filename", "") or ""
    cp_key = None
    for pat, src in ((r'Our Ref[:.]?\s*(?:CP\s*)?(\d{2}-\d{4,5})', raw_text),
                     (r'\bCP[\s:#]*(\d{2}-\d{4,5})', raw_text),
                     (r'\b(\d{2}-\d{4,5})\b', raw_text),
                     (r'(\d{2}-\d{4,5})', str(fname))):
        m = re.search(pat, src, re.IGNORECASE)
        if m:
            cp_key = m.group(1)
            break
    lab_ref_val = f"CP {cp_key}" if cp_key else "NA"

    rd = re.search(r'Report date:\s*(.*?)(?=\s*Page:|\n)', raw_text, re.IGNORECASE)
    report_date_val = standardize_date(rd.group(1).strip() if rd else "NA")

    ad = re.search(r'Arrival date:\s*(.*?)(?=\s*\]|\s*Page:|\n)', raw_text, re.IGNORECASE)
    arrival_date_val = standardize_date(ad.group(1).strip() if ad else "NA")

    sb = re.search(r'(Canine|Feline)[\s\-]+([a-zA-Z\s\-]+?)(?=\s*(?:\n|Male|Female|\d+\s*Years?|Our Ref|$))', raw_text, re.IGNORECASE)
    species_val = sb.group(1).strip().capitalize() if sb else "NA"
    breed_val = normalize_breed(sb.group(2)) if sb else "NA"

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

        sample_site_val = sample_site_val.strip() if isinstance(sample_site_val, str) else "NA"
        sample_site_val, sample_site_detailed_val = clean_site(sample_site_val)

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
    # Reports with no isolate (no significant growth) produce no rows above. Keep a
    # marker so they can be flagged and counted instead of silently disappearing.
    if not records:
        low = raw_text.lower()
        if any(k in low for k in ("no significant growth", "no bacterial growth", "no growth")):
            reason = "No significant growth"
        else:
            reason = "No isolate extracted"
        records.append({
            "Arrival Date": arrival_date_val, "Report Date": report_date_val,
            "Lab Reference": lab_ref_val, "Species": species_val, "Breed": breed_val,
            "Age": age_val, "Sex": sex_val, "Neutered": neutered_val,
            "Sample Type": "NA", "Site": "NA", "Sample Site (Detailed)": "NA",
            "Purity": "NA", "Isolate": reason, "_cp_key": cp_key,
            "_isolate_key": "", "_no_growth": reason,
        })
    for rec in records:
        rec["_susc"] = susc_for(rec["_isolate_key"], susc)
        rec["_clinic"] = clinic_val
    return records


# ============================================================================
# 7. AST ANTIBIOTIC LOOKUP + DIRECT EXTRACTION
# ============================================================================
def resolve_cell(meas, sir):
    if meas is not None and str(meas).strip().upper() == "INTR":
        return "INTR"
    if sir is None:
        return "NA"
    s = str(sir).strip()
    if s.upper() in ("", "N/A", "NA"):
        return "NA"
    if s.upper() in ("S", "I", "R"):
        return s.upper()
    return s


def _ast_sheets(file_object):
    wb = openpyxl.load_workbook(file_object, read_only=True, data_only=True)
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
        yield sheet_name, rows


def build_ast_lookup(file_object):
    meas_cols = {abx: AST_FIRST_ABX_COL + 2 * i for i, abx in enumerate(CANON_ABBREVS)}
    sir_cols = {abx: AST_FIRST_ABX_COL + 1 + 2 * i for i, abx in enumerate(CANON_ABBREVS)}
    lookup = {}
    for _, rows in _ast_sheets(file_object):
        for row in rows[1:]:
            if len(row) <= AST_CP_COL or not row[AST_CP_COL]:
                continue
            cp_key = normalize_cp(row[AST_CP_COL])
            iso = row[AST_ISOLATE_COL] if AST_ISOLATE_COL < len(row) else None
            if not cp_key or not iso:
                continue
            key = (cp_key, str(iso).strip().lower())
            maldi_raw = row[AST_MALDI_SCORE_COL] if AST_MALDI_SCORE_COL < len(row) else None
            try:
                maldi_val = f"{float(maldi_raw):.2f}" if maldi_raw not in (None, "") else "NA"
            except (ValueError, TypeError):
                maldi_val = str(maldi_raw)
            sex_a, neut_a = parse_ast_sex(cell_or_na(row, AST_SEX_COL))
            site_a, _ = clean_site(cell_or_na(row, AST_SITE_COL))
            entry = {
                "Clinic": row[AST_CLINIC_COL] if AST_CLINIC_COL < len(row) and row[AST_CLINIC_COL] is not None else "NA",
                "MALDI Score": maldi_val,
                "IsolateRaw": str(iso).strip(),
                "Species": cell_or_na(row, AST_SPECIES_COL),
                "Breed": normalize_breed(cell_or_na(row, AST_BREED_COL)),
                "Sex": sex_a,
                "Neutered": neut_a,
                "Sample Type": cell_or_na(row, AST_SAMPLE_COL),
                "Site": site_a,
            }
            for abx in CANON_ABBREVS:
                mi, si = meas_cols[abx], sir_cols[abx]
                meas = row[mi] if mi < len(row) else None
                sir = row[si] if si < len(row) else None
                entry[abx] = resolve_cell(meas, sir)
            lookup.setdefault(key, entry)
    return lookup


# Fields present in both the report and the AST sheet, compared to flag mismatches.
CROSS_FIELDS = ["Species", "Breed", "Sex", "Neutered", "Sample Type", "Site"]
# Free-text fields where a truncation or abbreviation is not a real conflict
# (e.g. "Labrador" vs "Labrador Retriever", "Ventral" vs "Ventral interdigital paws").
FUZZY_FIELDS = {"Breed", "Site", "Sample Type"}


def _norm_val(v):
    return re.sub(r'\s+', ' ', str(v)).strip().upper()


def _tokens(v):
    return set(re.sub(r'[^A-Z0-9 ]', ' ', _norm_val(v)).split())


def _values_agree(field, pv, av):
    if _norm_val(pv) == _norm_val(av):
        return True
    if field in FUZZY_FIELDS:
        tp, ta = _tokens(pv), _tokens(av)
        if tp and ta and (tp <= ta or ta <= tp):
            return True
    return False


def cross_check(rec, vals):
    """Return a list of 'Field (report: x, sheet: y)' for fields that genuinely disagree."""
    diffs = []
    for field in CROSS_FIELDS:
        pv, av = rec.get(field, "NA"), vals.get(field, "NA")
        if _norm_val(pv) in ("NA", "N/A", "") or _norm_val(av) in ("NA", "N/A", ""):
            continue
        if not _values_agree(field, pv, av):
            diffs.append(f"{field} (report: {pv}, sheet: {av})")
    return diffs


# ============================================================================
# 8. MERGE (PDF metadata + AST antibiotics, with cross-check)
# ============================================================================
def build_dataframe(pdf_records, ast_lookup):
    cp_isos = {}
    for (cp, _iso), entry in ast_lookup.items():
        cp_isos.setdefault(cp, set()).add(entry.get("IsolateRaw", _iso))
    cp_set = set(cp_isos)

    rows, not_in_sheet, name_diff, discrepancies = [], [], [], []
    for rec in pdf_records:
        if rec.get("_no_growth"):     # no-growth markers are not isolate rows
            continue
        key = (rec["_cp_key"], rec["_isolate_key"])
        merged = {col: rec[col] for col in PDF_COLUMNS}
        merged["Gram reaction"] = gram_status(rec["Isolate"])
        if key in ast_lookup:
            vals = ast_lookup[key]
            diffs = cross_check(rec, vals)
            if diffs:
                discrepancies.append(f'{rec["Lab Reference"]}: {rec["Isolate"]} — ' + "; ".join(diffs))
            merged["Clinic"] = vals.get("Clinic", "NA")
            merged["MALDI Score"] = vals.get("MALDI Score", "NA")
            for abx in CANON_ABBREVS:
                merged[abx] = vals.get(abx, "NA")
            # The sheet has no column for these, so read them from the report.
            rec_susc = rec.get("_susc", {})
            for abx in REPORT_ONLY_ABX:
                merged[abx] = rec_susc.get(abx, "NA")
        else:
            label = f'{rec["Lab Reference"]}: {rec["Isolate"]}'
            if rec["_cp_key"] in cp_set:
                sheet_has = ", ".join(sorted(cp_isos.get(rec["_cp_key"], set())))
                name_diff.append(f'{label} (sheet has: {sheet_has})')
            else:
                not_in_sheet.append(label)
            merged["Clinic"] = rec.get("_clinic", "NA")
            merged["MALDI Score"] = "NA"
            rec_susc = rec.get("_susc", {})
            for abx in ALL_ABX:
                merged[abx] = rec_susc.get(abx, "NA")
        rows.append(merged)
    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if not df.empty:
        df = df.drop_duplicates(subset=["Lab Reference", "Isolate"] + ALL_ABX, keep="first")
        df = df.sort_values(["Lab Reference", "Isolate"]).reset_index(drop=True)
    return df, not_in_sheet, name_diff, discrepancies


def build_from_pdf_only(pdf_files):
    """Metadata-only master from reports. Antibiotic results need the AST sheet, so
    the susceptibility columns are left blank."""
    records, bad, cp_files = [], [], {}
    for f in pdf_files:
        try:
            recs = parse_pdf_metadata(f)
            for cp in {r["_cp_key"] for r in recs if r["_cp_key"]}:
                cp_files.setdefault(cp, []).append(f.name)
            records.extend(recs)
        except Exception as e:
            bad.append(f"{f.name}: {e}")
    rows = []
    for rec in records:
        if rec.get("_no_growth"):     # no-growth markers are not isolate rows
            continue
        merged = {col: rec[col] for col in PDF_COLUMNS}
        merged["Clinic"] = rec.get("_clinic", "NA")
        merged["Gram reaction"] = gram_status(rec["Isolate"])
        merged["MALDI Score"] = "NA"
        rec_susc = rec.get("_susc", {})
        for abx in ALL_ABX:
            merged[abx] = rec_susc.get(abx, "NA")
        rows.append(merged)
    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if not df.empty:
        df = df.drop_duplicates(subset=["Lab Reference", "Isolate"], keep="first")
        df = df.sort_values(["Lab Reference", "Isolate"]).reset_index(drop=True)
    return df, bad, cp_files


def find_duplicate_uploads(cp_files, pdf_files):
    dupes = []
    for cp, files in sorted(cp_files.items()):
        if len(files) > 1:
            dupes.append(f"CP {cp} appears in {len(files)} uploaded files ({', '.join(sorted(set(files)))})")
    names = [f.name for f in pdf_files]
    for n in sorted({x for x in names if names.count(x) > 1}):
        if not any(n in fs and len(fs) > 1 for fs in cp_files.values()):
            dupes.append(f"File uploaded more than once: {n}")
    return dupes


# ============================================================================
# 9. EXCEL
# ============================================================================
def build_excel(df):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "AST Surveillance"
    cols = list(df.columns)
    abx_set = set(ALL_ABX)
    header_font = Font(bold=True, color="103A6B", size=11)
    header_border = Border(bottom=Side(style="medium", color="1D6FD6"))
    fill_map = {"S": "C6EFCE", "I": "FFEB9C", "R": "FFC7CE", "INTR": "BFE3F7"}
    typo_fill = PatternFill("solid", fgColor="FF2D2D")
    typo_font = Font(bold=True, color="FFFFFF")
    for j, name in enumerate(cols, 1):
        is_abx = name in abx_set
        header = ABX_FULL.get(name, name) if is_abx else ("Host species" if name == "Species" else name)
        c = ws.cell(1, j, header)
        c.font = header_font
        c.border = header_border
        if is_abx:   # full drug name, rotated so the sheet stays compact
            c.alignment = Alignment(text_rotation=90, horizontal="center", vertical="bottom")
        else:
            c.alignment = Alignment(horizontal="left", vertical="center")
    for i, (_, row) in enumerate(df.iterrows(), start=2):
        for j, name in enumerate(cols, 1):
            v = row[name]
            blank = v is None or (isinstance(v, float) and pd.isna(v))
            cell = ws.cell(i, j, "" if blank else v)
            if name in abx_set:
                cell.alignment = Alignment(horizontal="center")
                sval = "" if blank else str(v).strip()
                if sval in fill_map:
                    cell.fill = PatternFill("solid", fgColor=fill_map[sval])
                elif sval not in ("", "NA"):
                    cell.fill = typo_fill
                    cell.font = typo_font
    for j, name in enumerate(cols, 1):
        letter = ws.cell(1, j).column_letter
        if name in abx_set:
            ws.column_dimensions[letter].width = 5.2
        else:
            longest = max([len(str(name))] + df[name].astype(str).map(len).tolist())
            ws.column_dimensions[letter].width = min(max(longest + 2, 10), 34)
    abx_hdr_len = max([len(ABX_FULL.get(a, a)) for a in abx_set if a in cols] + [0])
    ws.row_dimensions[1].height = min(max(abx_hdr_len * 6.2, 22), 215)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============================================================================
# 10. SIDEBAR
# ============================================================================
with st.sidebar:
    st.markdown(f"<h3 style='color:{BLUE_800};font-size:1.3rem;font-weight:800;margin-bottom:0.5rem;'>User guide</h3>",
                unsafe_allow_html=True)
    st.markdown(
        "Run it with either:\n\n"
        "1. Reports on their own\n"
        "2. Reports + AST sheet: matched on CP and isolate, cross-checked, and susceptibility added\n\n"
        "Then download the master sheet.")
    st.divider()
    st.markdown(f"<h3 style='color:{BLUE_800};font-size:1.3rem;font-weight:800;margin-bottom:0.5rem;'>Susceptibility key</h3>",
                unsafe_allow_html=True)
    st.markdown(
        f"<div style='color:{INK};font-size:0.98rem;line-height:2.1;'>"
        f"<span class='legend-chip' style='background:#C6EFCE;'></span>Susceptible (S)<br>"
        f"<span class='legend-chip' style='background:#FFEB9C;'></span>Intermediate (I)<br>"
        f"<span class='legend-chip' style='background:#FFC7CE;'></span>Resistant (R)<br>"
        f"<span class='legend-chip' style='background:#BFE3F7;'></span>Intrinsic (INTR)<br>"
        f"<span class='legend-chip' style='background:#FF2D2D;'></span>Check entry</div>",
        unsafe_allow_html=True)

# ============================================================================
# 11. MAIN
# ============================================================================
_logo = logo_data_uri()
_logo_tag = f"<img src='{_logo}' class='amr-logo' alt='University of Sydney'/>" if _logo else ""
st.markdown(
    "<div class='amr-hero'>"
    + _logo_tag +
    "<span class='amr-eyebrow'>Sydney School of Veterinary Science</span>"
    "<h1>AST Surveillance Pipeline</h1>"
    "</div>",
    unsafe_allow_html=True)

tab1, tab2 = st.tabs(["Master sheet", "Analytics"])

with tab1:
    with st.container(border=True):
        section("Upload sources")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**AST logging sheet (Excel)**")
            ast_file = st.file_uploader("AST logging sheet", type=["xlsx"], label_visibility="collapsed")
        with c2:
            st.markdown("**PDF reports**")
            pdf_files = st.file_uploader("PDF reports", type=["pdf"], accept_multiple_files=True,
                                         label_visibility="collapsed")
        run = st.button("Process")

    if run:
        if not pdf_files:
            st.error("Upload the PDF reports. Add the AST logging sheet as well to cross-check and add susceptibility.")
        else:
            pdf_records, bad, cp_files, no_cp = [], [], {}, []
            total = len(pdf_files)
            pb = st.progress(0.0, text=f"Reading reports (0/{total})…")
            for i, f in enumerate(pdf_files):
                pb.progress(i / total, text=f"Reading ({i + 1}/{total}): {f.name}")
                try:
                    recs = parse_pdf_metadata(f)
                    for cp in {r["_cp_key"] for r in recs if r["_cp_key"]}:
                        cp_files.setdefault(cp, []).append(f.name)
                    if recs and not any(r["_cp_key"] for r in recs):
                        no_cp.append(f.name)
                    pdf_records.extend(recs)
                except Exception as e:
                    bad.append(f"{f.name}: {e}")
            pb.progress(0.8, text="Reports read. Building the master table…")
            dupes = find_duplicate_uploads(cp_files, pdf_files)
            # Reports with no isolate (no growth): listed so the case count adds up.
            no_growth = sorted({f'{r["Lab Reference"]} ({r["_no_growth"]})'
                                for r in pdf_records if r.get("_no_growth")})

            if ast_file:
                # ---- Reports cross-checked against the AST sheet ----
                ast_lookup = build_ast_lookup(ast_file)
                final_df, not_in_sheet, name_diff, discrepancies = build_dataframe(pdf_records, ast_lookup)
                if final_df.empty:
                    st.warning("No isolates matched between the PDF(s) and the AST sheet. Check the CP numbers and isolate names line up.")
                else:
                    pb.progress(0.9, text="Preparing the Excel file (this can take a few seconds for large batches)…")
                    xlsx = build_excel(final_df)
                    pb.progress(1.0, text="Done. Opening results…")
                    st.session_state.update(processed_data=final_df, skipped=not_in_sheet, name_diff=name_diff,
                                            bad=bad, dupes=dupes, discrepancies=discrepancies, no_cp=no_cp,
                                            no_growth=no_growth, excel_bytes=xlsx, mode="matched")
            else:
                # ---- Reports only ----
                final_df, bad2, _ = build_from_pdf_only(pdf_files)
                bad = bad + [b for b in bad2 if b not in bad]
                if final_df.empty:
                    st.warning("No isolates could be read from the uploaded reports.")
                else:
                    pb.progress(0.9, text="Preparing the Excel file (this can take a few seconds for large batches)…")
                    xlsx = build_excel(final_df)
                    pb.progress(1.0, text="Done. Opening results…")
                    st.session_state.update(processed_data=final_df, skipped=[], name_diff=[], bad=bad,
                                            excel_bytes=xlsx,
                                            dupes=dupes, discrepancies=[], no_cp=no_cp,
                                            no_growth=no_growth, mode="pdf")

    if 'processed_data' in st.session_state:
        final_df = st.session_state['processed_data']
        mode = st.session_state.get('mode', 'matched')

        mode_msg = {
            "matched": "Reports cross-checked against the AST sheet, matched on CP number and isolate. "
                       "Matched isolates take susceptibility, clinic and MALDI from the sheet; any report "
                       "not in the sheet keeps the susceptibility read from the report itself.",
            "pdf": "Built from the PDF reports only. Susceptibility is read from each report's own "
                   "susceptibility table; clinic and MALDI are not in the reports.",
        }.get(mode, "")
        if mode_msg:
            st.markdown(f"<div class='mode-note'>{mode_msg}</div>", unsafe_allow_html=True)

        with st.container(border=True):
            section("Master dataset")
            preview = final_df.copy()
            preview.index = range(1, len(preview) + 1)
            abx_present = [c for c in ALL_ABX if c in preview.columns]
            rename_map = {c: ABX_FULL.get(c, c) for c in abx_present}
            rename_map["Species"] = "Host species"
            preview = preview.rename(columns=rename_map)
            subset_full = [ABX_FULL.get(c, c) for c in abx_present]
            st.dataframe(preview.style.map(cell_css, subset=subset_full), use_container_width=True)
            aus_time = datetime.now(timezone.utc) + timedelta(hours=10)
            fname = f"AST_Surveillance_{aus_time.strftime('%Y%m%d')}.xlsx"
            xlsx = st.session_state.get("excel_bytes") or build_excel(final_df)
            st.download_button("Download master Excel", xlsx, fname,
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # ---- Flags and checks: kept below the table so the top stays uncluttered ----
        if st.session_state.get('dupes'):
            render_callout("Possible duplicate uploads", st.session_state['dupes'],
                           "#d99000", "#FBF1D6", ordered=False)

        if st.session_state.get('no_cp'):
            render_callout("No CP number found (shown as NA; check these reports)",
                           sorted(st.session_state['no_cp']), "#d99000", "#FBF1D6", ordered=False)

        if st.session_state.get('no_growth'):
            ng = st.session_state['no_growth']
            render_callout(f"Reports with no isolate, not in the table ({len(ng)})",
                           ng, "#6c6b6a", "#EEEAE6", ordered=False)

        if st.session_state.get('discrepancies'):
            render_callout("Report and AST sheet disagree (check these)", st.session_state['discrepancies'],
                           "#c77f00", "#F7EAD2", ordered=False)

        # Grouped review lists from the final table.
        typo_map, intr_map = {}, {}
        for _, r in final_df.iterrows():
            key = f'{r["Lab Reference"]}: {r["Isolate"]}'
            for abx in ALL_ABX:
                v = r[abx]
                if v == "INTR":
                    intr_map.setdefault(key, []).append(abx)
                elif v not in ("S", "I", "R", "INTR", "NA", "", None) and not (isinstance(v, float) and pd.isna(v)):
                    typo_map.setdefault(key, []).append(f"{abx} = {v}")

        if typo_map:
            items = [f"{k} ({', '.join(vs)})" for k, vs in sorted(typo_map.items())]
            render_callout("Isolates to check (unexpected antibiotic values)", items, "#FF2D2D", "#FFE4E4")

        if intr_map:
            items = [f"{k} ({', '.join(vs)})" for k, vs in sorted(intr_map.items())]
            render_callout("Isolates with intrinsic results (INTR)", items, "#2f88e6", "#E4F1FC")

        name_diff = st.session_state.get('name_diff')
        if name_diff:
            render_callout("CP is in the sheet but the isolate name differs (susceptibility from the report; check naming)",
                           sorted(name_diff), "#d99000", "#FBF1D6", ordered=False)

        skipped = st.session_state.get('skipped')
        if skipped:
            render_callout("Reports not yet in the AST sheet (susceptibility read from the report)", sorted(skipped),
                           "#6c6b6a", "#EEEAE6", ordered=False)

        if st.session_state.get('bad'):
            for b in st.session_state['bad']:
                st.error(b)

with tab2:
    if 'processed_data' not in st.session_state:
        st.info("Process data in the first tab to unlock analytics.")
    else:
        df = st.session_state['processed_data'].copy()
        clean = df[~df["Isolate"].isin(["nan", "NA", "Na", ""])]

        # KPI strip
        k1, k2, k3 = st.columns(3)
        k1.markdown(f"<div class='kpi kpi-total'><div class='kpi-body'><div class='kpi-num'>{len(clean)}</div>"
                    f"<div class='kpi-lab'>Total isolates</div></div></div>", unsafe_allow_html=True)
        k2.markdown(f"<div class='kpi'><div class='kpi-body'><div class='kpi-num'>{clean['Lab Reference'].nunique()}</div>"
                    f"<div class='kpi-lab'>Unique clinical cases</div></div></div>", unsafe_allow_html=True)
        k3.markdown(f"<div class='kpi'><div class='kpi-body'><div class='kpi-num'>{clean['Isolate'].nunique()}</div>"
                    f"<div class='kpi-lab'>Unique bacteria types</div></div></div>", unsafe_allow_html=True)
        st.write("")

        # Bacterial species distribution
        with st.container(border=True):
            section("Bacterial species distribution")
            counts = clean["Isolate"].value_counts().sort_values(ascending=True)
            y_cats, x_vals = counts.index.tolist(), [int(v) for v in counts.values]
            fig = go.Figure(go.Bar(orientation="h", y=y_cats, x=x_vals, marker_color=BLUE_600,
                marker_line_width=0, text=x_vals, textposition="outside",
                textfont=dict(size=16, color=INK), cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>Isolates: %{x}<extra></extra>"))
            style_fig(fig, max(340, 40 * len(y_cats)), bottom=30)
            set_titles(fig, "<b>Number of isolates</b>", "")
            fig.update_xaxes(range=[0, (max(x_vals) if x_vals else 1) * 1.18])
            st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # Resistance profile (cumulative antibiogram): per organism, and all combined
        sir_cols = [c for c in ALL_ABX if c in df.columns and df[c].isin(['S', 'I', 'R']).any()]
        if sir_cols:
            long_all = df[["Isolate"] + sir_cols].melt(
                id_vars=["Isolate"], var_name="ABx", value_name="Res")
            long_all = long_all[long_all["Res"].isin(["S", "I", "R"])]
            long_all["Res"] = long_all["Res"].map({'S': 'Susceptible', 'I': 'Intermediate', 'R': 'Resistant'})

            def resistance_figure(long_sub):
                ct = long_sub.groupby(['ABx', 'Res']).size().unstack(fill_value=0)
                for c in ['Resistant', 'Intermediate', 'Susceptible']:
                    if c not in ct.columns:
                        ct[c] = 0
                ct['n'] = ct[['Resistant', 'Intermediate', 'Susceptible']].sum(axis=1)
                ct = ct[ct['n'] > 0]
                if ct.empty:
                    return None
                pct = ct[['Resistant', 'Intermediate', 'Susceptible']].div(ct['n'], axis=0) * 100
                order_cats = pct['Resistant'].sort_values(ascending=True).index.tolist()
                labels = [f"{ABX_FULL.get(a, a)}  ·  n={int(ct.loc[a, 'n'])}" for a in order_cats]
                org_map = {}
                for (a, r), grp in long_sub.groupby(['ABx', 'Res'])['Isolate']:
                    vc = grp.value_counts()
                    org_map[(a, r)] = "<br>".join(f"{name} ×{c}" if c > 1 else name for name, c in vc.items())
                fig = go.Figure()
                for res in ["Resistant", "Intermediate", "Susceptible"]:
                    cdata = [[int(ct.loc[a, res]), org_map.get((a, res), "")] for a in order_cats]
                    fig.add_bar(orientation="h", y=labels,
                        x=[round(pct.loc[a, res], 1) for a in order_cats], name=res,
                        marker_color=SIR_CMAP[res], marker_line=dict(color="white", width=1),
                        customdata=cdata,
                        hovertemplate="<b>%{y}</b><br>" + res + ": %{x:.0f}% (%{customdata[0]} isolates)"
                                      "<br>%{customdata[1]}<extra></extra>")
                style_fig(fig, max(300, 28 * len(order_cats) + 70), bottom=40)
                fig.update_layout(barmode="stack",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title="",
                                font=dict(size=14, color=INK)))
                set_titles(fig, "<b>Percentage of isolates tested (%)</b>", "")
                fig.update_xaxes(range=[0, 100], ticksuffix="%")
                return fig

            # One organism at a time (cumulative antibiogram), defaulting to S. pseudintermedius.
            with st.container(border=True):
                section("Resistance profile by organism")
                orgs = sorted(long_all["Isolate"].unique())
                if orgs:
                    default = next((o for o in orgs if "pseudintermedius" in o.lower()), orgs[0])
                    pick = st.selectbox("Organism", orgs, index=orgs.index(default), key="abx_org")
                    fig_o = resistance_figure(long_all[long_all["Isolate"] == pick])
                    if fig_o is None:
                        st.info("No susceptibility results for this organism yet.")
                    else:
                        st.plotly_chart(fig_o, use_container_width=True)
                else:
                    st.info("No susceptibility results yet.")

            st.divider()

            # All organisms pooled, as a high-level overview.
            with st.container(border=True):
                section("Resistance profile: all organisms combined")
                fig_all = resistance_figure(long_all)
                if fig_all is None:
                    st.info("No susceptibility results yet.")
                else:
                    st.plotly_chart(fig_all, use_container_width=True)
            st.divider()
        else:
            st.info("No susceptibility results to profile. Add the AST logging sheet to see resistance by antibiotic.")
            st.divider()

        def _org_breakdown(frame, top=6):
            """Organisms found in a chart slice, as a hover list with counts."""
            vc = frame["Isolate"].value_counts()
            items = [f"{name} ({int(c)})" for name, c in vc.items()][:top]
            if len(vc) > top:
                items.append(f"+{len(vc) - top} more")
            return "<br>".join(items) if items else "—"

        # Sample site distribution
        with st.container(border=True):
            section("Sample site distribution")
            clean_sites = df[~df["Site"].isin(["nan", "NA", "Na", ""])]
            s_counts = clean_sites["Site"].value_counts().sort_values(ascending=True)
            ys, xs = s_counts.index.tolist(), [int(v) for v in s_counts.values]
            s_cust = [[_org_breakdown(clean_sites[clean_sites["Site"] == site])] for site in ys]
            figs = go.Figure(go.Bar(orientation="h", y=ys, x=xs, marker_color=BLUE_500,
                marker_line_width=0, text=xs, textposition="outside",
                textfont=dict(size=16, color=INK), cliponaxis=False, customdata=s_cust,
                hovertemplate="<b>%{y}</b><br>Isolates: %{x}"
                              "<br><br><b>Organisms found</b><br>%{customdata[0]}<extra></extra>"))
            style_fig(figs, max(300, 44 * len(ys)), bottom=30)
            set_titles(figs, "<b>Number of isolates</b>", "")
            figs.update_xaxes(range=[0, (max(xs) if xs else 1) * 1.2])
            st.plotly_chart(figs, use_container_width=True)

        st.divider()

        # Breed prevalence (horizontal bars, one chart per host species)
        with st.container(border=True):
            section("Breed prevalence by host species", "One count per animal.")
            unique_demo = clean.drop_duplicates(subset=['Lab Reference'])
            host_species = [s for s in unique_demo["Species"].unique() if s not in ("NA", "nan")]
            if host_species:
                for host in host_species:
                    sub = unique_demo[unique_demo["Species"] == host]
                    b_counts = sub["Breed"].value_counts().sort_values(ascending=True)
                    yb = b_counts.index.tolist()
                    xb = [int(v) for v in b_counts.values]
                    b_cust = [[_org_breakdown(clean[(clean["Species"] == host) &
                                                    (clean["Breed"] == breed)])] for breed in yb]
                    st.markdown(
                        f"<div style='color:{BLUE_800};font-size:1.05rem;font-weight:800;"
                        f"margin:0.5rem 0 0.15rem;'>{host} breeds "
                        f"<span style='font-weight:600;'>({len(sub)} animals)</span></div>",
                        unsafe_allow_html=True)
                    figb = go.Figure(go.Bar(orientation="h", y=yb, x=xb, marker_color=BLUE_800,
                        marker_line_width=0, text=xb, textposition="outside",
                        textfont=dict(size=16, color=INK), cliponaxis=False, customdata=b_cust,
                        hovertemplate="<b>%{y}</b><br>Animals: %{x}"
                                      "<br><br><b>Organisms found</b><br>%{customdata[0]}<extra></extra>"))
                    style_fig(figb, max(180, 40 * len(yb)) + 10, bottom=30)
                    set_titles(figb, "<b>Number of animals</b>", "")
                    figb.update_xaxes(range=[0, (max(xb) if xb else 1) * 1.2], dtick=1)
                    figb.update_yaxes(type="category", tickmode="linear", automargin=True)
                    st.plotly_chart(figb, use_container_width=True)
            else:
                st.info("No host-species demographic data available.")
