"""
send_report.py — Daily LG International Performance Email
Runs via GitHub Actions every morning at 8:30 AM ET.
"""

import json
import os
import re
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SHEET_URL      = os.environ["SHEET_URL"]
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
DASHBOARD_URL  = os.environ["DASHBOARD_URL"]
RECIPIENTS     = ["tbeyda@asbeauty.com", "mfriedman@asbeauty.com"]

SHEET_NAME = "Daily 2026"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
METRIC_SECTIONS = [
    ("Net Revenue + Shipping", 1,  10),
    ("Share %",                11, 19),
    ("Share of INT %",         20, 26),
    ("YoY #",                  27, 36),
    ("YoY %",                  37, 46),
    ("New Customers",          47, 56),
    ("Ad Spend",               57, 66),
    ("% of Ad Spend",          67, 76),
    ("CAC",                    77, 86),
]

# ---------------------------------------------------------------------------
# Google Sheets — standalone (no Streamlit)
# ---------------------------------------------------------------------------

def _get_client() -> gspread.Client:
    creds_dict = json.loads(os.environ["GCP_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _try_parse_date(value: str) -> Optional[date]:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d{4,6}", value):
        try:
            base = datetime(1899, 12, 30)
            return (base + pd.Timedelta(days=int(value))).date()
        except Exception:
            pass
    return None


def _parse_number(raw: str) -> Optional[float]:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or s in ("-", "—", "N/A", "n/a", "#DIV/0!", "#VALUE!", "#REF!"):
        return None
    s = s.replace("$", "").replace(",", "").replace(" ", "").replace("%", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def load_data() -> pd.DataFrame:
    client = _get_client()
    ws = client.open_by_url(SHEET_URL).worksheet(SHEET_NAME)
    all_values = ws.get_all_values()
    header = all_values[0]

    date_cols: dict[int, date] = {}
    in_dates = False
    for idx, cell in enumerate(header):
        parsed = _try_parse_date(cell)
        if parsed is not None:
            date_cols[idx] = parsed
            in_dates = True
        elif in_dates:
            break

    today = date.today()
    frames = []
    for metric_name, row_start, row_end in METRIC_SECTIONS:
        records = []
        for row in all_values[row_start:row_end + 1]:
            if not row:
                continue
            country = row[1].strip() if len(row) > 1 else ""
            if not country:
                continue
            for col_idx, col_date in date_cols.items():
                if col_date > today:
                    continue
                raw = row[col_idx] if col_idx < len(row) else ""
                value = _parse_number(raw)
                if value is None or value == 0.0:
                    continue
                records.append({"date": col_date, "country": country,
                                "metric_name": metric_name, "value": value})
        if records:
            frames.append(pd.DataFrame(records))

    if not frames:
        return pd.DataFrame(columns=["date", "country", "metric_name", "value"])

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = df["value"].astype(float)
    return df

# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _get(df, metric, countries, target_date, agg="sum") -> Optional[float]:
    mask = (
        (df["metric_name"] == metric)
        & df["country"].isin(countries)
        & (df["date"] == pd.Timestamp(target_date))
    )
    sub = df[mask]
    if sub.empty:
        return None
    return sub["value"].sum() if agg == "sum" else sub["value"].mean()


def _fmt_currency(v, scale=1):
    if v is None:
        return "—"
    v = v * scale
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:,.0f}"


def _fmt_pct(v):
    return f"{v:.1f}%" if v is not None else "—"


def _fmt_number(v):
    return f"{v:,.0f}" if v is not None else "—"


def _yoy_cell(cur, prev):
    if cur is None or prev is None or prev == 0:
        return '<span style="color:#6b6b8a">—</span>'
    pct = (cur - prev) / abs(prev) * 100
    arrow = "▲" if pct >= 0 else "▼"
    color = "#4ade80" if pct >= 0 else "#f87171"
    return f'<span style="color:{color};font-weight:600">{arrow} {abs(pct):.1f}%</span>'

# ---------------------------------------------------------------------------
# Build HTML email
# ---------------------------------------------------------------------------

def build_html(df: pd.DataFrame, report_date: date) -> str:
    ly_date = report_date.replace(year=report_date.year - 1)
    all_countries = df["country"].unique().tolist()
    int_ctry = [c for c in all_countries if c not in ("US", "Total", "Global Total", "International")]

    # Fetch metrics
    rev      = _get(df, "Net Revenue + Shipping", ["Total"], report_date)
    rev_ly   = _get(df, "Net Revenue + Shipping", ["Total"], ly_date)
    int_rev  = _get(df, "Net Revenue + Shipping", ["International"], report_date)
    tot_rev  = _get(df, "Net Revenue + Shipping", ["Total"], report_date)
    int_share = (int_rev / tot_rev * 100) if int_rev and tot_rev else None

    nc       = _get(df, "New Customers", ["Total", "Global Total"], report_date)
    nc_ly    = _get(df, "New Customers", ["Total", "Global Total"], ly_date)

    cac      = _get(df, "CAC", ["Total", "Global Total"], report_date, agg="mean")
    cac_ly   = _get(df, "CAC", ["Total", "Global Total"], ly_date, agg="mean")

    spend    = _get(df, "Ad Spend", ["Total", "Global Total"], report_date)
    if spend is None:
        spend = _get(df, "Ad Spend", int_ctry + ["US"], report_date)
    spend_ly = _get(df, "Ad Spend", ["Total", "Global Total"], ly_date)

    metrics = [
        ("Total Net Revenue",   _fmt_currency(rev, scale=1000), _yoy_cell(rev, rev_ly)),
        ("International Share", _fmt_pct(int_share),            '<span style="color:#6b6b8a">—</span>'),
        ("New Customers",       _fmt_number(nc),                _yoy_cell(nc, nc_ly)),
        ("Blended CAC",         _fmt_currency(cac),             _yoy_cell(cac, cac_ly)),
        ("Total Ad Spend",      _fmt_currency(spend, scale=1000), _yoy_cell(spend, spend_ly)),
    ]

    rows_html = ""
    for i, (label, value, yoy) in enumerate(metrics):
        bg = "#1e1e2e" if i % 2 == 0 else "#181828"
        rows_html += f"""
        <tr style="background:{bg}">
          <td style="padding:13px 20px;color:#a0a0b8;font-size:13px;border-bottom:1px solid #2a2a3e">{label}</td>
          <td style="padding:13px 20px;color:#ffffff;font-size:15px;font-weight:700;text-align:right;border-bottom:1px solid #2a2a3e">{value}</td>
          <td style="padding:13px 20px;font-size:13px;text-align:right;border-bottom:1px solid #2a2a3e">{yoy}</td>
        </tr>"""

    no_data_banner = ""
    if all(m[1] == "—" for m in metrics):
        no_data_banner = """
        <tr>
          <td colspan="3" style="padding:12px 20px;background:#2a1a1a;color:#f87171;font-size:12px;text-align:center">
            ⚠️ No data found for this date — the sheet may not yet be updated.
          </td>
        </tr>"""

    date_str = report_date.strftime("%A, %B %-d, %Y")

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px">
      <table width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%">

        <!-- Header -->
        <tr>
          <td style="background:#1e1e2e;border-radius:12px 12px 0 0;padding:28px 32px;border-bottom:1px solid #2e2e3e">
            <p style="margin:0;color:#7c3aed;font-size:11px;text-transform:uppercase;letter-spacing:2px;font-weight:600">Daily Performance Report</p>
            <h1 style="margin:6px 0 0;color:#ffffff;font-size:22px;font-weight:700">Laura Geller International</h1>
            <p style="margin:6px 0 0;color:#6b6b8a;font-size:13px">{date_str}</p>
          </td>
        </tr>

        <!-- Metrics table -->
        <tr>
          <td style="background:#16162a;padding:0">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr style="background:#12122a">
                <th style="padding:10px 20px;color:#6b6b8a;font-size:10px;text-transform:uppercase;letter-spacing:1px;text-align:left;font-weight:500">Metric</th>
                <th style="padding:10px 20px;color:#6b6b8a;font-size:10px;text-transform:uppercase;letter-spacing:1px;text-align:right;font-weight:500">Yesterday</th>
                <th style="padding:10px 20px;color:#6b6b8a;font-size:10px;text-transform:uppercase;letter-spacing:1px;text-align:right;font-weight:500">vs Prior Year</th>
              </tr>
              {no_data_banner}
              {rows_html}
            </table>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="background:#1e1e2e;border-radius:0 0 12px 12px;padding:28px 32px;text-align:center;border-top:1px solid #2e2e3e">
            <a href="{DASHBOARD_URL}"
               style="display:inline-block;background:#7c3aed;color:#ffffff;text-decoration:none;
                      padding:13px 32px;border-radius:8px;font-size:14px;font-weight:600;
                      letter-spacing:0.3px">
              Open Full Dashboard →
            </a>
            <p style="margin:18px 0 0;color:#6b6b8a;font-size:11px">
              Automated daily report · LG International Dashboard
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_email(html: str, report_date: date):
    subject = f"LG International Daily Report — {report_date.strftime('%b %-d, %Y')}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASSWORD)
        smtp.sendmail(GMAIL_USER, RECIPIENTS, msg.as_string())
    print(f"✓ Email sent to {RECIPIENTS} for {report_date}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    yesterday = date.today() - timedelta(days=1)
    print(f"Loading data for {yesterday}…")
    df = load_data()
    html = build_html(df, yesterday)
    send_email(html, yesterday)
