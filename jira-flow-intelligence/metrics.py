"""Pure pandas metrics over the JiraDataSource contract.

No Streamlit, no Claude — everything here takes/returns DataFrames so it's
independently testable and reusable regardless of where the data came from.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


# --- shared helpers -----------------------------------------------------------

def _percentile_stats(df: pd.DataFrame, value_col: str, group_by) -> pd.DataFrame:
    """count / median / p75 / p90 of value_col, grouped by group_by."""
    group_cols = list(group_by)
    grouped = df.groupby(group_cols)[value_col]
    stats = grouped.agg(
        ["count", "median", lambda s: np.percentile(s, 75), lambda s: np.percentile(s, 90)]
    )
    stats.columns = ["count", "median_hours", "p75_hours", "p90_hours"]
    return stats.reset_index()


# --- stage durations -----------------------------------------------------------

def compute_stage_durations(
    issues_df: pd.DataFrame, changelog_df: pd.DataFrame, now: pd.Timestamp | None = None
) -> pd.DataFrame:
    """One row per stage occupancy, joined with issue metadata for grouping.

    Excludes the terminal stage (config.TERMINAL_STAGE) — nothing "exits"
    Done under normal flow, so a completed issue's Done row always has
    exited_at=NaT even though the issue isn't open/WIP at all. Including it
    would misclassify finished work as ageing WIP. (A reopened issue's
    *first* Done occupancy does get a real exited_at and is a legitimate
    row here — only the truly-terminal one is dropped.)

    Open occupancies (exited_at is NaT) are right-censored at `now` — their
    duration_hours reflects "how long has this been sitting here so far",
    which is exactly what the ageing-WIP view needs.
    """
    if now is None:
        now = pd.Timestamp.now()

    df = changelog_df[changelog_df["exited_at"].notna() | (changelog_df["stage"] != config.TERMINAL_STAGE)].copy()
    df = df.merge(
        issues_df[["issue_key", "project", "team", "issue_type", "priority"]],
        on="issue_key",
        how="left",
    )
    df["is_open"] = df["exited_at"].isna()
    exited_effective = df["exited_at"].fillna(now)
    df["duration_hours"] = (exited_effective - df["entered_at"]).dt.total_seconds() / 3600.0
    return df


def stage_duration_stats(
    stage_durations_df: pd.DataFrame,
    group_by=("project", "issue_type", "stage"),
    include_open: bool = False,
) -> pd.DataFrame:
    """Median/P75/P90 stage duration per group. Excludes open occupancies by
    default — an in-progress stage isn't a finished sample to build a
    baseline from.
    """
    df = stage_durations_df if include_open else stage_durations_df[~stage_durations_df["is_open"]]
    return _percentile_stats(df, "duration_hours", group_by)


# --- cycle time -----------------------------------------------------------

def cycle_time(
    issues_df: pd.DataFrame,
    changelog_df: pd.DataFrame,
    start_stage: str = config.CYCLE_TIME_START_STAGE,
    end_stage: str = config.CYCLE_TIME_END_STAGE,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Per-issue cycle time between first entry into start_stage and first
    entry into end_stage. Open issues (never reached end_stage) are
    right-censored at `now`.
    """
    if now is None:
        now = pd.Timestamp.now()

    starts = changelog_df[changelog_df["stage"] == start_stage].groupby("issue_key")["entered_at"].min()
    ends = changelog_df[changelog_df["stage"] == end_stage].groupby("issue_key")["entered_at"].min()

    df = pd.DataFrame({"start": starts}).join(pd.DataFrame({"end": ends}), how="left")
    df["is_open"] = df["end"].isna()
    end_effective = df["end"].fillna(now)
    df["cycle_time_hours"] = (end_effective - df["start"]).dt.total_seconds() / 3600.0

    df = df.reset_index().merge(
        issues_df[["issue_key", "project", "team", "issue_type", "priority", "created"]],
        on="issue_key",
        how="left",
    )
    return df


def cycle_time_stats(cycle_time_df: pd.DataFrame, group_by=("project", "issue_type")) -> pd.DataFrame:
    closed = cycle_time_df[~cycle_time_df["is_open"]]
    return _percentile_stats(closed, "cycle_time_hours", group_by)


# --- trends -----------------------------------------------------------

def weekly_trend(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    window_weeks: int = config.TREND_ROLLING_WINDOW_WEEKS,
) -> pd.DataFrame:
    """Weekly median + IQR band + a trailing rolling median."""
    d = df.dropna(subset=[date_col, value_col]).copy()
    d["week"] = d[date_col].dt.to_period("W").dt.start_time

    weekly = d.groupby("week")[value_col].agg(
        ["count", "median", lambda s: np.percentile(s, 25), lambda s: np.percentile(s, 75)]
    )
    weekly.columns = ["count", "median", "p25", "p75"]
    weekly = weekly.reset_index().sort_values("week")
    weekly["rolling_median"] = weekly["median"].rolling(window=window_weeks, min_periods=1).mean()
    return weekly


# --- deviation detection -----------------------------------------------------------

def flag_iqr_outliers(
    stage_durations_df: pd.DataFrame,
    group_by=("project", "issue_type", "stage"),
    multiplier: float = config.IQR_OUTLIER_MULTIPLIER,
) -> pd.DataFrame:
    """Tukey rule: flag closed stage occupancies above Q3 + multiplier*IQR
    for their group. Every flagged row carries the exact q1/q3/iqr/threshold
    it was compared against, so "why flagged" is always traceable.
    """
    closed = stage_durations_df[~stage_durations_df["is_open"]].copy()
    group_cols = list(group_by)

    q1 = closed.groupby(group_cols)["duration_hours"].transform(lambda s: np.percentile(s, 25))
    q3 = closed.groupby(group_cols)["duration_hours"].transform(lambda s: np.percentile(s, 75))
    closed["q1"] = q1
    closed["q3"] = q3
    closed["iqr"] = closed["q3"] - closed["q1"]
    closed["threshold_hours"] = closed["q3"] + multiplier * closed["iqr"]

    flagged = closed[closed["duration_hours"] > closed["threshold_hours"]].copy()
    flagged["exceeded_by_hours"] = flagged["duration_hours"] - flagged["threshold_hours"]
    cols = [
        "issue_key", "project", "team", "issue_type", "priority", "stage",
        "entered_at", "exited_at", "duration_hours",
        "q1", "q3", "iqr", "threshold_hours", "exceeded_by_hours",
    ]
    return flagged[cols].sort_values("exceeded_by_hours", ascending=False)


def detect_baseline_shift(
    stage_durations_df: pd.DataFrame,
    group_by=("project", "stage"),
    baseline_weeks: int = config.BASELINE_SHIFT_BASELINE_WEEKS,
    recent_weeks: int = config.BASELINE_SHIFT_RECENT_WEEKS,
    pct_threshold: float = config.BASELINE_SHIFT_PCT_THRESHOLD,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Compare the recent-weeks median duration against the preceding
    baseline-weeks median, per group. Flags when the relative change
    exceeds pct_threshold — this is "changed vs baseline", distinct from
    flag_iqr_outliers' per-occupancy check.
    """
    if now is None:
        now = pd.Timestamp.now()

    closed = stage_durations_df[~stage_durations_df["is_open"]].copy()
    recent_cutoff = now - pd.Timedelta(weeks=recent_weeks)
    baseline_start = now - pd.Timedelta(weeks=recent_weeks + baseline_weeks)

    recent = closed[closed["exited_at"] >= recent_cutoff]
    baseline = closed[(closed["exited_at"] >= baseline_start) & (closed["exited_at"] < recent_cutoff)]

    group_cols = list(group_by)
    recent_median = recent.groupby(group_cols)["duration_hours"].median().rename("recent_median_hours")
    baseline_median = baseline.groupby(group_cols)["duration_hours"].median().rename("baseline_median_hours")

    merged = pd.concat([baseline_median, recent_median], axis=1).reset_index()
    merged = merged.dropna(subset=["recent_median_hours", "baseline_median_hours"])
    merged["pct_change"] = (
        (merged["recent_median_hours"] - merged["baseline_median_hours"]) / merged["baseline_median_hours"]
    )
    flagged = merged[merged["pct_change"].abs() >= pct_threshold].copy()
    return flagged.sort_values("pct_change", ascending=False)


def ageing_wip(
    issues_df: pd.DataFrame,
    stage_durations_df: pd.DataFrame,
    percentile: int = config.AGEING_WIP_PERCENTILE,
) -> pd.DataFrame:
    """Currently open issues, flagged when their current-stage age exceeds
    the given percentile of closed-issue durations for the same
    (project, issue_type, stage) group.
    """
    group_cols = ["project", "issue_type", "stage"]
    closed = stage_durations_df[~stage_durations_df["is_open"]]
    baseline = (
        closed.groupby(group_cols)["duration_hours"]
        .apply(lambda s: np.percentile(s, percentile))
        .rename("baseline_hours")
        .reset_index()
    )

    open_rows = stage_durations_df[stage_durations_df["is_open"]].copy()
    open_rows = open_rows.merge(baseline, on=group_cols, how="left")
    open_rows["age_hours"] = open_rows["duration_hours"]
    open_rows["is_aged"] = open_rows["age_hours"] > open_rows["baseline_hours"]

    cols = [
        "issue_key", "project", "team", "issue_type", "priority", "stage",
        "entered_at", "age_hours", "baseline_hours", "is_aged",
    ]
    return open_rows[cols].sort_values("age_hours", ascending=False)
