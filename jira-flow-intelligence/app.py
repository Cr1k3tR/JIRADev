"""AI Jira Flow Intelligence — Streamlit dashboard.

The only file that imports Streamlit. Wires filters -> data source ->
metrics -> rendering, in 4 tabs matching the deterministic MVP deliverables
from the source governance doc. Fully rule-based — no AI/LLM calls anywhere
in this app.
"""

import os

import altair as alt
import pandas as pd
import streamlit as st

import config
import metrics
from data_sources import JiraCloudSource, SyntheticJiraSource

st.set_page_config(page_title="AI Jira Flow Intelligence", layout="wide")

# Streamlit's multiselect value-container hard-clips at max-height:168px with
# overflow:hidden — with 6+ chips selected (e.g. all teams by default), the
# last one or two are silently invisible with no indication anything's
# hidden. Keep the same footprint but make it scrollable instead of clipped,
# so nothing disappears without a visible scrollbar. Confirmed via direct
# DOM/computed-style inspection of the live app, not guessed.
st.markdown(
    """
    <style>
    div[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
        max-height: 200px;
        overflow-y: auto;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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

# Labels/components are optional facets: every value offered is drawn from
# the currently loaded data (locked & controlled — no free text), but an
# empty selection means "don't filter on this" rather than "match nothing".
FACET_FIELDS = [("labels", "Labels (optional)"), ("components", "Components (optional)")]
selected_facets = {}
for facet_field, facet_label in FACET_FIELDS:
    facet_pool = sorted({value for row in issues_df[facet_field] for value in row})
    selected_facets[facet_field] = st.sidebar.multiselect(facet_label, facet_pool, default=[])

min_date = issues_df["created"].min().date()
max_date = issues_df["created"].max().date()
date_range = st.sidebar.slider(
    "Created date range", min_value=min_date, max_value=max_date, value=(min_date, max_date)
)

st.sidebar.header("Cycle time boundaries")
from_stage = st.sidebar.selectbox(
    "From stage", config.WORKFLOW_STAGES, index=config.WORKFLOW_STAGES.index(config.CYCLE_TIME_START_STAGE)
)
to_stage = st.sidebar.selectbox(
    "To stage", config.WORKFLOW_STAGES, index=config.WORKFLOW_STAGES.index(config.CYCLE_TIME_END_STAGE)
)
if config.WORKFLOW_STAGES.index(from_stage) >= config.WORKFLOW_STAGES.index(to_stage):
    st.sidebar.error("'From' stage must come before 'To' stage in the workflow.")
    st.stop()

mask = (
    issues_df["project"].isin(selected_projects)
    & issues_df["team"].isin(selected_teams)
    & issues_df["issue_type"].isin(selected_types)
    & (issues_df["created"].dt.date >= date_range[0])
    & (issues_df["created"].dt.date <= date_range[1])
)
for facet_field, selected in selected_facets.items():
    if selected:
        mask &= issues_df[facet_field].apply(lambda row, selected=selected: any(v in selected for v in row))
filtered_issues = issues_df[mask]

if filtered_issues.empty:
    st.warning("No issues match the current filters — widen your selection.")
    st.stop()

filtered_changelog = changelog_df[changelog_df["issue_key"].isin(filtered_issues["issue_key"])]

# --- Shared metrics computation -----------------------------------------------------------

now = pd.Timestamp.now()
stage_durations_df = metrics.compute_stage_durations(filtered_issues, filtered_changelog, now=now)
cycle_time_df = metrics.cycle_time(
    filtered_issues, filtered_changelog, start_stage=from_stage, end_stage=to_stage, now=now
)
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
    st.header("Overview")
    st.caption(f"Cycle time measured from **{from_stage}** to **{to_stage}**.")
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
        # Let Altair bin natively (quantitative x-axis) instead of pre-binning
        # with pd.cut into string interval labels — a string-labeled index
        # gets sorted alphabetically by st.bar_chart ("11.2" before "2.3"),
        # which silently scrambles the histogram's bar order.
        chart_data = pd.DataFrame({"cycle_time_days": closed_cycle["cycle_time_hours"] / 24.0})
        histogram = (
            alt.Chart(chart_data)
            .mark_bar()
            .encode(
                x=alt.X("cycle_time_days:Q", bin=alt.Bin(maxbins=15), title="Cycle time (days)"),
                y=alt.Y("count():Q", title="Issues"),
            )
        )
        st.altair_chart(histogram, use_container_width=True)
    else:
        st.info("No completed issues in this filter selection yet.")

    st.subheader("Weekly cycle-time trend")
    if not weekly_df.empty:
        st.line_chart(weekly_df.set_index("week")[["median", "rolling_median", "p25", "p75"]])
    else:
        st.info("Not enough completed issues yet to show a trend.")

# --- Bottlenecks -----------------------------------------------------------

with bottleneck_tab:
    st.header("Bottlenecks")
    st.subheader("Where does time accumulate? (median hours per stage)")
    if not overall_stage_stats_df.empty:
        # st.bar_chart re-sorts a string-labeled axis alphabetically (same
        # root cause as the cycle-time histogram fix) — sort="-y" pins the
        # bar order to actual descending value instead.
        bottleneck_chart = (
            alt.Chart(overall_stage_stats_df)
            .mark_bar()
            .encode(
                x=alt.X("stage:N", sort="-y", title="Stage"),
                y=alt.Y("median_hours:Q", title="Median hours"),
            )
        )
        st.altair_chart(bottleneck_chart, use_container_width=True)
    st.subheader("Stage duration detail (median / P75 / P90 by project + issue type)")
    st.dataframe(stage_stats_df, width="stretch")

# --- Ageing WIP -----------------------------------------------------------

with wip_tab:
    st.header("Ageing WIP")
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
    st.header("Deviations")
    st.subheader("Stage outliers (Tukey IQR rule)")
    st.caption("Each flag shows the exact q1/q3/iqr/threshold it was compared against.")
    st.dataframe(iqr_outliers_df, width="stretch")

    st.subheader("Baseline shifts (recent vs. preceding period)")
    st.dataframe(baseline_shift_df, width="stretch")
