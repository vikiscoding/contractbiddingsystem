"""Tests for Teams Workflows Adaptive Card notify (mocked HTTP)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opportunity_ingest.notify import (
    NotifyError,
    build_adaptive_card_payload,
    build_ingest_alert_payload,
    notify_ingest_alert,
    post_teams_webhook,
    set_github_output_notified,
)


def test_build_adaptive_card_payload_structure():
    payload = build_adaptive_card_payload(
        title="Test alert",
        facts=[{"title": "Reason", "value": "hard_fail"}],
        body_text="Details here",
    )
    assert payload["type"] == "message"
    att = payload["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    card = att["content"]
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.4"
    assert any(b.get("text") == "Test alert" for b in card["body"])


def test_build_ingest_alert_payload_reasons():
    for reason in ("hard_fail", "partial_errors", "zero_new_streak"):
        p = build_ingest_alert_payload(
            reason=reason,
            run_url="https://github.com/org/repo/actions/runs/1",
            storage_backend="sqlite",
        )
        facts = p["attachments"][0]["content"]["body"][-1]["facts"]
        titles = {f["title"] for f in facts}
        assert "Reason" in titles
        assert "Run" in titles
        assert "Backend" in titles


def test_post_teams_webhook_empty_url():
    with pytest.raises(NotifyError, match="empty"):
        post_teams_webhook("", {"type": "message"})


def test_post_teams_webhook_success():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("opportunity_ingest.notify.urllib.request.urlopen", return_value=mock_resp) as m:
        post_teams_webhook(
            "https://example.webhook.office.com/webhookb2/test",
            {"type": "message", "attachments": []},
        )
        assert m.called
        req = m.call_args[0][0]
        assert req.full_url.startswith("https://example.webhook")
        body = json.loads(req.data.decode("utf-8"))
        assert body["type"] == "message"


def test_post_teams_webhook_http_error():
    import urllib.error

    with patch(
        "opportunity_ingest.notify.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "https://x", 400, "Bad Request", hdrs=None, fp=None  # type: ignore[arg-type]
        ),
    ):
        with pytest.raises(NotifyError, match="HTTP"):
            post_teams_webhook("https://example.com/hook", {"type": "message"})


def test_notify_ingest_alert_no_webhook_returns_false():
    assert (
        notify_ingest_alert(None, reason="hard_fail", set_github_output=False) is False
    )
    assert (
        notify_ingest_alert("  ", reason="hard_fail", set_github_output=False) is False
    )


def test_notify_ingest_alert_success_sets_github_output(tmp_path: Path, monkeypatch):
    out = tmp_path / "github_output"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    with patch("opportunity_ingest.notify.post_teams_webhook") as post:
        ok = notify_ingest_alert(
            "https://example.com/hook",
            reason="zero_new_streak",
            run_url="https://github.com/r/actions/runs/9",
            storage_backend="sqlite",
            extra_facts=[{"title": "Added", "value": "0"}],
        )
    assert ok is True
    post.assert_called_once()
    text = out.read_text(encoding="utf-8")
    assert "notified=true" in text


def test_notify_ingest_alert_failure_returns_false():
    with patch(
        "opportunity_ingest.notify.post_teams_webhook",
        side_effect=NotifyError("boom"),
    ):
        ok = notify_ingest_alert(
            "https://example.com/hook",
            reason="hard_fail",
            set_github_output=False,
        )
    assert ok is False


def test_set_github_output_notified_no_env(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    set_github_output_notified(True)  # no-op


def test_set_github_output_notified_writes(tmp_path: Path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    set_github_output_notified(True)
    set_github_output_notified(False)
    text = out.read_text(encoding="utf-8")
    assert "notified=true" in text
    assert "notified=false" in text
