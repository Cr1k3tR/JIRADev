"""Claude-powered plain-language exception summaries + improvement experiments.

Only ever receives structured metrics (deviation flags, baseline-shift
stats, ageing-WIP rows) — never raw issue descriptions/comments, matching
the "no free-text ingestion" principle from the source governance doc.

Degrades gracefully: if ANTHROPIC_API_KEY isn't set, get_client() returns
None and callers should skip the AI call entirely rather than raising.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

import anthropic

MODEL = "claude-opus-5"

SYSTEM_PROMPT = (
    "You are a delivery-flow analyst reviewing structured Jira flow metrics "
    "for engineering delivery teams. Write for Product Owners and Scrum "
    "Masters: plain language, no jargon, no code. Base every statement only "
    "on the structured data provided in the user message — do not speculate "
    "about root causes that aren't evidenced in the data. Produce one short "
    "exception summary (2-4 sentences) covering the most significant "
    "bottlenecks/deviations, and 1-3 concrete improvement experiments a team "
    "could run, each with a testable hypothesis and a way to tell whether it "
    "worked."
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "exception_summary": {
            "type": "string",
            "description": "2-4 sentence plain-language summary of the most significant flagged deviations.",
        },
        "experiments": {
            "type": "array",
            "description": "Up to 3 concrete improvement experiments.",
            "items": {
                "type": "object",
                "properties": {
                    "hypothesis": {"type": "string"},
                    "experiment": {"type": "string"},
                    "expected_signal": {
                        "type": "string",
                        "description": "The metric that should move, and in which direction, if the hypothesis is correct.",
                    },
                },
                "required": ["hypothesis", "experiment", "expected_signal"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["exception_summary", "experiments"],
    "additionalProperties": False,
}


@dataclass
class Experiment:
    hypothesis: str
    experiment: str
    expected_signal: str


@dataclass
class InsightResult:
    exception_summary: str
    experiments: list[Experiment] = field(default_factory=list)
    error: str | None = None


_CACHE: dict[str, InsightResult] = {}


def get_client() -> anthropic.Anthropic | None:
    """None if ANTHROPIC_API_KEY isn't set — callers should skip the AI
    call entirely (rest of the dashboard still works) rather than raising.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic()


def build_summary_payload(
    iqr_outliers_df,
    baseline_shift_df,
    ageing_wip_df,
    filters: dict | None = None,
    max_rows: int = 20,
) -> dict:
    """Structured-only payload for the AI call — no issue descriptions or
    comments, only computed metrics/flags plus coarse issue metadata.
    """
    outlier_cols = [
        "issue_key", "project", "issue_type", "priority", "stage",
        "duration_hours", "threshold_hours", "exceeded_by_hours",
    ]
    shift_cols = ["project", "stage", "baseline_median_hours", "recent_median_hours", "pct_change"]
    ageing_cols = ["issue_key", "project", "issue_type", "priority", "stage", "age_hours", "baseline_hours"]

    def _records(df, cols):
        if df is None or df.empty:
            return []
        available = [c for c in cols if c in df.columns]
        return df[available].head(max_rows).to_dict(orient="records")

    aged_only = ageing_wip_df[ageing_wip_df["is_aged"]] if ageing_wip_df is not None and not ageing_wip_df.empty else ageing_wip_df

    return {
        "filters": filters or {},
        "stage_outliers": _records(iqr_outliers_df, outlier_cols),
        "baseline_shifts": _records(baseline_shift_df, shift_cols),
        "ageing_wip": _records(aged_only, ageing_cols),
    }


def _cache_key(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def generate_insights(payload: dict) -> InsightResult:
    """Structured-in, structured-out. Never raises — API/parse failures
    come back as InsightResult.error so app.py doesn't need try/except.
    """
    client = get_client()
    if client is None:
        return InsightResult(
            exception_summary="",
            error="ANTHROPIC_API_KEY is not set — AI insights are disabled.",
        )

    key = _cache_key(payload)
    if key in _CACHE:
        return _CACHE[key]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Here are this period's flagged flow deviations, as structured "
                        "data (no ticket text). Summarize the exceptions and propose "
                        "improvement experiments.\n\n"
                        + json.dumps(payload, default=str)
                    ),
                }
            ],
        )
    except anthropic.APIConnectionError as exc:
        return InsightResult(exception_summary="", error=f"Could not reach Claude API: {exc}")
    except anthropic.APIStatusError as exc:
        return InsightResult(exception_summary="", error=f"Claude API error ({exc.status_code}): {exc.message}")

    text_block = next((b for b in response.content if getattr(b, "type", None) == "text"), None)
    if text_block is None:
        return InsightResult(exception_summary="", error="Claude returned no text content.")

    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError:
        return InsightResult(exception_summary="", error="Claude's response was not valid JSON.")

    result = InsightResult(
        exception_summary=data.get("exception_summary", ""),
        experiments=[Experiment(**e) for e in data.get("experiments", [])],
        error=None,
    )
    _CACHE[key] = result
    return result
