"""Grok-assisted interpretation and ranking of stored opportunities.

Post-ingest only. Reads SQLite (or row dicts), never updates contract_opportunities
Status / Notes / RelevanceScore. Writes ranked JSON + Markdown reports under
``data/rankings/`` (or a caller-chosen path).

Requires optional extra: ``pip install -e ".[ai]"`` and ``XAI_API_KEY``.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

import yaml

UTC = timezone.utc
logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 12
DEFAULT_DESCRIPTION_CHARS = 1200
RANKINGS_SUBDIR = "rankings"

SYSTEM_PROMPT = """\
You are a capture analyst for a Canadian professional-services / IT firm.
You rank public tender opportunities against the firm's stated objectives.

Rules:
1. Use ONLY the opportunity text and company objectives provided. Do not invent
   buyers, budgets, or requirements not supported by the text.
2. Interpret the buyer's likely objective in plain language.
3. Rephrase the opportunity so a busy capture lead can scan it in 30 seconds.
4. Score fit_score 0–100 against the company's objectives (not keyword weight alone).
5. Be candid: false keyword hits and off-scope work get low scores.
6. Prefer technology / managed services / advisory that matches objectives;
   deprioritize construction, facilities, food design, pure creative ads, etc.
7. Return valid JSON only, matching the schema in the user message.
"""


class InterpretRankError(Exception):
    """User-facing failure for interpret-rank (config, API, parse)."""


class GrokClient(Protocol):
    """Minimal protocol so tests can inject a fake client."""

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Return parsed JSON object from the model."""
        ...


@dataclass(frozen=True, slots=True)
class CompanyObjectives:
    """Loaded from config/objectives.yaml."""

    version: int
    company: dict[str, Any]
    objectives: list[dict[str, Any]]
    guidance: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)

    def prompt_block(self) -> str:
        """Compact YAML-ish block for the model prompt."""
        payload = {
            "company": self.company,
            "objectives": self.objectives,
            "guidance": self.guidance,
        }
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


@dataclass(frozen=True, slots=True)
class RankedOpportunity:
    """One interpreted + ranked opportunity (report row)."""

    rank: int
    opportunity_id: str
    title: str
    buyer: str | None
    link: str
    closing_date: str | None
    keywords_matched: str | None
    rule_relevance_score: int | None
    fit_score: int
    recommendation: str
    plain_english: str
    interpreted_objective: str
    matched_objectives: list[str]
    why_it_fits: str
    risks_or_mismatches: str
    next_action: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InterpretRankResult:
    """Full run output (in-memory + paths when written)."""

    run_id: str
    model: str
    ranked: list[RankedOpportunity]
    input_count: int
    json_path: Path | None = None
    markdown_path: Path | None = None
    objectives_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "input_count": self.input_count,
            "ranked_count": len(self.ranked),
            "objectives_path": str(self.objectives_path) if self.objectives_path else None,
            "json_path": str(self.json_path) if self.json_path else None,
            "markdown_path": str(self.markdown_path) if self.markdown_path else None,
            "ranked": [r.as_dict() for r in self.ranked],
        }


def load_objectives(path: Path | str) -> CompanyObjectives:
    """Load and validate company objectives YAML."""
    p = Path(path)
    if not p.is_file():
        raise InterpretRankError(f"objectives file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InterpretRankError(f"failed to load objectives from {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise InterpretRankError(f"objectives root must be a mapping: {p}")
    company = raw.get("company") or {}
    objectives = raw.get("objectives") or []
    guidance = raw.get("guidance") or {}
    if not isinstance(company, dict):
        raise InterpretRankError("objectives.company must be a mapping")
    if not isinstance(objectives, list) or not objectives:
        raise InterpretRankError("objectives.objectives must be a non-empty list")
    if not isinstance(guidance, dict):
        raise InterpretRankError("objectives.guidance must be a mapping")
    version = int(raw.get("version") or 1)
    return CompanyObjectives(
        version=version,
        company=company,
        objectives=objectives,
        guidance=guidance,
        raw=raw,
    )


def _clean_text(value: object | None, max_chars: int | None = None) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value)).strip()
    # Collapse whitespace / HTML-ish noise lightly.
    text = re.sub(r"\s+", " ", text)
    if max_chars is not None and len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def prepare_opportunity_payload(
    rows: Sequence[Mapping[str, Any]],
    *,
    description_chars: int = DEFAULT_DESCRIPTION_CHARS,
) -> list[dict[str, Any]]:
    """Normalize store rows into compact model inputs."""
    out: list[dict[str, Any]] = []
    for row in rows:
        oid = _clean_text(row.get("OpportunityID"))
        title = _clean_text(row.get("Title"))
        if not oid or not title:
            continue
        out.append(
            {
                "opportunity_id": oid,
                "title": title,
                "buyer": _clean_text(row.get("Buyer")) or None,
                "category": _clean_text(row.get("Category")) or None,
                "description": _clean_text(row.get("Description"), description_chars) or None,
                "keywords_matched": _clean_text(row.get("KeywordsMatched")) or None,
                "rule_relevance_score": _as_int(row.get("RelevanceScore")),
                "status": _clean_text(row.get("Status")) or None,
                "published_date": _clean_text(row.get("PublishedDate")) or None,
                "closing_date": _clean_text(row.get("ClosingDate")) or None,
                "link": _clean_text(row.get("Link")) or None,
            }
        )
    return out


def _as_int(value: object | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filter_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    status: str | None = None,
    limit: int | None = None,
    min_rule_score: int | None = None,
) -> list[dict[str, Any]]:
    """Filter/sort opportunity rows before AI ranking.

    Sort seed: RelevanceScore DESC, then OpportunityID for stability.
    """
    items = [dict(r) for r in rows]
    if status:
        status_l = status.strip().lower()
        items = [
            r
            for r in items
            if _clean_text(r.get("Status")).lower() == status_l
        ]
    if min_rule_score is not None:
        items = [
            r
            for r in items
            if (_as_int(r.get("RelevanceScore")) or 0) >= min_rule_score
        ]

    def sort_key(r: Mapping[str, Any]) -> tuple[int, str]:
        score = _as_int(r.get("RelevanceScore")) or 0
        oid = _clean_text(r.get("OpportunityID"))
        return (-score, oid)

    items.sort(key=sort_key)
    if limit is not None and limit >= 0:
        items = items[:limit]
    return items


def build_user_prompt(
    objectives: CompanyObjectives,
    batch: Sequence[Mapping[str, Any]],
) -> str:
    """User message asking for structured JSON ranking of one batch."""
    schema_hint = {
        "rankings": [
            {
                "opportunity_id": "string (must match input)",
                "fit_score": "integer 0-100",
                "recommendation": "pursue | watch | pass",
                "plain_english": "2-4 sentence human rewrite",
                "interpreted_objective": "what the buyer is trying to achieve",
                "matched_objectives": ["objective id from company list"],
                "why_it_fits": "1-3 sentences",
                "risks_or_mismatches": "1-3 sentences",
                "next_action": "concrete next step for capture lead",
            }
        ]
    }
    return (
        "## Company objectives (frame of reference)\n"
        f"{objectives.prompt_block()}\n"
        "## Opportunities to interpret and rank\n"
        f"{json.dumps(list(batch), ensure_ascii=False, indent=2)}\n\n"
        "## Required JSON schema\n"
        f"{json.dumps(schema_hint, indent=2)}\n\n"
        "Return a single JSON object with key `rankings` covering EVERY opportunity "
        "in the batch (same opportunity_id values). Sort rankings by fit_score "
        "descending within this batch."
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse JSON object from model text (tolerates fenced markdown)."""
    raw = text.strip()
    if not raw:
        raise InterpretRankError("empty model response")
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Last resort: first { ... last }
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise InterpretRankError(
                f"model response is not JSON (first 200 chars): {text[:200]!r}"
            )
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise InterpretRankError(f"failed to parse model JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InterpretRankError("model JSON root must be an object")
    return data


class OpenAIGrokClient:
    """xAI Grok client via OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        model: str = "grok-4.5",
        timeout: float = 120.0,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise InterpretRankError(
                'openai package not installed; run: pip install -e ".[ai]"'
            ) from exc
        if not api_key or not api_key.strip():
            raise InterpretRankError("XAI_API_KEY is required for interpret-rank")
        self.model = model
        self._client = OpenAI(api_key=api_key.strip(), base_url=base_url, timeout=timeout)

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001 — surface any SDK/HTTP error
            raise InterpretRankError(f"Grok API call failed: {exc}") from exc
        try:
            content = resp.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise InterpretRankError(f"unexpected Grok response shape: {exc}") from exc
        return _extract_json_object(content)


def _clamp_score(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


def _normalize_recommendation(value: object) -> str:
    s = _clean_text(value).lower()
    if s in {"pursue", "bid", "go", "relevant"}:
        return "pursue"
    if s in {"watch", "monitor", "maybe", "review"}:
        return "watch"
    if s in {"pass", "skip", "discard", "no"}:
        return "pass"
    return s or "watch"


def merge_model_rankings(
    inputs: Sequence[Mapping[str, Any]],
    model_payload: Mapping[str, Any],
) -> list[RankedOpportunity]:
    """Join model rankings back to inputs; stable global rank by fit_score."""
    by_id = {str(item["opportunity_id"]): item for item in inputs}
    raw_list = model_payload.get("rankings")
    if not isinstance(raw_list, list):
        raise InterpretRankError("model JSON missing rankings[] array")

    seen: set[str] = set()
    partial: list[dict[str, Any]] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue
        oid = _clean_text(entry.get("opportunity_id"))
        if not oid or oid not in by_id or oid in seen:
            continue
        seen.add(oid)
        src = by_id[oid]
        matched = entry.get("matched_objectives") or []
        if isinstance(matched, str):
            matched_list = [matched]
        elif isinstance(matched, list):
            matched_list = [str(x) for x in matched if x is not None]
        else:
            matched_list = []
        partial.append(
            {
                "opportunity_id": oid,
                "title": src.get("title") or "",
                "buyer": src.get("buyer"),
                "link": src.get("link") or "",
                "closing_date": src.get("closing_date"),
                "keywords_matched": src.get("keywords_matched"),
                "rule_relevance_score": src.get("rule_relevance_score"),
                "fit_score": _clamp_score(entry.get("fit_score")),
                "recommendation": _normalize_recommendation(entry.get("recommendation")),
                "plain_english": _clean_text(entry.get("plain_english"))
                or _clean_text(src.get("description"), 400)
                or (src.get("title") or ""),
                "interpreted_objective": _clean_text(entry.get("interpreted_objective"))
                or "Not stated clearly in the notice text.",
                "matched_objectives": matched_list,
                "why_it_fits": _clean_text(entry.get("why_it_fits")) or "",
                "risks_or_mismatches": _clean_text(entry.get("risks_or_mismatches")) or "",
                "next_action": _clean_text(entry.get("next_action"))
                or "Open the notice Link and review eligibility.",
            }
        )

    # Any inputs the model skipped get a low default so the report is complete.
    for oid, src in by_id.items():
        if oid in seen:
            continue
        logger.warning("model omitted opportunity_id=%s; applying default pass", oid)
        partial.append(
            {
                "opportunity_id": oid,
                "title": src.get("title") or "",
                "buyer": src.get("buyer"),
                "link": src.get("link") or "",
                "closing_date": src.get("closing_date"),
                "keywords_matched": src.get("keywords_matched"),
                "rule_relevance_score": src.get("rule_relevance_score"),
                "fit_score": 0,
                "recommendation": "watch",
                "plain_english": _clean_text(src.get("description"), 400)
                or (src.get("title") or ""),
                "interpreted_objective": "Model did not return an interpretation.",
                "matched_objectives": [],
                "why_it_fits": "",
                "risks_or_mismatches": "Missing model output for this row.",
                "next_action": "Re-run interpret-rank or review manually via Link.",
            }
        )

    partial.sort(
        key=lambda r: (-int(r["fit_score"]), str(r["opportunity_id"])),
    )
    ranked: list[RankedOpportunity] = []
    for i, row in enumerate(partial, start=1):
        ranked.append(
            RankedOpportunity(
                rank=i,
                opportunity_id=str(row["opportunity_id"]),
                title=str(row["title"]),
                buyer=row.get("buyer"),  # type: ignore[arg-type]
                link=str(row.get("link") or ""),
                closing_date=row.get("closing_date"),  # type: ignore[arg-type]
                keywords_matched=row.get("keywords_matched"),  # type: ignore[arg-type]
                rule_relevance_score=row.get("rule_relevance_score"),  # type: ignore[arg-type]
                fit_score=int(row["fit_score"]),
                recommendation=str(row["recommendation"]),
                plain_english=str(row["plain_english"]),
                interpreted_objective=str(row["interpreted_objective"]),
                matched_objectives=list(row["matched_objectives"]),
                why_it_fits=str(row["why_it_fits"]),
                risks_or_mismatches=str(row["risks_or_mismatches"]),
                next_action=str(row["next_action"]),
            )
        )
    return ranked


def _chunk(items: Sequence[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        return [list(items)]
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def rank_opportunities(
    rows: Sequence[Mapping[str, Any]],
    objectives: CompanyObjectives,
    client: GrokClient,
    *,
    model_name: str = "grok-4.5",
    batch_size: int = DEFAULT_BATCH_SIZE,
    description_chars: int = DEFAULT_DESCRIPTION_CHARS,
    run_id: str | None = None,
) -> InterpretRankResult:
    """Call Grok in batches and return a globally ranked result (in-memory)."""
    prepared = prepare_opportunity_payload(rows, description_chars=description_chars)
    if not prepared:
        rid = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return InterpretRankResult(
            run_id=rid,
            model=model_name,
            ranked=[],
            input_count=0,
        )

    all_partial: list[RankedOpportunity] = []
    for batch in _chunk(prepared, batch_size):
        user = build_user_prompt(objectives, batch)
        payload = client.complete_json(system=SYSTEM_PROMPT, user=user)
        batch_ranked = merge_model_rankings(batch, payload)
        all_partial.extend(batch_ranked)

    # Re-rank across batches.
    all_partial.sort(key=lambda r: (-r.fit_score, r.opportunity_id))
    final: list[RankedOpportunity] = []
    for i, r in enumerate(all_partial, start=1):
        final.append(
            RankedOpportunity(
                rank=i,
                opportunity_id=r.opportunity_id,
                title=r.title,
                buyer=r.buyer,
                link=r.link,
                closing_date=r.closing_date,
                keywords_matched=r.keywords_matched,
                rule_relevance_score=r.rule_relevance_score,
                fit_score=r.fit_score,
                recommendation=r.recommendation,
                plain_english=r.plain_english,
                interpreted_objective=r.interpreted_objective,
                matched_objectives=list(r.matched_objectives),
                why_it_fits=r.why_it_fits,
                risks_or_mismatches=r.risks_or_mismatches,
                next_action=r.next_action,
            )
        )

    rid = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return InterpretRankResult(
        run_id=rid,
        model=model_name,
        ranked=final,
        input_count=len(prepared),
    )


def render_markdown(result: InterpretRankResult, objectives: CompanyObjectives) -> str:
    """Human-readable ranked brief for capture leads."""
    company_name = _clean_text((objectives.company or {}).get("name")) or "Company"
    lines: list[str] = [
        f"# Opportunity ranking brief — {result.run_id}",
        "",
        f"**Frame of reference:** {company_name}  ",
        f"**Model:** `{result.model}`  ",
        f"**Opportunities interpreted:** {result.input_count}  ",
        "",
        "Scores are **Grok fit** against `config/objectives.yaml`, not the rule-based "
        "`RelevanceScore` from ingest. Ingest rows are **not** modified.",
        "",
        "---",
        "",
    ]
    if not result.ranked:
        lines.append("_No opportunities to rank._")
        lines.append("")
        return "\n".join(lines)

    for r in result.ranked:
        buyer = r.buyer or "Unknown buyer"
        rule = r.rule_relevance_score if r.rule_relevance_score is not None else "—"
        matched = ", ".join(r.matched_objectives) if r.matched_objectives else "—"
        lines.extend(
            [
                f"## #{r.rank} — {r.title}",
                "",
                f"- **Fit score:** {r.fit_score}/100  ",
                f"- **Recommendation:** `{r.recommendation}`  ",
                f"- **Buyer:** {buyer}  ",
                f"- **OpportunityID:** `{r.opportunity_id}`  ",
                f"- **Closing:** {r.closing_date or '—'}  ",
                f"- **Keywords (ingest):** {r.keywords_matched or '—'}  ",
                f"- **Rule RelevanceScore:** {rule}  ",
                f"- **Matched objectives:** {matched}  ",
                f"- **Link:** {r.link or '—'}  ",
                "",
                "### Plain English",
                r.plain_english or "—",
                "",
                "### Interpreted buyer objective",
                r.interpreted_objective or "—",
                "",
                "### Why it fits",
                r.why_it_fits or "—",
                "",
                "### Risks / mismatches",
                r.risks_or_mismatches or "—",
                "",
                "### Next action",
                r.next_action or "—",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def write_reports(
    result: InterpretRankResult,
    objectives: CompanyObjectives,
    *,
    out_dir: Path,
    objectives_path: Path | None = None,
) -> InterpretRankResult:
    """Write JSON + Markdown under out_dir; return result with paths set."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"interpret-{result.run_id}.json"
    md_path = out_dir / f"interpret-{result.run_id}.md"
    payload = result.as_dict()
    payload["company"] = objectives.company
    payload["objectives"] = objectives.objectives
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(result, objectives), encoding="utf-8")
    return InterpretRankResult(
        run_id=result.run_id,
        model=result.model,
        ranked=result.ranked,
        input_count=result.input_count,
        json_path=json_path,
        markdown_path=md_path,
        objectives_path=objectives_path,
    )


def run_interpret_rank(
    rows: Sequence[Mapping[str, Any]],
    *,
    objectives_path: Path,
    api_key: str,
    base_url: str = "https://api.x.ai/v1",
    model: str = "grok-4.5",
    out_dir: Path,
    status: str | None = None,
    limit: int | None = None,
    min_rule_score: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    client_factory: Callable[..., GrokClient] | None = None,
) -> InterpretRankResult:
    """End-to-end: filter rows → Grok rank → write reports."""
    objectives = load_objectives(objectives_path)
    filtered = filter_rows(
        rows,
        status=status,
        limit=limit,
        min_rule_score=min_rule_score,
    )
    if client_factory is not None:
        client = client_factory(api_key=api_key, base_url=base_url, model=model)
    else:
        client = OpenAIGrokClient(api_key=api_key, base_url=base_url, model=model)
    result = rank_opportunities(
        filtered,
        objectives,
        client,
        model_name=model,
        batch_size=batch_size,
    )
    return write_reports(
        result,
        objectives,
        out_dir=out_dir,
        objectives_path=objectives_path,
    )
