"""Teams Workflows webhook notifications (Adaptive Card).

Python owns primary notify for hard fail, high partial errors, and zero-new
streak. Sets GitHub Actions step output ``notified=true`` so the workflow
backup step can skip double-notify.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0


def set_github_output_notified(notified: bool = True) -> None:
    """Append ``notified=true|false`` to ``GITHUB_OUTPUT`` when running in Actions."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    value = "true" if notified else "false"
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"notified={value}\n")
        logger.info("Wrote GITHUB_OUTPUT notified=%s", value)
    except OSError as exc:
        logger.warning("Could not write GITHUB_OUTPUT: %s", exc)


def build_adaptive_card_payload(
    *,
    title: str,
    facts: Sequence[Mapping[str, str]] | None = None,
    body_text: str | None = None,
) -> dict[str, Any]:
    """Build a Teams Workflows message with an Adaptive Card attachment."""
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "weight": "Bolder",
            "size": "Medium",
            "text": title,
            "wrap": True,
        }
    ]
    if body_text:
        body.append({"type": "TextBlock", "text": body_text, "wrap": True})
    if facts:
        body.append(
            {
                "type": "FactSet",
                "facts": [
                    {"title": str(f.get("title", "")), "value": str(f.get("value", ""))}
                    for f in facts
                ],
            }
        )
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body,
                },
            }
        ],
    }


def build_ingest_alert_payload(
    *,
    reason: str,
    run_url: str | None = None,
    storage_backend: str | None = None,
    extra_facts: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Standard CanadaBuys ingest alert card for hard fail / partial / streak."""
    title_by_reason = {
        "hard_fail": "CanadaBuys ingest hard failure",
        "partial_errors": "CanadaBuys ingest partial create errors",
        "zero_new_streak": "CanadaBuys ingest zero-new streak threshold",
    }
    title = title_by_reason.get(reason, f"CanadaBuys ingest alert ({reason})")
    facts: list[dict[str, str]] = [
        {"title": "Reason", "value": reason},
    ]
    if run_url:
        facts.append({"title": "Run", "value": run_url})
    if storage_backend:
        facts.append({"title": "Backend", "value": storage_backend})
    if extra_facts:
        facts.extend({"title": str(f["title"]), "value": str(f["value"])} for f in extra_facts)
    return build_adaptive_card_payload(title=title, facts=facts)


def post_teams_webhook(
    webhook_url: str,
    payload: Mapping[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """POST JSON payload to Teams Workflows webhook URL.

    Raises ``NotifyError`` on transport / non-2xx responses.
    """
    if not webhook_url or not webhook_url.strip():
        raise NotifyError("TEAMS_WEBHOOK_URL is empty")

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url.strip(),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status is not None and int(status) >= 300:
                raise NotifyError(f"Teams webhook returned HTTP {status}")
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"Teams webhook HTTP error: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise NotifyError(f"Teams webhook request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise NotifyError("Teams webhook request timed out") from exc


class NotifyError(Exception):
    """Teams webhook delivery failure (non-fatal to exit matrix; still logged)."""


def notify_ingest_alert(
    webhook_url: str | None,
    *,
    reason: str,
    run_url: str | None = None,
    storage_backend: str | None = None,
    extra_facts: Sequence[Mapping[str, str]] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    set_github_output: bool = True,
) -> bool:
    """Send ingest alert if webhook configured.

    Returns True if a notification was attempted and succeeded (and optionally
    sets ``notified=true`` for Actions). Returns False if webhook unset or send failed.
    """
    if not webhook_url or not str(webhook_url).strip():
        logger.warning(
            "Notify requested (reason=%s) but TEAMS_WEBHOOK_URL is not set",
            reason,
        )
        return False

    payload = build_ingest_alert_payload(
        reason=reason,
        run_url=run_url,
        storage_backend=storage_backend,
        extra_facts=extra_facts,
    )
    try:
        post_teams_webhook(str(webhook_url), payload, timeout=timeout)
    except NotifyError as exc:
        logger.error("Teams notify failed (reason=%s): %s", reason, exc)
        return False

    logger.info("Teams notify sent (reason=%s)", reason)
    if set_github_output:
        set_github_output_notified(True)
    return True
