"""Keyword filter against TenderRecord title/description/(optional category).

Any-match: a row is a hit if any configured term matches. Short terms
(len <= short_term_max_len) use word-boundary regex to avoid substring noise.

Scoring uses unique matched term weights. Nested overlaps are resolved
**span-aware**: a shorter term is dropped only when every match span is fully
covered by a longer matched term's span (e.g. ``managed service`` inside
``managed services``). Independent occurrences still count
(e.g. ``workflow automation and general automation`` keeps both).

A term listed in multiple groups contributes **one** weight but attributes
**all** declaring groups (for multi-group diversity bonus).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from opportunity_ingest.models import TenderRecord

# Logical field names allowed in match.fields
ALLOWED_SEARCH_FIELDS = frozenset({"title", "description"})
DEFAULT_SEARCH_FIELDS: tuple[str, ...] = ("title", "description")


class KeywordConfigError(Exception):
    """Invalid or unreadable keywords.yaml."""


@dataclass(frozen=True, slots=True)
class KeywordTerm:
    term: str
    weight: int
    group: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class KeywordConfig:
    """Parsed keyword configuration (engineering-owned YAML)."""

    version: int
    case_sensitive: bool
    search_category: bool
    short_term_max_len: int
    fields: tuple[str, ...]
    terms: tuple[KeywordTerm, ...]
    category_boosts: Mapping[str, int]
    group_labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KeywordMatchResult:
    """Outcome of filtering one tender.

    ``terms`` are unique matched term strings after span-aware nested suppression
    (stable first-seen order among survivors).
    ``groups`` are unique group ids from surviving terms (all declaring groups
    for dual-listed terms).
    ``weights`` maps matched term → weight (for scoring; one weight per term).
    """

    matched: bool
    terms: tuple[str, ...]
    groups: tuple[str, ...]
    weights: Mapping[str, int]


# Inclusive-exclusive character span in the search blob: [start, end).
Span = tuple[int, int]


def _as_int(value: object, *, context: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise KeywordConfigError(f"Invalid integer for {context}: {value!r}") from exc


def _compile_pattern(
    term: str,
    *,
    case_sensitive: bool,
    short_term_max_len: int,
) -> re.Pattern[str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    escaped = re.escape(term)
    if len(term) <= short_term_max_len:
        # Word-boundary match for short tokens (rpa, msp, llm, itsm, ...).
        pattern = rf"\b{escaped}\b"
    else:
        pattern = escaped
    return re.compile(pattern, flags)


def load_keyword_config(path: str | Path) -> KeywordConfig:
    """Load and validate ``config/keywords.yaml``."""
    p = Path(path)
    try:
        raw_text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise KeywordConfigError(f"Cannot read keywords file: {p}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise KeywordConfigError(f"Invalid YAML in {p}: {exc}") from exc

    if not isinstance(data, dict):
        raise KeywordConfigError(f"Keywords root must be a mapping: {p}")

    return _parse_keyword_config(data, source=str(p))


def _parse_fields(match: Mapping[str, Any], *, source: str) -> tuple[str, ...]:
    raw = match.get("fields", list(DEFAULT_SEARCH_FIELDS))
    if not isinstance(raw, list) or not raw:
        raise KeywordConfigError(
            f"'match.fields' must be a non-empty list in {source}"
        )
    fields: list[str] = []
    for item in raw:
        name = str(item).strip().lower()
        if name not in ALLOWED_SEARCH_FIELDS:
            raise KeywordConfigError(
                f"Unknown search field {item!r} in {source}; "
                f"allowed: {sorted(ALLOWED_SEARCH_FIELDS)}"
            )
        if name not in fields:
            fields.append(name)
    return tuple(fields)


def _parse_keyword_config(data: Mapping[str, Any], *, source: str) -> KeywordConfig:
    match = data.get("match") or {}
    if not isinstance(match, Mapping):
        raise KeywordConfigError(f"'match' must be a mapping in {source}")

    case_sensitive = bool(match.get("case_sensitive", False))
    search_category = bool(match.get("search_category", True))
    short_term_max_len = _as_int(
        match.get("short_term_max_len", 4),
        context=f"match.short_term_max_len in {source}",
    )
    version = _as_int(data.get("version", 1), context=f"version in {source}")
    fields = _parse_fields(match, source=source)

    groups_raw = data.get("groups") or {}
    if not isinstance(groups_raw, Mapping) or not groups_raw:
        raise KeywordConfigError(f"'groups' must be a non-empty mapping in {source}")

    terms: list[KeywordTerm] = []
    group_labels: dict[str, str] = {}
    for group_id, group_body in groups_raw.items():
        if not isinstance(group_body, Mapping):
            raise KeywordConfigError(f"Group {group_id!r} must be a mapping in {source}")
        group_labels[str(group_id)] = str(group_body.get("label") or group_id)
        kws = group_body.get("keywords") or []
        if not isinstance(kws, list):
            raise KeywordConfigError(f"Group {group_id!r} keywords must be a list in {source}")
        for item in kws:
            if not isinstance(item, Mapping):
                raise KeywordConfigError(
                    f"Keyword entry in group {group_id!r} must be a mapping in {source}"
                )
            term = str(item.get("term", "")).strip()
            if not term:
                continue
            weight = _as_int(
                item.get("weight", 0),
                context=f"weight for term {term!r} in group {group_id!r} ({source})",
            )
            pattern = _compile_pattern(
                term,
                case_sensitive=case_sensitive,
                short_term_max_len=short_term_max_len,
            )
            terms.append(
                KeywordTerm(term=term, weight=weight, group=str(group_id), pattern=pattern)
            )

    if not terms:
        raise KeywordConfigError(f"No keywords defined in {source}")

    boosts_raw = data.get("category_boosts") or {}
    if not isinstance(boosts_raw, Mapping):
        raise KeywordConfigError(f"'category_boosts' must be a mapping in {source}")
    category_boosts: dict[str, int] = {}
    for k, v in boosts_raw.items():
        category_boosts[str(k)] = _as_int(
            v, context=f"category_boosts[{k!r}] in {source}"
        )

    return KeywordConfig(
        version=version,
        case_sensitive=case_sensitive,
        search_category=search_category,
        short_term_max_len=short_term_max_len,
        fields=fields,
        terms=tuple(terms),
        category_boosts=category_boosts,
        group_labels=group_labels,
    )


def _search_blob(
    tender: TenderRecord,
    *,
    fields: Sequence[str],
    search_category: bool,
) -> str:
    """Concatenate configured searchable fields (+ category when enabled)."""
    parts: list[str] = []
    for name in fields:
        if name == "title":
            parts.append(tender.title or "")
        elif name == "description":
            if tender.description:
                parts.append(tender.description)
    if search_category and tender.procurement_category:
        parts.append(tender.procurement_category)
    return "\n".join(parts)


def _span_contained(inner: Span, outer: Span) -> bool:
    """True if ``inner`` lies entirely within ``outer`` (half-open intervals)."""
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def suppress_nested_by_spans(
    term_order: Sequence[str],
    term_spans: Mapping[str, Sequence[Span]],
) -> list[str]:
    """Drop a term only when every match span is covered by a longer term.

    A shorter term is kept if it has **any** independent occurrence whose
    span is not fully nested inside a longer matched term's span.

    Preserves first-seen order among survivors. Unique-by-term is assumed
    (``term_order`` has no duplicates).
    """
    if len(term_order) <= 1:
        return list(term_order)

    kept: list[str] = []
    for term in term_order:
        spans = term_spans.get(term) or ()
        if not spans:
            continue
        longer = [u for u in term_order if len(u) > len(term) and u in term_spans]
        has_independent = False
        for span in spans:
            covered = False
            for longer_term in longer:
                for outer in term_spans[longer_term]:
                    if _span_contained(span, outer):
                        covered = True
                        break
                if covered:
                    break
            if not covered:
                has_independent = True
                break
        if has_independent:
            kept.append(term)
    return kept


def suppress_nested_terms(terms: Sequence[str]) -> list[str]:
    """Legacy string-nesting helper (no blob spans).

    Prefer :func:`suppress_nested_by_spans` for production matching. Kept for
    simple unit tests of pure term-string nesting without a search blob.
    """
    if len(terms) <= 1:
        return list(terms)

    by_len = sorted(terms, key=lambda t: len(t), reverse=True)
    kept_norm: list[str] = []
    kept_original: list[str] = []
    for t in by_len:
        norm = t.casefold()
        if any(norm != longer and norm in longer for longer in kept_norm):
            continue
        kept_norm.append(norm)
        kept_original.append(t)

    survivors = set(kept_original)
    return [t for t in terms if t in survivors]


def match_keywords(tender: TenderRecord, config: KeywordConfig) -> KeywordMatchResult:
    """Return matched terms/groups for one tender (any-match semantics)."""
    blob = _search_blob(
        tender,
        fields=config.fields,
        search_category=config.search_category,
    )

    # term -> weight (first listing wins); groups; all match spans in blob
    weights: dict[str, int] = {}
    term_order: list[str] = []
    term_groups: dict[str, list[str]] = {}
    term_spans: dict[str, list[Span]] = {}

    for kt in config.terms:
        if kt.term not in term_spans:
            spans = [(m.start(), m.end()) for m in kt.pattern.finditer(blob)]
            if not spans:
                continue
            term_spans[kt.term] = spans
            weights[kt.term] = kt.weight
            term_order.append(kt.term)
            term_groups[kt.term] = []
        # Dual-listed terms: attribute every declaring group (one weight).
        if kt.term in term_spans and kt.group not in term_groups[kt.term]:
            term_groups[kt.term].append(kt.group)

    kept_terms = suppress_nested_by_spans(term_order, term_spans)
    kept_weights = {t: weights[t] for t in kept_terms}

    groups_order: list[str] = []
    groups_set: set[str] = set()
    for t in kept_terms:
        for g in term_groups.get(t, ()):
            if g not in groups_set:
                groups_set.add(g)
                groups_order.append(g)

    return KeywordMatchResult(
        matched=bool(kept_terms),
        terms=tuple(kept_terms),
        groups=tuple(groups_order),
        weights=kept_weights,
    )


def filter_tenders(
    tenders: list[TenderRecord],
    config: KeywordConfig,
) -> list[tuple[TenderRecord, KeywordMatchResult]]:
    """Keep only tenders with at least one keyword match."""
    out: list[tuple[TenderRecord, KeywordMatchResult]] = []
    for tender in tenders:
        result = match_keywords(tender, config)
        if result.matched:
            out.append((tender, result))
    return out
