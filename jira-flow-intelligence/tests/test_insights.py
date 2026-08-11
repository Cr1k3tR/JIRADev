import json
from unittest.mock import MagicMock

import anthropic
import pandas as pd
import pytest

import insights


@pytest.fixture(autouse=True)
def _clear_cache():
    insights._CACHE.clear()
    yield
    insights._CACHE.clear()


def test_get_client_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert insights.get_client() is None


def test_get_client_returns_client_when_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
    client = insights.get_client()
    assert isinstance(client, anthropic.Anthropic)


def test_generate_insights_short_circuits_without_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = insights.generate_insights({"stage_outliers": []})
    assert result.error is not None
    assert "ANTHROPIC_API_KEY" in result.error
    assert result.exception_summary == ""


def _fake_response(payload_dict):
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload_dict)
    response = MagicMock()
    response.content = [block]
    return response


def test_generate_insights_parses_structured_response(monkeypatch):
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        {
            "exception_summary": "Two stages are running slower than usual.",
            "experiments": [
                {
                    "hypothesis": "Review queue depth is causing the In Review backlog.",
                    "experiment": "Cap WIP in Review to 3 issues per reviewer.",
                    "expected_signal": "Median In Review duration should drop within 2 sprints.",
                }
            ],
        }
    )
    monkeypatch.setattr(insights, "get_client", lambda: fake_client)

    result = insights.generate_insights({"stage_outliers": [{"issue_key": "P-1"}]})

    assert result.error is None
    assert result.exception_summary == "Two stages are running slower than usual."
    assert len(result.experiments) == 1
    assert result.experiments[0].hypothesis.startswith("Review queue depth")
    fake_client.messages.create.assert_called_once()


def test_generate_insights_caches_by_payload(monkeypatch):
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        {"exception_summary": "ok", "experiments": []}
    )
    monkeypatch.setattr(insights, "get_client", lambda: fake_client)

    payload = {"stage_outliers": [{"issue_key": "CACHE-TEST"}]}
    first = insights.generate_insights(payload)
    second = insights.generate_insights(payload)

    assert first == second
    fake_client.messages.create.assert_called_once()  # second call was served from cache


def test_generate_insights_handles_invalid_json(monkeypatch):
    fake_client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "not valid json"
    response = MagicMock()
    response.content = [block]
    fake_client.messages.create.return_value = response
    monkeypatch.setattr(insights, "get_client", lambda: fake_client)

    result = insights.generate_insights({"stage_outliers": []})
    assert result.error is not None
    assert "not valid JSON" in result.error


def test_generate_insights_handles_api_status_error(monkeypatch):
    fake_client = MagicMock()

    fake_request = MagicMock()
    fake_response = MagicMock()
    fake_response.status_code = 401
    fake_response.headers = {}
    fake_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="invalid x-api-key",
        response=fake_response,
        body=None,
    )
    monkeypatch.setattr(insights, "get_client", lambda: fake_client)

    result = insights.generate_insights({"stage_outliers": []})
    assert result.error is not None
    assert "Claude API error" in result.error


def test_build_summary_payload_never_includes_free_text_fields():
    outliers = pd.DataFrame(
        [
            {
                "issue_key": "P-1", "project": "P", "issue_type": "Bug", "priority": "High",
                "stage": "In Review", "duration_hours": 50.0, "threshold_hours": 20.0,
                "exceeded_by_hours": 30.0, "description": "some ticket text that must never leak",
            }
        ]
    )
    empty = pd.DataFrame()

    payload = insights.build_summary_payload(outliers, empty, empty)

    assert "description" not in json.dumps(payload)
    assert payload["stage_outliers"][0]["issue_key"] == "P-1"
