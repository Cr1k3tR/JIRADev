# AI Jira Flow Intelligence — Prototype

A personal prototype of the "AI Jira Flow Intelligence" concept: analytics over
Jira workflow history that measures cycle time and stage durations, and flags
bottlenecks/deviations — cycle-time percentiles, stage bottleneck breakdown,
ageing-WIP tracking, and outlier/baseline-shift detection.

**Fully deterministic — no AI/LLM calls anywhere in this app.** Every number
and every flag comes from plain statistics (percentiles, Tukey's IQR rule,
median comparisons) in `metrics.py`. There is no natural-language summary or
AI-generated recommendation layer.

Runs entirely locally against **synthetic Jira data** by default — no live
Jira connection required. The data-source layer is built so a real Jira
Cloud instance can be plugged in later without touching the metrics or
dashboard code (see [Plugging in real Jira later](#plugging-in-real-jira-later)).

## Setup

```bash
cd jira-flow-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` if you want to override the data source
(defaults to synthetic — no configuration needed to run it as-is):

```bash
cp .env.example .env
```

## Run

```bash
source .venv/bin/activate
streamlit run app.py
```

Streamlit will open the dashboard in your browser (default
http://localhost:8501). Use the sidebar to filter by project/team/issue
type/date range.

## Architecture

```
data_sources/     JiraDataSource interface + SyntheticJiraSource (real) + JiraCloudSource (stub)
metrics.py        pure pandas: stage durations, cycle time, trends, deviation detection
app.py            Streamlit dashboard — the only file that imports Streamlit
config.py         workflow definition + all thresholds (single source of truth)
```

Everything downstream of `data_sources/` only depends on two DataFrame
contracts (documented in `data_sources/base.py`) — issues and changelog —
so swapping the data source never requires touching `metrics.py` or `app.py`.

### Deviation detection (deliberately simple, no ML, no AI)

- **Stage outliers** — Tukey IQR rule (`Q3 + 1.5*IQR`) per (project, issue
  type, stage). Every flag carries the exact q1/q3/iqr/threshold it was
  compared against, so "why flagged" is always traceable.
- **Baseline shifts** — recent-weeks median vs. preceding-baseline-weeks
  median per (project, stage); flags when the relative change exceeds a
  threshold.
- **Ageing WIP** — currently open issues whose time in their current stage
  exceeds the P90 of closed-issue durations for that group.

All thresholds live in `config.py`. There is no narrative summary or
recommended-experiments layer — the dashboard shows the numbers and the
flags; interpreting them is left to the reader.

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
   `DATA_SOURCE` and instantiates the right class; `metrics.py` only ever
   sees the two DataFrames.

## Out of scope for this prototype

RBAC/auth, audit logging, multi-user support, data residency/hosting
concerns, any AI/LLM-generated narrative or recommendations, ML-based
anomaly detection (rule-based only, for explainability), and the formal
pilot process/success-metric tracking described in the source governance
doc — those are enterprise-pilot concerns, not this demo.
