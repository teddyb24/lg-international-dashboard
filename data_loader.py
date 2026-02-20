"""
data_loader.py
Reads the "Daily 2026" Google Sheet and parses the wide matrix into a
tidy long-format DataFrame with columns: date, country, metric_name, value.

Sheet layout recap
------------------
Row 1      : headers — col A = "Metric", col B = "Country", col C onward = dates
             After the last date come summary cols: "2025 YTD", "2026 YTD",
             "YTD YoY #", "YTD YoY %"
Col A      : metric name (only on the first row of each section, rest blank)
Col B      : country name

Metric sections (1-indexed rows in the sheet):
  2–11   Net Revenue + Shipping
  12–20  Share %
  21–27  Share of INT %
  28–37  YoY #
  38–47  YoY %
  48–57  New Customers
  58–67  Ad Spend
  68–77  % of Ad Spend
  78–87  CAC
"""

import re
from datetime import datetime, date
from typing import Optional

import gspread
import numpy as np
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHEET_NAME = "Daily 2026"

# (metric_label, first_data_row_0indexed, last_data_row_0indexed)
# Rows are 0-indexed after we read all_values (row 0 = header row in sheet row 1)
METRIC_SECTIONS = [
    ("Net Revenue + Shipping", 1, 10),   # sheet rows 2–11
    ("Share %",                11, 19),  # sheet rows 12–20
    ("Share of INT %",         20, 26),  # sheet rows 21–27
    ("YoY #",                  27, 36),  # sheet rows 28–37
    ("YoY %",                  37, 46),  # sheet rows 38–47
    ("New Customers",          47, 56),  # sheet rows 48–57
    ("Ad Spend",               57, 66),  # sheet rows 58–67
    ("% of Ad Spend",          67, 76),  # sheet rows 68–77
    ("CAC",                    77, 86),  # sheet rows 78–87
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _get_gspread_client() -> gspread.Client:
    """Build an authenticated gspread client from Streamlit secrets."""
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# Sheet reading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner="Loading data from Google Sheets…")
def load_raw_data(sheet_url: str) -> pd.DataFrame:
    """
    Main entry point.  Returns a tidy DataFrame:
        date (datetime.date) | country (str) | metric_name (str) | value (float)
    Only rows with valid, non-zero values are included.
    """
    client = _get_gspread_client()
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = spreadsheet.worksheet(SHEET_NAME)

    all_values = worksheet.get_all_values()   # list of lists, strings

    date_cols = _parse_date_columns(all_values[0])   # {col_index: date}
    frames = []

    for metric_name, row_start, row_end in METRIC_SECTIONS:
        section_rows = all_values[row_start : row_end + 1]
        df = _parse_section(section_rows, metric_name, date_cols)
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["metric_name", "country", "date"]).reset_index(drop=True)
    return combined


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_date_columns(header_row: list[str]) -> dict[int, date]:
    """
    Walk the header row (index 0 = col A, 1 = col B, 2 = first date col).
    Return a dict mapping column index → datetime.date for every column that
    looks like a date.  Stop as soon as we hit a non-date column after the
    date range begins (the summary columns at the end).
    """
    date_cols: dict[int, date] = {}
    in_dates = False

    for idx, cell in enumerate(header_row):
        parsed = _try_parse_date(cell)
        if parsed is not None:
            date_cols[idx] = parsed
            in_dates = True
        elif in_dates:
            # First non-date after dates started → we've hit the summary cols
            break

    return date_cols


def _try_parse_date(value: str) -> Optional[date]:
    """Try several common date formats; return None if not a date."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    # Try numeric serial (Google Sheets sometimes exports as integer days since 1899-12-30)
    if re.fullmatch(r"\d{4,6}", value):
        try:
            serial = int(value)
            # Google Sheets epoch
            base = datetime(1899, 12, 30)
            return (base + pd.Timedelta(days=serial)).date()
        except Exception:
            pass
    return None


def _parse_section(
    rows: list[list[str]],
    metric_name: str,
    date_cols: dict[int, date],
) -> pd.DataFrame:
    """
    Given the raw rows for one metric section, return a long-format DataFrame.
    Each row in `rows` corresponds to one country.
    Col B (index 1) holds the country name.
    """
    today = date.today()
    records = []

    for row in rows:
        if not row:
            continue
        country = row[1].strip() if len(row) > 1 else ""
        if not country:
            continue

        for col_idx, col_date in date_cols.items():
            # Skip future dates — they'll have no data
            if col_date > today:
                continue

            raw = row[col_idx] if col_idx < len(row) else ""
            value = _parse_number(raw)

            if value is None or value == 0.0:
                continue  # skip empties and zeros

            records.append(
                {
                    "date": col_date,
                    "country": country,
                    "metric_name": metric_name,
                    "value": value,
                }
            )

    if not records:
        return pd.DataFrame(columns=["date", "country", "metric_name", "value"])

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = df["value"].astype(float)
    return df


def _parse_number(raw: str) -> Optional[float]:
    """
    Convert a raw cell string to float.
    Handles: commas, $ signs, % signs, parentheses for negatives, blank.
    """
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or s in ("-", "—", "N/A", "n/a", "#DIV/0!", "#VALUE!", "#REF!"):
        return None
    # Remove currency symbols and commas
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    # Handle percentage — keep as-is (e.g. "12.5%" → 12.5)
    s = s.replace("%", "")
    # Handle parentheses for negatives
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Convenience accessors used by app.py
# ---------------------------------------------------------------------------

def get_last_updated(df: pd.DataFrame) -> Optional[date]:
    """Return the most recent date that has data in the DataFrame."""
    if df.empty:
        return None
    return df["date"].max().date()


def get_metric_names(df: pd.DataFrame) -> list[str]:
    return sorted(df["metric_name"].unique().tolist())


def get_countries(df: pd.DataFrame) -> list[str]:
    return sorted(df["country"].unique().tolist())


def filter_data(
    df: pd.DataFrame,
    metrics: list[str],
    countries: list[str],
    start_date,
    end_date,
) -> pd.DataFrame:
    mask = (
        df["metric_name"].isin(metrics)
        & df["country"].isin(countries)
        & (df["date"] >= pd.Timestamp(start_date))
        & (df["date"] <= pd.Timestamp(end_date))
    )
    return df[mask].copy()


def get_summary_value(
    df: pd.DataFrame,
    metric: str,
    countries: list[str],
    start_date,
    end_date,
    aggregation: str = "sum",
) -> Optional[float]:
    """Return a single aggregated value for a metric/country/period combo."""
    sub = filter_data(df, [metric], countries, start_date, end_date)
    if sub.empty:
        return None
    if aggregation == "sum":
        return sub["value"].sum()
    if aggregation == "mean":
        return sub["value"].mean()
    if aggregation == "last":
        return sub.sort_values("date").iloc[-1]["value"]
    return None
