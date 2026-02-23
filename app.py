"""
app.py — Laura Geller International Website Performance Dashboard
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    filter_data,
    get_countries,
    get_last_updated,
    get_metric_names,
    get_summary_value,
    load_raw_data,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="LG International Dashboard",
    page_icon="💄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS tweaks (dark theme supplement)
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Metric card styling */
    [data-testid="metric-container"] {
        background-color: #1e1e2e;
        border: 1px solid #2e2e3e;
        border-radius: 8px;
        padding: 12px 16px;
    }
    /* Tighter section headers */
    h2 { margin-top: 0.5rem !important; }
    /* Make the sidebar slightly wider */
    [data-testid="stSidebar"] { min-width: 260px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

SHEET_URL = st.secrets.get("sheet_url", "")

if not SHEET_URL:
    st.error(
        "No `sheet_url` found in Streamlit secrets. "
        "Add it to `.streamlit/secrets.toml` (see README)."
    )
    st.stop()

try:
    df_all = load_raw_data(SHEET_URL)
except Exception as exc:
    st.error(f"Failed to load data: {exc}")
    st.stop()

if df_all.empty:
    st.warning("The sheet returned no data. Check the sheet URL and sharing permissions.")
    st.stop()

last_updated = get_last_updated(df_all)
all_countries = get_countries(df_all)
all_metrics = get_metric_names(df_all)

# ---------------------------------------------------------------------------
# Sidebar — Filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("💄 LG International")
    st.caption(f"Last data: **{last_updated}**" if last_updated else "No data yet")
    st.divider()

    # ── Date range ──────────────────────────────────────────────────────────
    st.subheader("Date Range")
    today = date.today()
    mtd_start = today.replace(day=1)

    date_preset = st.selectbox(
        "Quick select",
        ["Yesterday", "MTD", "Last 7 days", "Last 30 days", "Last 90 days", "YTD", "Custom"],
        index=0,
    )

    yesterday = today - timedelta(days=1)

    if date_preset == "Yesterday":
        default_start, default_end = yesterday, yesterday
    elif date_preset == "MTD":
        default_start, default_end = mtd_start, yesterday
    elif date_preset == "Last 7 days":
        default_start, default_end = yesterday - timedelta(days=6), yesterday
    elif date_preset == "Last 30 days":
        default_start, default_end = today - timedelta(days=29), today
    elif date_preset == "Last 90 days":
        default_start, default_end = today - timedelta(days=89), today
    elif date_preset == "YTD":
        default_start, default_end = date(today.year, 1, 1), today
    else:
        default_start, default_end = mtd_start, today

    if date_preset == "Custom":
        start_date = st.date_input("Start date", value=default_start)
        end_date = st.date_input("End date", value=default_end)
    else:
        start_date, end_date = default_start, default_end
        st.caption(f"{start_date} → {end_date}")

    st.divider()

    # ── Countries ────────────────────────────────────────────────────────────
    st.subheader("Countries")

    exclude_us = st.toggle("Hide US (dominates scale)", value=False)

    available_countries = [c for c in all_countries if not (exclude_us and c == "US")]

    selected_countries = st.multiselect(
        "Select countries",
        options=available_countries,
        default=available_countries,
    )

    if not selected_countries:
        st.warning("Select at least one country.")

    st.divider()

    # ── Metric ───────────────────────────────────────────────────────────────
    st.subheader("Primary Metric")
    selected_metric = st.selectbox("Metric", options=all_metrics, index=0)

    st.divider()

    # ── Chart mode ───────────────────────────────────────────────────────────
    chart_mode = st.radio("Chart view", ["Daily", "7-day Rolling Avg"], horizontal=True)

    st.divider()
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

st.title("🌍 Laura Geller — International Performance")

# Guard
if not selected_countries:
    st.info("Please select at least one country in the sidebar.")
    st.stop()

# Filtered frame for selected metric + countries + date range
df_filtered = filter_data(df_all, [selected_metric], selected_countries, start_date, end_date)

# ── Summary cards ────────────────────────────────────────────────────────────

def _fmt_currency(v):
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:,.0f}"

def _fmt_pct(v):
    if v is None:
        return "—"
    return f"{v:.1f}%"

def _fmt_number(v):
    if v is None:
        return "—"
    return f"{v:,.0f}"

def _yoy_delta(df: pd.DataFrame, metric: str, countries: list, start: date, end: date) -> str:
    """Compute YoY % change for the same period last year."""
    ly_start = start.replace(year=start.year - 1)
    ly_end = end.replace(year=end.year - 1)
    cur = get_summary_value(df, metric, countries, start, end)
    prev = get_summary_value(df, metric, countries, ly_start, ly_end)
    if cur is None or prev is None or prev == 0:
        return ""
    pct = (cur - prev) / abs(prev) * 100
    arrow = "▲" if pct >= 0 else "▼"
    return f"{arrow} {abs(pct):.1f}% YoY"

all_ctry = get_countries(df_all)
int_ctry = [c for c in all_ctry if c not in ("US", "Total", "Global Total")]

st.subheader("Summary")
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    rev = get_summary_value(df_all, "Net Revenue + Shipping", ["Total"], start_date, end_date)
    rev_display = rev * 1000 if rev is not None else None
    delta = _yoy_delta(df_all, "Net Revenue + Shipping", ["Total"], start_date, end_date)
    st.metric("Total Net Revenue", _fmt_currency(rev_display), delta=delta or None)

with c2:
    int_rev = get_summary_value(df_all, "Net Revenue + Shipping", ["International"], start_date, end_date)
    tot_rev = get_summary_value(df_all, "Net Revenue + Shipping", ["Total"], start_date, end_date)
    if int_rev is not None and tot_rev and tot_rev != 0:
        int_share = int_rev / tot_rev * 100
        int_share_str = _fmt_pct(int_share)
    else:
        int_share_str = "—"
    st.metric("International Share %", int_share_str)

with c3:
    nc = get_summary_value(df_all, "New Customers", ["Total", "Global Total"], start_date, end_date)
    # Try Global Total if Total not present
    if nc is None:
        nc = get_summary_value(df_all, "New Customers", int_ctry + ["US"], start_date, end_date)
    delta_nc = _yoy_delta(df_all, "New Customers", ["Total", "Global Total"], start_date, end_date)
    st.metric("Total New Customers", _fmt_number(nc), delta=delta_nc or None)

with c4:
    cac = get_summary_value(df_all, "CAC", ["Total", "Global Total"], start_date, end_date, aggregation="mean")
    st.metric("Blended CAC", _fmt_currency(cac))

with c5:
    spend = get_summary_value(df_all, "Ad Spend", ["Total", "Global Total"], start_date, end_date)
    if spend is None:
        spend = get_summary_value(df_all, "Ad Spend", int_ctry + ["US"], start_date, end_date)
    spend_display = spend * 1000 if spend is not None else None
    delta_spend = _yoy_delta(df_all, "Ad Spend", ["Total", "Global Total"], start_date, end_date)
    st.metric("Total Ad Spend", _fmt_currency(spend_display), delta=delta_spend or None)

st.divider()

# ── Main line chart ──────────────────────────────────────────────────────────

st.subheader(f"{selected_metric} — Trend")

if df_filtered.empty:
    st.info("No data for the selected filters.")
else:
    pivot = (
        df_filtered.groupby(["date", "country"])["value"]
        .sum()
        .reset_index()
        .sort_values("date")
    )

    if chart_mode == "7-day Rolling Avg":
        pivot = pivot.sort_values(["country", "date"])
        pivot["value"] = (
            pivot.groupby("country")["value"]
            .transform(lambda s: s.rolling(7, min_periods=1).mean())
        )
        chart_title = f"{selected_metric} (7-day rolling avg)"
    else:
        chart_title = f"{selected_metric} (daily)"

    fig_line = px.line(
        pivot,
        x="date",
        y="value",
        color="country",
        title=chart_title,
        labels={"value": selected_metric, "date": "Date", "country": "Country"},
        template="plotly_dark",
    )
    fig_line.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=60, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig_line, use_container_width=True)

st.divider()

# ── Country comparison + International breakdown ─────────────────────────────

col_bar, col_pie = st.columns([3, 2])

with col_bar:
    st.subheader(f"{selected_metric} — Country Comparison")

    if df_filtered.empty:
        st.info("No data.")
    else:
        agg = (
            df_filtered.groupby("country")["value"]
            .sum()
            .reset_index()
            .sort_values("value", ascending=True)
        )
        fig_bar = px.bar(
            agg,
            x="value",
            y="country",
            orientation="h",
            title=f"Total {selected_metric} by Country ({start_date} – {end_date})",
            labels={"value": selected_metric, "country": "Country"},
            template="plotly_dark",
            color="value",
            color_continuous_scale="Teal",
        )
        fig_bar.update_layout(
            coloraxis_showscale=False,
            margin=dict(t=60, b=20),
            yaxis_title=None,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

with col_pie:
    st.subheader("International Breakdown")

    int_breakdown_df = filter_data(
        df_all,
        ["Share of INT %"],
        [c for c in get_countries(df_all) if c not in ("Total", "Global Total", "US", "International")],
        start_date,
        end_date,
    )

    if int_breakdown_df.empty:
        # Fallback: use Net Revenue for non-US countries
        int_breakdown_df = filter_data(
            df_all,
            ["Net Revenue + Shipping"],
            int_ctry,
            start_date,
            end_date,
        )

    if int_breakdown_df.empty:
        st.info("No international breakdown data.")
    else:
        pie_agg = (
            int_breakdown_df.groupby("country")["value"]
            .sum()
            .reset_index()
        )
        fig_pie = px.pie(
            pie_agg,
            names="country",
            values="value",
            hole=0.45,
            title="Share of International",
            template="plotly_dark",
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(
            showlegend=False,
            margin=dict(t=60, b=20, l=20, r=20),
        )
        st.plotly_chart(fig_pie, use_container_width=True)

st.divider()

# ── Raw data table ────────────────────────────────────────────────────────────

st.subheader("Raw Data Table")

if df_filtered.empty:
    st.info("No data for the selected filters.")
else:
    table_df = (
        df_filtered[["date", "country", "metric_name", "value"]]
        .sort_values(["date", "country"])
        .copy()
    )
    table_df["date"] = table_df["date"].dt.date
    table_df = table_df.rename(
        columns={
            "date": "Date",
            "country": "Country",
            "metric_name": "Metric",
            "value": "Value",
        }
    )

    # Search filter
    search = st.text_input("Filter table (country / date):", placeholder="e.g. UK or 2026-01")
    if search:
        mask = table_df.apply(lambda row: search.lower() in str(row).lower(), axis=1)
        table_df = table_df[mask]

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        height=400,
    )

    csv = table_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇ Download CSV",
        data=csv,
        file_name=f"lg_international_{selected_metric.replace(' ', '_')}_{start_date}_{end_date}.csv",
        mime="text/csv",
    )
