#!/usr/bin/env python3
"""Quick CLI sanity check of the synthetic data + metrics pipeline, without
launching Streamlit. Run from the project root:

    python scripts/verify_synthetic_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

import metrics  # noqa: E402
from data_sources import SyntheticJiraSource  # noqa: E402


def main():
    src = SyntheticJiraSource()
    issues = src.get_issues()
    changelog = src.get_changelog()
    now = pd.Timestamp.now()

    print(f"Issues: {len(issues)}  |  Changelog rows: {len(changelog)}")
    print(f"Projects: {sorted(issues['project'].unique())}")
    print(f"Open (WIP) issues: {issues['resolved'].isna().sum()}")
    print(f"Reopened issues: {(issues['reopened_count'] > 0).sum()}")

    stage_durations = metrics.compute_stage_durations(issues, changelog, now=now)
    print("\nStage duration stats (median/P75/P90, hours):")
    print(metrics.stage_duration_stats(stage_durations, group_by=("stage",)).to_string(index=False))

    cycle = metrics.cycle_time(issues, changelog, now=now)
    closed = cycle[~cycle["is_open"]]
    print(f"\nCycle time (closed issues): median={closed['cycle_time_hours'].median():.1f}h "
          f"p75={closed['cycle_time_hours'].quantile(0.75):.1f}h "
          f"p90={closed['cycle_time_hours'].quantile(0.90):.1f}h")

    outliers = metrics.flag_iqr_outliers(stage_durations)
    print(f"\nIQR outliers flagged: {len(outliers)}")

    shifts = metrics.detect_baseline_shift(stage_durations, now=now)
    print(f"Baseline shifts flagged: {len(shifts)}")

    ageing = metrics.ageing_wip(issues, stage_durations)
    print(f"Ageing WIP flagged past P90: {int(ageing['is_aged'].sum())} / {len(ageing)} open occupancies")


if __name__ == "__main__":
    main()
