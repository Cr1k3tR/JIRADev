# AI Jira Flow Intelligence — Prototype

A personal prototype of the "AI Jira Flow Intelligence" concept: analytics over
Jira workflow history that measures cycle time and stage durations, flags
bottlenecks/deviations, and uses Claude to turn those flags into a
plain-language exception summary plus recommended improvement experiments.

Runs entirely locally against **synthetic Jira data** by default — no live
Jira connection required. The data-source layer is built so a real Jira
Cloud instance can be plugged in later without touching the metrics,
dashboard, or AI code (see [Plugging in real Jira later](#plugging-in-real-jira-later)).

## Setup

```bash
cd jira-flow-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` (or export the variables in your shell) and
fill in `ANTHROPIC_API_KEY` if you want the AI Insights tab enabled. Every
other tab works without it.

```bash
cp .env.example .env
```

## Run

```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)   # or just `source .env` if using zsh/bash with `set -a`
streamlit run app.py
```

Streamlit will open the dashboard in your browser (default
http://localhost:8501). Use the sidebar to filter by project/team/issue
type/date range.

## Architecture

```
data_sources/     JiraDataSource interface + SyntheticJiraSource (real) + JiraCloudSource (stub)
metrics.py        pure pandas: stage durations, cycle time, trends, deviation detection
insights.py       Claude API: structured deviation data -> plain-language summary + experiments
app.py            Streamlit dashboard — the only file that imports Streamlit
config.py         workflow definition + all thresholds (single source of truth)
```

Everything downstream of `data_sources/` only depends on two DataFrame
contracts (documented in `data_sources/base.py`) — issues and changelog —
so swapping the data source never requires touching `metrics.py`,
`insights.py`, or `app.py`.

### Deviation detection (deliberately simple, no ML)

- **Stage outliers** — Tukey IQR rule (`Q3 + 1.5*IQR`) per (project, issue
  type, stage). Every flag carries the exact q1/q3/iqr/threshold it was
  compared against, so "why flagged" is always traceable.
- **Baseline shifts** — recent-weeks median vs. preceding-baseline-weeks
  median per (project, stage); flags when the relative change exceeds a
  threshold.
- **Ageing WIP** — currently open issues whose time in their current stage
  exceeds the P90 of closed-issue durations for that group.

All thresholds live in `config.py`.

### AI Insights

`insights.py` sends Claude (`claude-opus-5`, structured JSON output) **only
the computed deviation flags and coarse issue metadata** — project, issue
type, priority, the flagged stage, the numbers. It never sends issue
descriptions, comments, or any other free text, matching the "no
sensitive free-text ingestion" principle from the source governance doc.

Results are cached in-process keyed on a hash of the input payload, so
re-rendering the dashboard with unchanged filters doesn't re-call the API.
If `ANTHROPIC_API_KEY` isn't set, the tab shows a disabled notice and the
rest of the dashboard is unaffected.

## Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

Or a quick non-Streamlit sanity check of the data + metrics pipeline:

```bash
python scripts/verify_synthetic_data.py
```

## Plugging in real Jira later

1. Fill in the two methods in `data_sources/jira_cloud.py` (`get_issues`,
   `get_changelog`) — TODOs there name the exact Jira REST endpoints
   (`/rest/api/3/search`, changelog via `expand=changelog` or
   `/rest/api/3/issue/{key}/changelog`). Auth is HTTP Basic with
   `(email, api_token)`, not a bearer token.
2. Set in `.env`:
   ```
   DATA_SOURCE=jira_cloud
   JIRA_BASE_URL=https://your-domain.atlassian.net
   JIRA_EMAIL=you@example.com
   JIRA_API_TOKEN=...
   ```
3. Nothing else changes — `app.py`'s data-source factory reads
   `DATA_SOURCE` and instantiates the right class; `metrics.py` and
   `insights.py` only ever see the two DataFrames.

## Out of scope for this prototype

RBAC/auth, audit logging, multi-user support, data residency/hosting
concerns, ML-based anomaly detection (rule-based only, for explainability),
and the formal pilot process/success-metric tracking described in the
source governance doc — those are enterprise-pilot concerns, not this demo.
