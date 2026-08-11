"""Single source of truth for workflow definition and analysis thresholds.

Nothing in metrics.py, insights.py, or app.py should hardcode a stage name,
threshold, or window size — it should reference a constant here instead.
"""

# Ordered workflow stages an issue moves through on the happy path.
# "Blocked" is not part of the sequence — it's a side-excursion any active
# stage can enter from and return to (see data_sources/synthetic.py).
WORKFLOW_STAGES = ["Backlog", "To Do", "In Progress", "In Review", "Test", "Done"]
ACTIVE_STAGES = ["To Do", "In Progress", "In Review", "Test"]  # can go Blocked
BLOCKED_STAGE = "Blocked"
TERMINAL_STAGE = "Done"

# Cycle time is measured between these two stage-entry events by default.
# (Distinct from lead time, which would start at `created` instead.)
CYCLE_TIME_START_STAGE = "In Progress"
CYCLE_TIME_END_STAGE = "Done"

# --- Deviation detection thresholds -----------------------------------------

# Tukey IQR rule: flag values above Q3 + IQR_OUTLIER_MULTIPLIER * (Q3 - Q1)
IQR_OUTLIER_MULTIPLIER = 1.5

# Baseline-shift detection: compare the median of the most recent
# BASELINE_SHIFT_RECENT_WEEKS against the median of the preceding
# BASELINE_SHIFT_BASELINE_WEEKS; flag if the relative change exceeds
# BASELINE_SHIFT_PCT_THRESHOLD.
BASELINE_SHIFT_BASELINE_WEEKS = 8
BASELINE_SHIFT_RECENT_WEEKS = 2
BASELINE_SHIFT_PCT_THRESHOLD = 0.20

# Weekly trend rolling-median window.
TREND_ROLLING_WINDOW_WEEKS = 4

# Ageing WIP: an open issue is flagged once its current-stage age exceeds
# this percentile of closed-issue durations for its (project, issue_type,
# stage) group.
AGEING_WIP_PERCENTILE = 90

# --- Synthetic data defaults -------------------------------------------------

SYNTHETIC_SEED = 42
SYNTHETIC_NUM_ISSUES = 800
SYNTHETIC_HISTORY_DAYS = 182  # ~6 months

SYNTHETIC_PROJECTS = ["PAY", "PLAT", "MOB"]
SYNTHETIC_TEAMS = {
    "PAY": ["Payments Core", "Payments Risk"],
    "PLAT": ["Platform Infra", "Platform Data"],
    "MOB": ["Mobile iOS", "Mobile Android"],
}
SYNTHETIC_ISSUE_TYPES = ["Story", "Bug", "Task", "Epic"]
SYNTHETIC_ISSUE_TYPE_WEIGHTS = [0.45, 0.30, 0.20, 0.05]
SYNTHETIC_PRIORITIES = ["Low", "Medium", "High", "Critical"]
SYNTHETIC_PRIORITY_WEIGHTS = [0.20, 0.45, 0.25, 0.10]
SYNTHETIC_LABEL_POOL = [
    "backend", "frontend", "infra", "tech-debt", "customer-reported",
    "security", "performance", "flaky-test", "docs",
]

# Probability a given stage transition draws from the heavy-tail (bottleneck)
# distribution instead of the normal one.
SYNTHETIC_OUTLIER_PROBABILITY = 0.07
SYNTHETIC_OUTLIER_SCALE_MULTIPLIER = 4.0

SYNTHETIC_BLOCKED_PROBABILITY = 0.05
SYNTHETIC_REOPEN_PROBABILITY = 0.05
# Fraction of issues left as current WIP (stopped partway through the flow).
SYNTHETIC_OPEN_WIP_FRACTION = 0.15
