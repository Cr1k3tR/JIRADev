"""AI Jira Flow Intelligence — Streamlit dashboard.

The only file that imports Streamlit. Wires filters -> data source ->
metrics -> rendering, in 4 tabs matching the deterministic MVP deliverables
from the source governance doc. Fully rule-based — no AI/LLM calls anywhere
in this app.
"""

import os

import pandas as pd
import streamlit as st

import metrics
from data_sources import JiraCloudSource, SyntheticJiraSource

st.set_page_config(page_title="AI Jira Flow Intelligence", layout="wide")


@st.cache_resource
def _get_data_source():
    source_type = os.environ.get("DATA_SOURCE", "synthetic")
    if source_type == "synthetic":
        return SyntheticJiraSource()
    if source_type == "jira_cloud":
        return JiraCloudSource(
            base_url=os.environ.get("JIRA_BASE_URL", ""),
            email=os.environ.get("JIRA_EMAIL", ""),
            api_token=os.environ.get("JIRA_API_TOKEN", ""),
        )
    raise ValueError(f"Unknown DATA_SOURCE: {source_type!r}")


def _format_hours(hours: float) -> str:
    if pd.isna(hours):
        return "—"
    days = hours / 24.0
    return f"{days:.1f}d" if days >= 1 else f"{hours:.1f}h"


st.title("AI Jira Flow Intelligence")
st.caption(
    "Prototype — synthetic data by default. Set DATA_SOURCE=jira_cloud once "
    "a real Jira instance/token is wired up in data_sources/jira_cloud.py."
)

source = _get_data_source()
issues_df = source.get_issues()
changelog_df = source.get_changelog()

# --- Sidebar filters -----------------------------------------------------------

st.sidebar.header("Filters")
projects = sorted(issues_df["project"].unique())
teams = sorted(issues_df["team"].unique())
issue_types = sorted(issues_df["issue_type"].unique())

selected_projects = st.sidebar.multiselect("Project", projects, default=projects)
selected_teams = st.sidebar.multiselect("Team", teams, default=teams)
selected_types = st.sidebar.multiselect("Issue type", issue_types, default=issue_types)

min_date = issues_df["created"].min().date()
max_date = issues_df["created"].max().date()
date_range = st.sidebar.slider(
    "Created date range", min_value=min_date, max_value=max_date, value=(min_date, max_date)
)

mask = (
    issues_df["project"].isin(selected_projects)
    & issues_df["team"].isin(selected_teams)
    & issues_df["issue_type"].isin(selected_types)
    & (issues_df["created"].dt.date >= date_range[0])
    & (issues_df["created"].dt.date <= date_range[1])
)
filtered_issues = issues_df[mask]

if filtered_issues.empty:
    st.warning("No issues match the current filters — widen your selection.")
    st.stop()

filtered_changelog = changelog_df[changelog_df["issue_key"].isin(filtered_issues["issue_key"])]

# --- Shared metrics computation -----------------------------------------------------------

now = pd.Timestamp.now()
stage_durations_df = metrics.compute_stage_durations(filtered_issues, filtered_changelog, now=now)
cycle_time_df = metrics.cycle_time(filtered_issues, filtered_changelog, now=now)
cycle_stats_df = metrics.cycle_time_stats(cycle_time_df)
stage_stats_df = metrics.stage_duration_stats(stage_durations_df)
overall_stage_stats_df = metrics.stage_duration_stats(stage_durations_df, group_by=("stage",))
weekly_df = metrics.weekly_trend(cycle_time_df[~cycle_time_df["is_open"]], date_col="end", value_col="cycle_time_hours")

iqr_outliers_df = metrics.flag_iqr_outliers(stage_durations_df)
baseline_shift_df = metrics.detect_baseline_shift(stage_durations_df, now=now)
ageing_df = metrics.ageing_wip(filtered_issues, stage_durations_df)

overview_tab, bottleneck_tab, wip_tab, deviations_tab = st.tabs(
    ["Overview", "Bottlenecks", "Ageing WIP", "Deviations"]
)

# --- Overview -----------------------------------------------------------

with overview_tab:
    closed_cycle = cycle_time_df[~cycle_time_df["is_open"]]
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Median cycle time", _format_hours(closed_cycle["cycle_time_hours"].median()))
    col2.metric("P75 cycle time", _format_hours(closed_cycle["cycle_time_hours"].quantile(0.75)))
    col3.metric("P90 cycle time", _format_hours(closed_cycle["cycle_time_hours"].quantile(0.90)))
    col4.metric("Open WIP", int(cycle_time_df["is_open"].sum()))
    throughput_4wk = int((closed_cycle["end"] >= now - pd.Timedelta(weeks=4)).sum())
    col5.metric("Throughput (4wk)", throughput_4wk)

    st.subheader("Cycle time distribution")
    if not closed_cycle.empty:
        bins = pd.cut(closed_cycle["cycle_time_hours"] / 24.0, bins=15)
        hist = bins.value_counts().sort_index()
        hist.index = hist.index.astype(str)
        st.bar_chart(hist)
    else:
        st.info("No completed issues in this filter selection yet.")

    st.subheader("Weekly cycle-time trend")
    if not weekly_df.empty:
        st.line_chart(weekly_df.set_index("week")[["median", "rolling_median", "p25", "p75"]])
    else:
        st.info("Not enough completed issues yet to show a trend.")

# --- Bottlenecks -----------------------------------------------------------

with bottleneck_tab:
    st.subheader("Where does time accumulate? (median hours per stage)")
    if not overall_stage_stats_df.empty:
        chart_df = overall_stage_stats_df.set_index("stage")["median_hours"].sort_values(ascending=False)
        st.bar_chart(chart_df)
    st.subheader("Stage duration detail (median / P75 / P90 by project + issue type)")
    st.dataframe(stage_stats_df, width="stretch")

# --- Ageing WIP -----------------------------------------------------------

with wip_tab:
    st.subheader("Currently open issues, oldest first")
    display_df = ageing_df.copy()
    if not display_df.empty:
        display_df["age"] = display_df["age_hours"].apply(_format_hours)
        display_df["baseline (P90)"] = display_df["baseline_hours"].apply(_format_hours)
    st.dataframe(
        display_df[["issue_key", "project", "team", "issue_type", "priority", "stage", "age", "baseline (P90)", "is_aged"]]
        if not display_df.empty else display_df,
        width="stretch",
    )

# --- Deviations -----------------------------------------------------------

with deviations_tab:
    st.subheader("Stage outliers (Tukey IQR rule)")
    st.caption("Each flag shows the exact q1/q3/iqr/threshold it was compared against.")
    st.dataframe(iqr_outliers_df, width="stretch")

    st.subheader("Baseline shifts (recent vs. preceding period)")
    st.dataframe(baseline_shift_df, width="stretch")
