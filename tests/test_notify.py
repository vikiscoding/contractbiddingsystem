"""Tests for Teams Workflows Adaptive Card notify (mocked HTTP)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opportunity_ingest.notify import (
    MatchAlertItem,
    NotifyError,
    build_adaptive_card_payload,
    build_ingest_alert_payload,
    build_match_alert_payload,
    filter_match_items,
    match_items_from_ranked,
    notify_ingest_alert,
    notify_match_alerts,
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
    assert set_github_output_notified(True) is True  # no handoff needed


def test_set_github_output_notified_writes(tmp_path: Path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert set_github_output_notified(True) is True
    assert set_github_output_notified(False) is True
    text = out.read_text(encoding="utf-8")
    assert "notified=true" in text
    assert "notified=false" in text


def test_set_github_output_raises_when_unwritable(tmp_path: Path, monkeypatch):
    # Point at a path whose parent cannot be written as a file (directory as file).
    bad = tmp_path / "not_a_file_dir"
    bad.mkdir()
    monkeypatch.setenv("GITHUB_OUTPUT", str(bad))  # open() on a directory fails
    with pytest.raises(NotifyError, match="GITHUB_OUTPUT unwritable"):
        set_github_output_notified(True)


def test_notify_returns_false_when_github_output_handoff_fails(
    tmp_path: Path, monkeypatch
):
    """Teams POST succeeded but GITHUB_OUTPUT failed → do not claim notified."""
    bad = tmp_path / "dir_as_output"
    bad.mkdir()
    monkeypatch.setenv("GITHUB_OUTPUT", str(bad))
    with patch("opportunity_ingest.notify.post_teams_webhook") as post:
        ok = notify_ingest_alert(
            "https://example.com/hook",
            reason="hard_fail",
            set_github_output=True,
        )
    assert post.called
    assert ok is False


def _sample_match(score: int = 55, oid: str = "ID-1") -> MatchAlertItem:
    return MatchAlertItem(
        title="Cloud RFP for Copilot enablement",
        opportunity_id=oid,
        link=f"https://example.com/notice/{oid}",
        score=score,
        score_kind="RelevanceScore",
        buyer="PSPC",
        keywords="copilot, power platform",
        summary="Buyer wants Microsoft-native AI under human governance.",
        recommendation="pursue",
        closing_date="2026-09-01T00:00:00Z",
    )


def test_filter_match_items_threshold():
    items = [_sample_match(55), _sample_match(30, "LOW"), _sample_match(90, "HI")]
    out = filter_match_items(items, threshold=40)
    assert [i.opportunity_id for i in out] == ["HI", "ID-1"]


def test_build_match_alert_payload_has_cta_and_truncation():
    items = [_sample_match(52, "WS-AI"), _sample_match(41, "WS-IAM")]
    payload = build_match_alert_payload(items, threshold=40, source="ingest")
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert "actions" in card
    assert card["actions"][0]["type"] == "Action.OpenUrl"
    assert "https://example.com/notice/WS-AI" in card["actions"][0]["url"]
    body_text = " ".join(
        str(b.get("text", "")) for b in card["body"] if isinstance(b, dict)
    )
    assert "52/100" in body_text or "52" in body_text


def test_notify_match_alerts_success():
    with patch("opportunity_ingest.notify.post_teams_webhook") as post:
        ok = notify_match_alerts(
            "https://example.com/hook",
            [_sample_match(60)],
            threshold=40,
            source="ingest",
        )
    assert ok is True
    post.assert_called_once()


def test_notify_match_alerts_below_threshold_skips():
    with patch("opportunity_ingest.notify.post_teams_webhook") as post:
        ok = notify_match_alerts(
            "https://example.com/hook",
            [_sample_match(10)],
            threshold=40,
        )
    assert ok is False
    post.assert_not_called()


def test_notify_match_alerts_disabled():
    with patch("opportunity_ingest.notify.post_teams_webhook") as post:
        ok = notify_match_alerts(
            "https://example.com/hook",
            [_sample_match(90)],
            enabled=False,
        )
    assert ok is False
    post.assert_not_called()


def test_match_items_from_ranked_dicts():
    ranked = [
        {
            "fit_score": 52,
            "title": "AI ITQ",
            "opportunity_id": "X",
            "link": "https://example.com/x",
            "plain_english": "Source list for AI",
            "recommendation": "watch",
            "buyer": "PSPC",
            "keywords_matched": "artificial intelligence",
        },
        {
            "fit_score": 5,
            "title": "Elevator",
            "opportunity_id": "Y",
            "link": "https://example.com/y",
        },
    ]
    items = match_items_from_ranked(ranked, threshold=40)
    assert len(items) == 1
    assert items[0].score == 52
    assert items[0].score_kind == "GrokFit"
