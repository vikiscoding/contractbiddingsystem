"""Teams Workflows webhook notifications (Adaptive Card).

Two pipelines share this module:

1. **Ops alerts** — hard fail, partial errors, zero-new streak
   (``notify_ingest_alert`` / ``TEAMS_WEBHOOK_URL``).
2. **Match alerts** — new opportunities or Grok ranks at/above score threshold
   (``notify_match_alerts`` / ``TEAMS_MATCH_WEBHOOK_URL`` or ops fallback).
   Call-to-action cards include truncated summaries + OpenUrl actions.

On successful ops notify POST, sets GitHub Actions step output ``notified=true``
so the workflow backup step can skip double-notify
(``failure() && steps.ingest.outputs.notified != 'true'``).

**GITHUB_OUTPUT ownership (KD-18):** When ``GITHUB_OUTPUT`` is set, notify
ownership is complete only if that file is written after a successful webhook
POST. Write is retried once; persistent failure logs at ERROR and returns
``False`` (does not claim ``notified=true``). In that edge case Actions may
still double-notify on job failure — operators should treat GITHUB_OUTPUT I/O
errors as critical. When ``GITHUB_OUTPUT`` is unset (local runs), POST success
alone is enough.

Match alerts do **not** set ``notified=true`` (ops ownership handoff only).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MATCH_THRESHOLD = 40
DEFAULT_MATCH_MAX_ITEMS = 8
DEFAULT_TITLE_MAX = 120
DEFAULT_SUMMARY_MAX = 280


class NotifyError(Exception):
    """Teams webhook or GITHUB_OUTPUT handoff failure (non-fatal to exit matrix)."""


@dataclass(frozen=True, slots=True)
class MatchAlertItem:
    """One high-match opportunity for a Teams capture ping."""

    title: str
    opportunity_id: str
    link: str
    score: int
    score_kind: str  # e.g. RelevanceScore | GrokFit
    buyer: str | None = None
    keywords: str | None = None
    summary: str | None = None
    recommendation: str | None = None
    closing_date: str | None = None


def set_github_output_notified(notified: bool = True) -> bool:
    """Append ``notified=true|false`` to ``GITHUB_OUTPUT`` when running in Actions.

    Returns:
        True if env is unset (no handoff needed) or write succeeded.

    Raises:
        NotifyError: if ``GITHUB_OUTPUT`` is set but unwritable after one retry.
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return True
    value = "true" if notified else "false"
    last_exc: OSError | None = None
    for attempt in range(2):
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"notified={value}\n")
            logger.info("Wrote GITHUB_OUTPUT notified=%s", value)
            return True
        except OSError as exc:
            last_exc = exc
            logger.warning(
                "GITHUB_OUTPUT write attempt %s/2 failed (%s): %s",
                attempt + 1,
                path,
                exc,
            )
    raise NotifyError(
        f"GITHUB_OUTPUT unwritable after retry ({path}): {last_exc}. "
        "Teams may already have been notified; Actions failure backup may "
        "double-notify if job exits non-zero."
    )


def _truncate(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if len(s) <= max_chars:
        return s
    if max_chars <= 1:
        return s[:max_chars]
    return s[: max_chars - 1].rstrip() + "…"


def build_adaptive_card_payload(
    *,
    title: str,
    facts: Sequence[Mapping[str, str]] | None = None,
    body_text: str | None = None,
    actions: Sequence[Mapping[str, Any]] | None = None,
    extra_body: Sequence[Mapping[str, Any]] | None = None,
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
    if extra_body:
        body.extend(dict(b) for b in extra_body)
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
    card: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    if actions:
        card["actions"] = [dict(a) for a in actions]
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


def filter_match_items(
    items: Sequence[MatchAlertItem],
    *,
    threshold: int = DEFAULT_MATCH_THRESHOLD,
) -> list[MatchAlertItem]:
    """Return items with score >= threshold, highest score first."""
    thr = max(0, min(100, int(threshold)))
    filtered = [i for i in items if int(i.score) >= thr and (i.link or "").strip()]
    filtered.sort(key=lambda i: (-int(i.score), i.opportunity_id))
    return filtered


def build_match_alert_payload(
    items: Sequence[MatchAlertItem],
    *,
    threshold: int = DEFAULT_MATCH_THRESHOLD,
    source: str = "ingest",
    run_url: str | None = None,
    max_items: int = DEFAULT_MATCH_MAX_ITEMS,
    title_max_chars: int = DEFAULT_TITLE_MAX,
    summary_max_chars: int = DEFAULT_SUMMARY_MAX,
    card_title: str | None = None,
    cta_label: str = "Open notice",
) -> dict[str, Any]:
    """Adaptive Card: high-match opportunities with summary + OpenUrl CTAs.

    ``source`` is ``ingest`` (rule score) or ``interpret-rank`` (Grok fit).
    """
    matched = filter_match_items(items, threshold=threshold)
    if not matched:
        raise NotifyError("no match items at or above threshold")

    cap = max(1, int(max_items))
    shown = matched[:cap]
    hidden = len(matched) - len(shown)

    if card_title:
        title = card_title
    elif source == "interpret-rank":
        title = f"Grok fit matches (≥{threshold})"
    else:
        title = f"New opportunity matches (≥{threshold})"

    intro = (
        f"**{len(matched)}** high-match opportunit"
        f"{'y' if len(matched) == 1 else 'ies'} "
        f"(threshold **{threshold}/100**, source `{source}`). "
        "Review links and act — Status stays human-owned in the store."
    )
    if hidden > 0:
        intro += f" Showing top {len(shown)}; **{hidden}** more not listed."

    extra_body: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for idx, item in enumerate(shown, start=1):
        t = _truncate(item.title, title_max_chars) or item.opportunity_id
        summary = _truncate(item.summary, summary_max_chars)
        buyer = _truncate(item.buyer, 80) or "—"
        kws = _truncate(item.keywords, 100) or "—"
        rec = (item.recommendation or "").strip()
        lines = [
            f"**#{idx} · {item.score}/100** ({item.score_kind})"
            + (f" · `{rec}`" if rec else ""),
            t,
            f"Buyer: {buyer} · ID: `{item.opportunity_id}`",
            f"Keywords: {kws}",
        ]
        if item.closing_date:
            lines.append(f"Closing: {item.closing_date}")
        if summary:
            lines.append(summary)
        extra_body.append(
            {
                "type": "TextBlock",
                "text": "\n\n".join(lines),
                "wrap": True,
                "separator": True,
            }
        )
        link = (item.link or "").strip()
        if link.startswith(("http://", "https://")):
            # Teams shows a limited number of card actions; label uniquely.
            label = f"{cta_label} #{idx}"
            if len(label) > 40:
                label = f"Open #{idx}"
            actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": label,
                    "url": link,
                }
            )

    facts: list[dict[str, str]] = [
        {"title": "Threshold", "value": str(threshold)},
        {"title": "Matches", "value": str(len(matched))},
        {"title": "Source", "value": source},
    ]
    if run_url:
        facts.append({"title": "Run", "value": run_url})

    # Adaptive Cards: too many actions can be dropped by Teams; keep first 6.
    return build_adaptive_card_payload(
        title=title,
        body_text=intro,
        extra_body=extra_body,
        facts=facts,
        actions=actions[:6] if actions else None,
    )


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

    Returns True only when ownership is complete:
    - webhook POST succeeded, and
    - if ``set_github_output`` and ``GITHUB_OUTPUT`` is set: handoff write succeeded.

    Returns False if webhook unset, POST failed, or GITHUB_OUTPUT handoff failed
    after a successful POST (does **not** claim notified ownership; dual-notify
    risk remains for non-zero job exits — logged at ERROR).
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
        try:
            set_github_output_notified(True)
        except NotifyError as exc:
            # Do not claim notified=True: Actions backup keys off GITHUB_OUTPUT.
            logger.error(
                "Teams notify delivered (reason=%s) but GITHUB_OUTPUT handoff "
                "failed — not claiming notified ownership: %s",
                reason,
                exc,
            )
            return False
    return True


def notify_match_alerts(
    webhook_url: str | None,
    items: Sequence[MatchAlertItem],
    *,
    threshold: int = DEFAULT_MATCH_THRESHOLD,
    source: str = "ingest",
    run_url: str | None = None,
    max_items: int = DEFAULT_MATCH_MAX_ITEMS,
    enabled: bool = True,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    title_max_chars: int = DEFAULT_TITLE_MAX,
    summary_max_chars: int = DEFAULT_SUMMARY_MAX,
    card_title: str | None = None,
    cta_label: str = "Open notice",
) -> bool:
    """Post a capture-channel Adaptive Card for high-match opportunities.

    Returns True when a card was POSTed successfully.
    Returns False when disabled, no webhook, no items above threshold, or POST fails.
    Does **not** write GITHUB_OUTPUT (ops double-notify handoff is separate).
    """
    if not enabled:
        logger.info("Match notify disabled; skipping (source=%s)", source)
        return False
    if not webhook_url or not str(webhook_url).strip():
        logger.warning(
            "Match notify skipped (source=%s): no TEAMS_MATCH_WEBHOOK_URL / "
            "TEAMS_WEBHOOK_URL",
            source,
        )
        return False

    matched = filter_match_items(items, threshold=threshold)
    if not matched:
        logger.info(
            "Match notify: no items with score>=%s (source=%s, candidates=%s)",
            threshold,
            source,
            len(items),
        )
        return False

    try:
        payload = build_match_alert_payload(
            matched,
            threshold=threshold,
            source=source,
            run_url=run_url,
            max_items=max_items,
            title_max_chars=title_max_chars,
            summary_max_chars=summary_max_chars,
            card_title=card_title,
            cta_label=cta_label,
        )
        post_teams_webhook(str(webhook_url), payload, timeout=timeout)
    except NotifyError as exc:
        logger.error("Teams match notify failed (source=%s): %s", source, exc)
        return False

    logger.info(
        "Teams match notify sent (source=%s, matches=%s, threshold=%s)",
        source,
        len(matched),
        threshold,
    )
    return True


def match_items_from_opportunity_fields(
    fields_list: Sequence[Any],
    *,
    threshold: int = DEFAULT_MATCH_THRESHOLD,
) -> list[MatchAlertItem]:
    """Build match items from ``OpportunityFields`` (or duck-typed) for ingest."""
    items: list[MatchAlertItem] = []
    for f in fields_list:
        try:
            score = int(getattr(f, "RelevanceScore", 0) or 0)
        except (TypeError, ValueError):
            score = 0
        if score < threshold:
            continue
        link = str(getattr(f, "Link", "") or "").strip()
        if not link:
            continue
        desc = getattr(f, "Description", None)
        items.append(
            MatchAlertItem(
                title=str(getattr(f, "Title", "") or ""),
                opportunity_id=str(getattr(f, "OpportunityID", "") or ""),
                link=link,
                score=score,
                score_kind="RelevanceScore",
                buyer=getattr(f, "Buyer", None),
                keywords=getattr(f, "KeywordsMatched", None),
                summary=str(desc) if desc else None,
                recommendation=None,
                closing_date=(
                    str(getattr(f, "ClosingDate"))
                    if getattr(f, "ClosingDate", None) is not None
                    else None
                ),
            )
        )
    return items


def match_items_from_ranked(
    ranked: Sequence[Any],
    *,
    threshold: int = DEFAULT_MATCH_THRESHOLD,
) -> list[MatchAlertItem]:
    """Build match items from ``RankedOpportunity`` (or dicts) for interpret-rank."""
    items: list[MatchAlertItem] = []
    for r in ranked:
        if isinstance(r, Mapping):
            score = int(r.get("fit_score") or 0)
            link = str(r.get("link") or "").strip()
            if score < threshold or not link:
                continue
            items.append(
                MatchAlertItem(
                    title=str(r.get("title") or ""),
                    opportunity_id=str(r.get("opportunity_id") or ""),
                    link=link,
                    score=score,
                    score_kind="GrokFit",
                    buyer=r.get("buyer"),  # type: ignore[arg-type]
                    keywords=r.get("keywords_matched"),  # type: ignore[arg-type]
                    summary=str(r.get("plain_english") or r.get("interpreted_objective") or ""),
                    recommendation=str(r.get("recommendation") or "") or None,
                    closing_date=str(r.get("closing_date") or "") or None,
                )
            )
            continue
        try:
            score = int(getattr(r, "fit_score", 0) or 0)
        except (TypeError, ValueError):
            score = 0
        link = str(getattr(r, "link", "") or "").strip()
        if score < threshold or not link:
            continue
        items.append(
            MatchAlertItem(
                title=str(getattr(r, "title", "") or ""),
                opportunity_id=str(getattr(r, "opportunity_id", "") or ""),
                link=link,
                score=score,
                score_kind="GrokFit",
                buyer=getattr(r, "buyer", None),
                keywords=getattr(r, "keywords_matched", None),
                summary=str(
                    getattr(r, "plain_english", None)
                    or getattr(r, "interpreted_objective", None)
                    or ""
                )
                or None,
                recommendation=getattr(r, "recommendation", None),
                closing_date=getattr(r, "closing_date", None),
            )
        )
    return items
