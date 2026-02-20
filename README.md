# Laura Geller — International Performance Dashboard

A Streamlit dashboard that reads the **Daily 2026** Google Sheet and displays
international website performance data (revenue, new customers, ad spend, CAC,
and more) with interactive filters, charts, and a downloadable data table.

---

## Project structure

```
dashboard/
├── app.py                        # Main Streamlit app
├── data_loader.py                # Sheet reader & parser
├── requirements.txt
├── README.md
└── .streamlit/
    ├── config.toml               # Dark theme + server settings
    ├── secrets.toml              # ← YOU CREATE THIS (not committed)
    └── secrets.toml.example      # Template
```

---

## Local setup

### 1. Prerequisites

- Python 3.11+
- A Google Cloud service account JSON key with access to the sheet

### 2. Install dependencies

```bash
cd dashboard
pip install -r requirements.txt
```

### 3. Create `.streamlit/secrets.toml`

Copy the example file and fill in your values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml`:

```toml
sheet_url = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "abc123"
private_key = "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
client_email = "your-sa@your-project.iam.gserviceaccount.com"
client_id = "123456789"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-sa%40your-project.iam.gserviceaccount.com"
```

**Tip:** You can copy all fields directly from your downloaded service account
JSON file.  The `private_key` field must preserve the literal `\n` newline
escapes — most editors handle this automatically when you paste.

### 4. Share the Google Sheet

In Google Sheets → Share, add the service account email
(`client_email` from your JSON) as a **Viewer**.

### 5. Run locally

```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser.

---

## Deploy to Streamlit Cloud

1. Push this `dashboard/` folder to a GitHub repository (ensure
   `secrets.toml` is in `.gitignore`).

2. Go to [share.streamlit.io](https://share.streamlit.io) and click
   **New app**.

3. Select your repo, branch, and set **Main file path** to `app.py`
   (or `dashboard/app.py` if the repo root is the parent folder).

4. Click **Advanced settings → Secrets** and paste the full contents of
   your `secrets.toml` there.

5. Deploy.  Streamlit Cloud will install `requirements.txt` automatically.

---

## Secrets reference

| Key | Description |
|-----|-------------|
| `sheet_url` | Full URL of the Google Sheet (must include `/edit` or just the base URL) |
| `gcp_service_account.*` | All fields from the service account JSON key |

---

## Data refresh

The sheet is read once per hour (TTL = 3600 s via `st.cache_data`).
Use the **Refresh data** button in the sidebar to force an immediate reload.

---

## Adding the sheet URL at test time

When you are ready to test locally, the quickest way is to run:

```bash
streamlit run app.py
```

…then open the app.  If `sheet_url` is missing from secrets you will see
an error banner with instructions.

Alternatively, export it as an environment variable for a quick test
(not recommended for production):

```bash
# bash / zsh
STREAMLIT_SECRETS_sheet_url="https://..." streamlit run app.py
```
