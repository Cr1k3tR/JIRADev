"""Synthetic Jira data generator.

Produces a plausible-looking issue set + changelog (status-transition
history) with realistic right-skewed stage durations, a small fraction of
deliberately injected bottlenecks (for the deviation-detection layer to
find), occasional Blocked excursions and reopens, and a slice of issues left
as current open WIP. Deterministic by default (fixed seed) so the demo is
reproducible.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

import config
from .base import JiraDataSource

# Baseline mean stage durations in hours, before per-project multiplier and
# outlier/blocked adjustments. "Backlog" and "To Do" model queueing time;
# "In Progress"/"In Review"/"Test" model active work.
_BASE_STAGE_HOURS = {
    "Backlog": 96.0,
    "To Do": 16.0,
    "In Progress": 30.0,
    "In Review": 8.0,
    "Test": 10.0,
}

# Relative velocity per project — used to make projects visibly different
# from one another in the dashboard (some slower/faster than others).
_PROJECT_SPEED_MULTIPLIER = {"PAY": 1.25, "PLAT": 1.0, "MOB": 0.8}

_BLOCKED_BASE_HOURS = 20.0
_REOPEN_STAGE_SHRINK = 0.5  # reopened issues repeat a shortened walk


class SyntheticJiraSource(JiraDataSource):
    def __init__(
        self,
        seed=config.SYNTHETIC_SEED,
        num_issues=config.SYNTHETIC_NUM_ISSUES,
        history_days=config.SYNTHETIC_HISTORY_DAYS,
    ):
        self._seed = seed
        self._num_issues = num_issues
        self._history_days = history_days
        self._issues_df = None
        self._changelog_df = None

    def get_issues(self) -> pd.DataFrame:
        self._ensure_generated()
        return self._issues_df

    def get_changelog(self) -> pd.DataFrame:
        self._ensure_generated()
        return self._changelog_df

    def _ensure_generated(self):
        if self._issues_df is None or self._changelog_df is None:
            self._generate()

    # -- generation --------------------------------------------------------

    def _generate(self):
        rng = np.random.default_rng(self._seed)
        now = pd.Timestamp.now().floor("h")

        issue_rows = []
        changelog_rows = []
        project_counters = {p: 0 for p in config.SYNTHETIC_PROJECTS}

        for _ in range(self._num_issues):
            project = rng.choice(config.SYNTHETIC_PROJECTS)
            project_counters[project] += 1
            issue_key = f"{project}-{project_counters[project]}"

            team = rng.choice(config.SYNTHETIC_TEAMS[project])
            board = f"{team} {rng.choice(config.SYNTHETIC_BOARD_SUFFIXES)}"
            issue_type = rng.choice(
                config.SYNTHETIC_ISSUE_TYPES, p=config.SYNTHETIC_ISSUE_TYPE_WEIGHTS
            )
            priority = rng.choice(
                config.SYNTHETIC_PRIORITIES, p=config.SYNTHETIC_PRIORITY_WEIGHTS
            )
            n_labels = rng.integers(0, 4)
            labels = list(
                rng.choice(config.SYNTHETIC_LABEL_POOL, size=n_labels, replace=False)
            ) if n_labels else []

            component_pool = config.SYNTHETIC_COMPONENTS[project]
            n_components = rng.integers(0, 3)
            components = list(
                rng.choice(component_pool, size=n_components, replace=False)
            ) if n_components else []

            days_ago = rng.uniform(0, self._history_days)
            created = now - timedelta(days=float(days_ago))

            leave_open = rng.random() < config.SYNTHETIC_OPEN_WIP_FRACTION
            stop_at_stage_idx = None
            if leave_open:
                # Stop somewhere in the active stages (not Backlog, not Done)
                stop_at_stage_idx = int(rng.integers(1, len(config.WORKFLOW_STAGES) - 1))

            issue_rows_local, current_status, resolved_at, current_time = self._walk_stages(
                rng, issue_key, project, created, stop_at_stage_idx
            )

            reopened_count = 0
            if resolved_at is not None and rng.random() < config.SYNTHETIC_REOPEN_PROBABILITY:
                # Give the first "Done" occupancy a real exit time (it did
                # stop being Done, when someone reopened it) — only the
                # issue's truly final row should ever carry exited_at=NaT.
                reopen_gap_hours = float(rng.gamma(shape=2.0, scale=24.0))
                reopen_time = current_time + timedelta(hours=reopen_gap_hours)
                issue_rows_local[-1]["exited_at"] = reopen_time

                reopen_rows, current_status, resolved_at, current_time = self._reopen_walk(
                    rng, issue_key, project, reopen_time
                )
                issue_rows_local = issue_rows_local + reopen_rows
                reopened_count = 1

            # Sampled durations are unbounded — a recently-created issue can
            # accumulate enough stage time to land in the future relative to
            # `now`. Shift the whole issue's timeline (created + every
            # changelog timestamp) backward by the overage so nothing ever
            # exceeds `now`, preserving every sampled duration exactly.
            latest_time = current_time
            if latest_time > now:
                shift = latest_time - now
                created -= shift
                if resolved_at is not None:
                    resolved_at -= shift
                for row in issue_rows_local:
                    row["entered_at"] -= shift
                    if pd.notna(row["exited_at"]):
                        row["exited_at"] -= shift

            changelog_rows.extend(issue_rows_local)

            sprint = f"Sprint {int(days_ago // 14) + 1}"

            issue_rows.append(
                {
                    "issue_key": issue_key,
                    "project": project,
                    "team": team,
                    "board": board,
                    "issue_type": issue_type,
                    "priority": priority,
                    "sprint": sprint,
                    "labels": labels,
                    "components": components,
                    "created": created,
                    "resolved": resolved_at if resolved_at is not None else pd.NaT,
                    "current_status": current_status,
                    "reopened_count": reopened_count,
                }
            )

        self._issues_df = pd.DataFrame(issue_rows)
        self._changelog_df = pd.DataFrame(changelog_rows)

    def _sample_duration_hours(self, rng, stage, project):
        base = _BASE_STAGE_HOURS[stage] * _PROJECT_SPEED_MULTIPLIER.get(project, 1.0)
        is_outlier = rng.random() < config.SYNTHETIC_OUTLIER_PROBABILITY
        if is_outlier:
            base *= config.SYNTHETIC_OUTLIER_SCALE_MULTIPLIER
        # Gamma(shape=2, scale=base/2) has mean == base with a realistic right skew.
        return float(rng.gamma(shape=2.0, scale=base / 2.0))

    def _walk_stages(self, rng, issue_key, project, created, stop_at_stage_idx):
        """Walk WORKFLOW_STAGES from Backlog, returning (rows, current_status,
        resolved_at | None, current_time). Stops early (open WIP) if
        stop_at_stage_idx is given.
        """
        rows = []
        current_time = created
        stages = config.WORKFLOW_STAGES

        for idx, stage in enumerate(stages):
            entered_at = current_time
            is_terminal = stage == config.TERMINAL_STAGE
            leaves_early = stop_at_stage_idx is not None and idx == stop_at_stage_idx

            if is_terminal:
                rows.append(
                    {"issue_key": issue_key, "stage": stage, "entered_at": entered_at, "exited_at": pd.NaT}
                )
                return rows, stage, entered_at, entered_at

            if leaves_early:
                rows.append(
                    {"issue_key": issue_key, "stage": stage, "entered_at": entered_at, "exited_at": pd.NaT}
                )
                return rows, stage, None, entered_at

            duration_hours = self._sample_duration_hours(rng, stage, project)
            exited_at = entered_at + timedelta(hours=duration_hours)

            # Occasional Blocked excursion mid-stage (active stages only).
            if stage in config.ACTIVE_STAGES and rng.random() < config.SYNTHETIC_BLOCKED_PROBABILITY:
                blocked_hours = float(rng.gamma(shape=2.0, scale=_BLOCKED_BASE_HOURS / 2.0))
                blocked_entered = exited_at
                blocked_exited = blocked_entered + timedelta(hours=blocked_hours)
                rows.append(
                    {"issue_key": issue_key, "stage": stage, "entered_at": entered_at, "exited_at": exited_at}
                )
                rows.append(
                    {
                        "issue_key": issue_key,
                        "stage": config.BLOCKED_STAGE,
                        "entered_at": blocked_entered,
                        "exited_at": blocked_exited,
                    }
                )
                current_time = blocked_exited
            else:
                rows.append(
                    {"issue_key": issue_key, "stage": stage, "entered_at": entered_at, "exited_at": exited_at}
                )
                current_time = exited_at

        # Should not reach here since Done is terminal and always in stages.
        return rows, stages[-1], current_time, current_time

    def _reopen_walk(self, rng, issue_key, project, reopened_at):
        """Shortened repeat walk: In Progress -> In Review -> Test -> Done."""
        rows = []
        current_time = reopened_at
        reopen_stages = ["In Progress", "In Review", "Test", "Done"]

        for stage in reopen_stages:
            entered_at = current_time
            if stage == "Done":
                rows.append(
                    {"issue_key": issue_key, "stage": stage, "entered_at": entered_at, "exited_at": pd.NaT}
                )
                return rows, stage, entered_at, entered_at

            base_hours = _BASE_STAGE_HOURS[stage] * _PROJECT_SPEED_MULTIPLIER.get(project, 1.0)
            duration_hours = float(
                rng.gamma(shape=2.0, scale=(base_hours * _REOPEN_STAGE_SHRINK) / 2.0)
            )
            exited_at = entered_at + timedelta(hours=duration_hours)
            rows.append(
                {"issue_key": issue_key, "stage": stage, "entered_at": entered_at, "exited_at": exited_at}
            )
            current_time = exited_at

        return rows, reopen_stages[-1], current_time, current_time
