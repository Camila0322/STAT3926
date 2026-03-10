import streamlit as st
import pdfplumber
import spacy
import pandas as pd
import re
import io
import os

# 1. THIS MUST BE THE FIRST STREAMLIT COMMAND
st.set_page_config(page_title="AMR Data Extractor", layout="wide")

# Cache the NLP model so it only loads once per session
@st.cache_resource
def load_nlp():
    return spacy.load("en_core_web_sm")
nlp = load_nlp()

def redact_text(text):
    """Identifies and redacts human names and locations to ensure privacy."""
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "GPE", "LOC"]: 
            text = text.replace(ent.text, "[REDACTED]")
    return text

def standardize_age(age_string):
    """Converts varied ages into 'X Years X Months' format."""
    if not age_string: return "NA"
    
    years, months = 0, 0
    year_match = re.search(r'(\d+)\s*(y|year|years)', age_string, re.IGNORECASE)
    if year_match: years = int(year_match.group(1))
        
    month_match = re.search(r'(\d+)\s*(m|month|months)', age_string, re.IGNORECASE)
    if month_match: months = int(month_match.group(1))
        
    if years == 0 and months == 0: return age_string 
    return f"{years} Years {months} Months"

def parse_pdf_report(file_object):
    """Extracts metadata, purity, and S/I/R results from a PDF file."""
    extracted_data = []
    
    with pdfplumber.open(file_object) as pdf:
        # Extract raw text first to protect animal breeds from accidental redaction
        full_text = "".join(page.extract_text() + "\n" for page in pdf.pages)
        
        # --- Metadata Regex (Run on un-redacted text) ---
        # Fixed: Captures full reference including space (e.g., CP 26-00756)
        lab_ref = re.search(r'Our Ref:\s*([A-Z0-9]+\s*[\d\-]+|[A-Z0-9\-]+)', full_text)
        lab_ref_val = lab_ref.group(1).strip() if lab_ref else "NA"
        
        # Bounded regex stops capturing when it hits Gender, Age, or "Our Ref"
        species_breed = re.search(r'(Canine|Feline)\s+([a-zA-Z\s\-]+?)(?=\s+(?:Male|Female|\d+\s*Years?|Our Ref|Your Ref|$))', full_text, re.IGNORECASE)
        species_val = species_breed.group(1).strip() if species_breed else "NA"
        
        # Fixed: .strip(" -") removes leading/trailing hyphens from the breed
        breed_val = species_breed.group(2).strip(" -") if species_breed else "NA"
        
        age_raw = re.search(r'(\d+\s*Years?)', full_text)
        age_val = standardize_age(age_raw.group(1)) if age_raw else "NA"
        
        gender_raw = re.search(r'(Male Neutered|Female Spayed|Male|Female)', full_text)
        sex_val = "NA"
        neutered_val = "NA"
        
        if gender_raw:
            gender_str = gender_raw.group(1)
            if "Male" in gender_str: sex_val = "Male"
            elif "Female" in gender_str: sex_val = "Female"
                
            if "Neutered" in gender_str or "Spayed" in gender_str: neutered_val = "Yes"
            else: neutered_val = "No"
        
        # --- Text Redaction applied AFTER metadata extraction ---
        safe_text = redact_text(full_text)
        
        sample_site = re.search(r'Swab:\s*(.+)', safe_text)
        sample_site_val = sample_site.group(1).strip() if sample_site else "NA"

        # --- Isolate Chunking & Purity Logic ---
        isolate_pattern = r'\d+\.\s*(?:Heavy|Moderate|Light)\s*growth\s*-\s*([^\n]+)'
        parts = re.split(isolate_pattern, safe_text)
        
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
                "Lab Name": "University of Sydney",
                "Lab Reference Number": lab_ref_val,
                "Animal Species": species_val,
                "Breed": breed_val,
                "Age": age_val,
                "Sex": sex_val,           
                "Neutered": neutered_val, 
                "Sample Type": "Swab", 
                "Sample Site": sample_site_val,
                "Purity": purity_val,
                "Bacterial Isolate Species": isolate_species,
            }
            
            for abx in antibiotics_to_check:
                match = re.search(rf'{re.escape(abx)}[^a-zA-Z]*([SIR])\b', isolate_text, re.IGNORECASE)
                if match:
                    record[abx] = match.group(1).upper()
                else:
                    record[abx] = "NA" 
                    
            extracted_data.append(record)

    return extracted_data

# --- Main Page UI ---
st.title("Antimicrobial Resistance Pipeline")
st.write("Extract metadata and susceptibility results from diagnostic PDFs. You can update an existing master sheet or generate a brand new one.")

# Create a clean side-by-side layout for the uploaders
col1, col2 = st.columns(2)

with col1:
    master_file = st.file_uploader("1. Upload Master Excel (Optional)", type=["xlsx"])
    if master_file:
        st.success("Master Excel loaded successfully.")
    else:
        st.info("Leave empty to generate a new Master File from scratch.")

with col2:
    uploaded_files = st.file_uploader("2. Upload PDF Reports", type=["pdf"], accept_multiple_files=True)

st.divider()

if st.button("Run Extraction Pipeline", type="primary"):
    if uploaded_files:
        processed_refs = set()
        master_df = pd.DataFrame()
        
        # Load existing Master Excel if provided
        if master_file is not None:
            master_df = pd.read_excel(master_file)
            if "Lab Reference Number" in master_df.columns:
                processed_refs = set(master_df["Lab Reference Number"].dropna().unique())
        else:
            st.toast("No existing master file detected. Creating a new one!")

        new_records = []
        skipped_files = []
        flagged_files = []

        with st.spinner(f"Scanning {len(uploaded_files)} PDF(s)..."):
            for file in uploaded_files:
                try:
                    records = parse_pdf_report(file)
                    
                    if not records:
                        flagged_files.append(file.name)
                        continue
                        
                    lab_ref = records[0].get("Lab Reference Number")
                    
                    if lab_ref in processed_refs:
                        skipped_files.append(file.name)
                    else:
                        new_records.extend(records)
                        processed_refs.add(lab_ref)
                        
                except Exception as e:
                    flagged_files.append(file.name)

            # Append, Style, and Export
            if new_records or not master_df.empty:
                
                # Combine dataframes
                if new_records:
                    new_df = pd.DataFrame(new_records)
                    updated_df = pd.concat([master_df, new_df], ignore_index=True) if not master_df.empty else new_df
                    if master_file is None:
                        st.success(f"Successfully generated a new master file with {len(new_records)} isolates.")
                    else:
                        st.success(f"Successfully appended {len(new_records)} new isolates.")
                else:
                    updated_df = master_df
                    st.info("No new records were added (all PDFs were duplicates or failed).")

                # Apply color styling
                def color_sri(val):
                    if val == 'S': return 'background-color: #C6EFCE; color: #006100'
                    elif val == 'I': return 'background-color: #FFEB9C; color: #9C5700'
                    elif val == 'R': return 'background-color: #FFC7CE; color: #9C0006'
                    return ''

                try:
                    styled_df = updated_df.style.map(color_sri) 
                except AttributeError:
                    styled_df = updated_df.style.applymap(color_sri) 
                
                # Show the preview on the webpage
                st.dataframe(styled_df, use_container_width=True)

                # Generate the downloadable Excel file in memory
                buffer = io.BytesIO()
                styled_df.to_excel(buffer, index=False, engine='openpyxl')
                
                st.download_button(
                    label="⬇️ Download Updated Master Excel",
                    data=buffer.getvalue(),
                    file_name="AMR_National_Surveillance_Master_Updated.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )
            else:
                st.info("No valid records to process or display.")

            # Show warnings for skipped or failed files
            if skipped_files:
                st.warning(f"Skipped {len(skipped_files)} file(s) because the Lab Reference Number is already in the master file: {', '.join(skipped_files)}")
                
            if flagged_files:
                st.error(f"Failed to read data from the following file(s): {', '.join(flagged_files)}")
    else:
        st.error("Please upload at least one PDF report to begin.")

