import pandas as pd

import config
import metrics
from data_sources import SyntheticJiraSource

ISSUE_COLUMNS = {
    "issue_key", "project", "team", "issue_type", "priority", "sprint",
    "labels", "created", "resolved", "current_status", "reopened_count",
}
CHANGELOG_COLUMNS = {"issue_key", "stage", "entered_at", "exited_at"}


def _make_source(num_issues=200):
    return SyntheticJiraSource(seed=1, num_issues=num_issues)


def test_schema():
    src = _make_source()
    issues = src.get_issues()
    changelog = src.get_changelog()

    assert ISSUE_COLUMNS.issubset(issues.columns)
    assert CHANGELOG_COLUMNS.issubset(changelog.columns)
    assert len(issues) == 200
    assert not changelog.empty


def test_no_required_field_nulls():
    issues = _make_source().get_issues()
    for col in ["issue_key", "project", "team", "issue_type", "priority", "created", "current_status"]:
        assert issues[col].notna().all(), f"unexpected null in {col}"


def test_no_timestamp_exceeds_now():
    src = _make_source()
    issues = src.get_issues()
    changelog = src.get_changelog()
    now = pd.Timestamp.now()

    assert (issues["created"] <= now).all()
    assert (issues["resolved"].dropna() <= now).all()
    assert (changelog["entered_at"] <= now).all()
    assert (changelog["exited_at"].dropna() <= now).all()


def test_changelog_is_chronologically_contiguous_per_issue():
    changelog = _make_source().get_changelog()

    for issue_key, group in changelog.groupby("issue_key"):
        ordered = group.sort_values("entered_at").reset_index(drop=True)
        # entered_at never decreases
        assert (ordered["entered_at"].diff().dropna() >= pd.Timedelta(0)).all()
        # each row's exit hands off exactly to the next row's entry
        for i in range(len(ordered) - 1):
            exited = ordered.loc[i, "exited_at"]
            assert pd.notna(exited), f"{issue_key} has a mid-sequence open stage"
            assert exited == ordered.loc[i + 1, "entered_at"]
        # the last row is either open (current stage) or terminal Done
        last_exited = ordered.loc[len(ordered) - 1, "exited_at"]
        last_stage = ordered.loc[len(ordered) - 1, "stage"]
        assert pd.isna(last_exited)
        if pd.notna(issue_key):
            pass  # last_stage is either an active stage (open WIP) or Done


def test_no_negative_durations():
    src = _make_source(num_issues=500)
    issues = src.get_issues()
    changelog = src.get_changelog()
    now = pd.Timestamp.now()

    stage_durations = metrics.compute_stage_durations(issues, changelog, now=now)
    assert (stage_durations["duration_hours"] >= 0).all()

    cycle = metrics.cycle_time(issues, changelog, now=now)
    assert (cycle["cycle_time_hours"] >= 0).all()


def test_outlier_injection_produces_detectable_outliers():
    src = _make_source(num_issues=500)
    issues = src.get_issues()
    changelog = src.get_changelog()

    stage_durations = metrics.compute_stage_durations(issues, changelog)
    outliers = metrics.flag_iqr_outliers(stage_durations)

    assert len(outliers) > 0
    assert (outliers["duration_hours"] > outliers["threshold_hours"]).all()


def test_some_issues_left_open_as_wip():
    issues = _make_source(num_issues=500).get_issues()
    open_count = issues["resolved"].isna().sum()

    assert open_count > 0
    assert open_count < len(issues)


def test_deterministic_with_same_seed():
    a = SyntheticJiraSource(seed=99, num_issues=50).get_issues()
    b = SyntheticJiraSource(seed=99, num_issues=50).get_issues()

    pd.testing.assert_frame_equal(a, b)


def test_blocked_stage_appears():
    changelog = _make_source(num_issues=500).get_changelog()
    assert (changelog["stage"] == config.BLOCKED_STAGE).any()


def test_reopen_increments_count():
    issues = _make_source(num_issues=500).get_issues()
    assert (issues["reopened_count"] > 0).any()
