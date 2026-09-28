# AMR National Surveillance Pipeline

A browser based tool that turns veterinary pathology PDF reports and the laboratory AST logging spreadsheet into a single, clean, de-identified antimicrobial resistance (AMR) surveillance dataset, with an analytics dashboard on top. It forms part of the AMR National Surveillance program at the School of Veterinary Science, University of Sydney. Built with Streamlit and deployed on Azure App Service.

## What it does

The app takes two inputs and produces one master dataset:

1. **PDF laboratory reports** provide the case metadata: arrival and report dates, laboratory reference (CP number), species, breed, age, sex, neutered status, sample type and site, purity, and the bacterial isolate identified.
2. **The AST LOGGING spreadsheet** provides the antimicrobial susceptibility results (S, I, R or INTR) for each isolate, along with the clinic and the MALDI-TOF confidence score.

The two are matched by CP number and isolate name, merged into one row per isolate, and returned as a colour coded master sheet that can be downloaded as Excel.

## Key features

- **Automatic de-identification.** Patient and owner names and other identifying text are removed using spaCy named entity recognition before anything is stored or displayed.
- **Antibiotic result handling.** Each antibiotic cell reads S, I, R or INTR (intrinsic). Where the measurement cell records INTR, the app records INTR directly rather than the adjacent interpretation. Any value that is not S, I, R or INTR is highlighted so data entry slips can be found and checked.
- **Gram classification.** Each isolate is classified as Gram positive or Gram negative from its genus, using curated genus lists. Fungi, wall-less organisms and Gram-variable organisms are handled separately.
- **Deduplication.** Isolates with an identical susceptibility profile from the same case are reported once. If any antibiotic result differs, both are kept.
- **Review lists.** After processing, the app lists duplicated uploads, isolates with unexpected antibiotic values, isolates with intrinsic results, and isolates with no matching AST row.
- **Analytics dashboard.** Species distribution, resistance profile by antibiotic split by Gram stain, sample site distribution, and breed prevalence by host species.
- **Excel export.** The master sheet downloads as a formatted Excel file with the susceptibility colours preserved.

## Repository structure

```
amr_resistance/
├── app.py               # Main Streamlit application (all processing and UI)
├── startup.sh           # Azure startup command (runs Streamlit on port 8000)
├── requirements.txt     # Python dependencies
├── usyd_logo_white.png  # Logo used in the app header
└── README.md
```

## Running the app

The app runs as a hosted web application on Microsoft Azure App Service (Linux, Python 3.11). It is not run locally for normal use; you open the deployed Azure URL in a browser, upload the AST LOGGING spreadsheet and the matching PDF report(s), and process.

Deployment is automatic: pushing to the `main` branch of this repository triggers a GitHub Actions workflow that builds and deploys the app to Azure. Azure App Service on Linux serves on port 8000, so `startup.sh` runs:

```
python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0
```

The startup command in the App Service configuration is set to `bash startup.sh`.

### Optional: local development

For development only, the app can also be run locally:

```
pip install -r requirements.txt
streamlit run app.py
```

## Data and privacy

Input reports contain identifiable patient information. The pipeline removes identifying text during processing, and only de-identified, aggregated data is retained in the master sheet. Please treat all input files as confidential and do not commit real report PDFs or the AST logging spreadsheet to this repository.

## Author

Camila Calahorrano Aguilar, Research Assistant, School of Veterinary Science, University of Sydney. Supervised by Dr Kate Worthing and Jie Kang.
