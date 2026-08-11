import numpy as np
import pandas as pd
import pytest

import metrics

T0 = pd.Timestamp("2026-01-01 00:00:00")

NORMAL_DURATIONS_H = [8, 9, 10, 11, 12, 9, 10, 11, 8, 12, 10]
OUTLIER_DURATION_H = 100


def _issue_row(key, project="P", issue_type="Story", priority="Medium", team="T", resolved=pd.NaT):
    return {
        "issue_key": key, "project": project, "team": team, "issue_type": issue_type,
        "priority": priority, "sprint": "Sprint 1", "labels": [], "created": T0,
        "resolved": resolved, "current_status": "Done" if pd.notna(resolved) else "In Progress",
        "reopened_count": 0,
    }


def _build_fixture():
    """11 'normal' closed issues + 1 deliberate outlier + 1 still-open issue,
    all in project P / Story, all passing through In Progress -> Done.
    """
    issues, changelog = [], []

    for i, dur in enumerate(NORMAL_DURATIONS_H):
        key = f"P-{i + 1}"
        exited = T0 + pd.Timedelta(hours=dur)
        issues.append(_issue_row(key, resolved=exited))
        changelog.append({"issue_key": key, "stage": "In Progress", "entered_at": T0, "exited_at": exited})
        changelog.append({"issue_key": key, "stage": "Done", "entered_at": exited, "exited_at": pd.NaT})

    outlier_exit = T0 + pd.Timedelta(hours=OUTLIER_DURATION_H)
    issues.append(_issue_row("P-OUT", resolved=outlier_exit))
    changelog.append({"issue_key": "P-OUT", "stage": "In Progress", "entered_at": T0, "exited_at": outlier_exit})
    changelog.append({"issue_key": "P-OUT", "stage": "Done", "entered_at": outlier_exit, "exited_at": pd.NaT})

    issues.append(_issue_row("P-OPEN", resolved=pd.NaT))
    changelog.append({"issue_key": "P-OPEN", "stage": "In Progress", "entered_at": T0, "exited_at": pd.NaT})

    return pd.DataFrame(issues), pd.DataFrame(changelog)


def test_compute_stage_durations_censors_open_at_now():
    issues, changelog = _build_fixture()
    now = T0 + pd.Timedelta(hours=50)
    sd = metrics.compute_stage_durations(issues, changelog, now=now)

    open_row = sd[(sd["issue_key"] == "P-OPEN") & (sd["stage"] == "In Progress")].iloc[0]
    assert open_row["is_open"]
    assert open_row["duration_hours"] == pytest.approx(50.0)

    closed_row = sd[(sd["issue_key"] == "P-1") & (sd["stage"] == "In Progress")].iloc[0]
    assert not closed_row["is_open"]
    assert closed_row["duration_hours"] == pytest.approx(8.0)


def test_stage_duration_stats_excludes_open_by_default():
    issues, changelog = _build_fixture()
    sd = metrics.compute_stage_durations(issues, changelog, now=T0 + pd.Timedelta(hours=200))
    stats = metrics.stage_duration_stats(sd, group_by=("stage",))

    in_progress = stats[stats["stage"] == "In Progress"].iloc[0]
    assert in_progress["count"] == 12  # 11 normal + outlier, NOT the open one
    expected_median = float(np.median(NORMAL_DURATIONS_H + [OUTLIER_DURATION_H]))
    assert in_progress["median_hours"] == pytest.approx(expected_median)


def test_stage_duration_stats_can_include_open():
    issues, changelog = _build_fixture()
    sd = metrics.compute_stage_durations(issues, changelog, now=T0 + pd.Timedelta(hours=200))
    stats = metrics.stage_duration_stats(sd, group_by=("stage",), include_open=True)

    in_progress = stats[stats["stage"] == "In Progress"].iloc[0]
    assert in_progress["count"] == 13


def test_flag_iqr_outliers_flags_only_the_outlier():
    issues, changelog = _build_fixture()
    sd = metrics.compute_stage_durations(issues, changelog, now=T0 + pd.Timedelta(hours=200))
    flagged = metrics.flag_iqr_outliers(sd, group_by=("stage",))

    assert set(flagged["issue_key"]) == {"P-OUT"}

    all_closed = NORMAL_DURATIONS_H + [OUTLIER_DURATION_H]
    q1, q3 = np.percentile(all_closed, 25), np.percentile(all_closed, 75)
    threshold = q3 + 1.5 * (q3 - q1)
    row = flagged.iloc[0]
    assert row["threshold_hours"] == pytest.approx(threshold)
    assert row["duration_hours"] == pytest.approx(OUTLIER_DURATION_H)


def test_flag_iqr_outliers_no_false_positives_on_clean_data():
    issues, changelog = [], []
    for i, dur in enumerate(NORMAL_DURATIONS_H):
        key = f"C-{i + 1}"
        exited = T0 + pd.Timedelta(hours=dur)
        issues.append(_issue_row(key, resolved=exited))
        changelog.append({"issue_key": key, "stage": "In Progress", "entered_at": T0, "exited_at": exited})
        changelog.append({"issue_key": key, "stage": "Done", "entered_at": exited, "exited_at": pd.NaT})

    issues_df, changelog_df = pd.DataFrame(issues), pd.DataFrame(changelog)
    sd = metrics.compute_stage_durations(issues_df, changelog_df, now=T0 + pd.Timedelta(hours=200))
    flagged = metrics.flag_iqr_outliers(sd, group_by=("stage",))

    assert flagged.empty


def test_cycle_time_start_to_end():
    issues, changelog = _build_fixture()
    ct = metrics.cycle_time(
        issues, changelog, start_stage="In Progress", end_stage="Done", now=T0 + pd.Timedelta(hours=200)
    )

    closed_row = ct[ct["issue_key"] == "P-1"].iloc[0]
    assert not closed_row["is_open"]
    assert closed_row["cycle_time_hours"] == pytest.approx(8.0)

    open_row = ct[ct["issue_key"] == "P-OPEN"].iloc[0]
    assert open_row["is_open"]
    assert open_row["cycle_time_hours"] == pytest.approx(200.0)


def test_cycle_time_stats_excludes_open():
    issues, changelog = _build_fixture()
    ct = metrics.cycle_time(issues, changelog, now=T0 + pd.Timedelta(hours=200))
    stats = metrics.cycle_time_stats(ct, group_by=("project",))

    row = stats[stats["project"] == "P"].iloc[0]
    assert row["count"] == 12
    expected_median = float(np.median(NORMAL_DURATIONS_H + [OUTLIER_DURATION_H]))
    assert row["median_hours"] == pytest.approx(expected_median)


def test_ageing_wip_flags_when_past_p90_baseline():
    issues, changelog = _build_fixture()
    sd = metrics.compute_stage_durations(issues, changelog, now=T0 + pd.Timedelta(hours=200))
    ageing = metrics.ageing_wip(issues, sd, percentile=90)

    open_row = ageing[ageing["issue_key"] == "P-OPEN"].iloc[0]
    expected_p90 = np.percentile(NORMAL_DURATIONS_H + [OUTLIER_DURATION_H], 90)
    assert open_row["baseline_hours"] == pytest.approx(expected_p90)
    assert open_row["age_hours"] == pytest.approx(200.0)
    assert bool(open_row["is_aged"]) == (200.0 > expected_p90)


def test_detect_baseline_shift_flags_when_recent_much_slower():
    now = T0 + pd.Timedelta(weeks=10)
    baseline_weeks, recent_weeks = 4, 1

    issues, changelog = [], []
    baseline_exit = now - pd.Timedelta(weeks=3)
    for i in range(5):
        key = f"B-{i + 1}"
        entered = baseline_exit - pd.Timedelta(hours=10)
        issues.append(_issue_row(key, resolved=baseline_exit))
        changelog.append({"issue_key": key, "stage": "In Progress", "entered_at": entered, "exited_at": baseline_exit})
        changelog.append({"issue_key": key, "stage": "Done", "entered_at": baseline_exit, "exited_at": pd.NaT})

    recent_exit = now - pd.Timedelta(hours=2)
    for i in range(5):
        key = f"R-{i + 1}"
        entered = recent_exit - pd.Timedelta(hours=40)
        issues.append(_issue_row(key, resolved=recent_exit))
        changelog.append({"issue_key": key, "stage": "In Progress", "entered_at": entered, "exited_at": recent_exit})
        changelog.append({"issue_key": key, "stage": "Done", "entered_at": recent_exit, "exited_at": pd.NaT})

    issues_df, changelog_df = pd.DataFrame(issues), pd.DataFrame(changelog)
    sd = metrics.compute_stage_durations(issues_df, changelog_df, now=now)

    shifted = metrics.detect_baseline_shift(
        sd, group_by=("project", "stage"), baseline_weeks=baseline_weeks,
        recent_weeks=recent_weeks, pct_threshold=0.2, now=now,
    )

    row = shifted[(shifted["project"] == "P") & (shifted["stage"] == "In Progress")].iloc[0]
    assert row["baseline_median_hours"] == pytest.approx(10.0)
    assert row["recent_median_hours"] == pytest.approx(40.0)
    assert row["pct_change"] == pytest.approx(3.0)


def test_weekly_trend_buckets_by_week():
    df = pd.DataFrame(
        {
            "date": [T0, T0 + pd.Timedelta(days=1), T0 + pd.Timedelta(days=8), T0 + pd.Timedelta(days=9)],
            "value": [10, 20, 30, 40],
        }
    )
    trend = metrics.weekly_trend(df, date_col="date", value_col="value", window_weeks=2)

    assert len(trend) == 2
    assert trend.iloc[0]["median"] == pytest.approx(15.0)
    assert trend.iloc[1]["median"] == pytest.approx(35.0)
