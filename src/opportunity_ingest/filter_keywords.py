"""Keyword filter against TenderRecord title/description/(optional category).

Any-match: a row is a hit if any configured term matches. Short terms
(len <= short_term_max_len) use word-boundary regex to avoid substring noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from opportunity_ingest.models import TenderRecord


class KeywordConfigError(Exception):
    """Invalid or unreadable keywords.yaml."""


@dataclass(frozen=True, slots=True)
class KeywordTerm:
    term: str
    weight: int
    group: str


@dataclass(frozen=True, slots=True)
class KeywordConfig:
    """Parsed keyword configuration (engineering-owned YAML)."""

    version: int
    case_sensitive: bool
    search_category: bool
    short_term_max_len: int
    terms: tuple[KeywordTerm, ...]
    category_boosts: Mapping[str, int]
    group_labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KeywordMatchResult:
    """Outcome of filtering one tender.

    ``terms`` are unique matched term strings (stable first-seen order).
    ``groups`` are unique group ids that contributed at least one match.
    ``weights`` maps matched term → weight (for scoring).
    """

    matched: bool
    terms: tuple[str, ...]
    groups: tuple[str, ...]
    weights: Mapping[str, int]


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


def _parse_keyword_config(data: Mapping[str, Any], *, source: str) -> KeywordConfig:
    match = data.get("match") or {}
    if not isinstance(match, Mapping):
        raise KeywordConfigError(f"'match' must be a mapping in {source}")

    case_sensitive = bool(match.get("case_sensitive", False))
    search_category = bool(match.get("search_category", True))
    short_term_max_len = int(match.get("short_term_max_len", 4))
    version = int(data.get("version", 1))

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
            weight = int(item.get("weight", 0))
            terms.append(KeywordTerm(term=term, weight=weight, group=str(group_id)))

    if not terms:
        raise KeywordConfigError(f"No keywords defined in {source}")

    boosts_raw = data.get("category_boosts") or {}
    if not isinstance(boosts_raw, Mapping):
        raise KeywordConfigError(f"'category_boosts' must be a mapping in {source}")
    category_boosts = {str(k): int(v) for k, v in boosts_raw.items()}

    return KeywordConfig(
        version=version,
        case_sensitive=case_sensitive,
        search_category=search_category,
        short_term_max_len=short_term_max_len,
        terms=tuple(terms),
        category_boosts=category_boosts,
        group_labels=group_labels,
    )


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


def _search_blob(tender: TenderRecord, *, search_category: bool) -> str:
    """Concatenate searchable fields with separators (any-match on joined text)."""
    parts: list[str] = [tender.title or ""]
    if tender.description:
        parts.append(tender.description)
    if search_category:
        if tender.procurement_category:
            parts.append(tender.procurement_category)
    return "\n".join(parts)


def match_keywords(tender: TenderRecord, config: KeywordConfig) -> KeywordMatchResult:
    """Return matched terms/groups for one tender (any-match semantics)."""
    blob = _search_blob(tender, search_category=config.search_category)

    seen_terms: list[str] = []
    seen_set: set[str] = set()
    groups_order: list[str] = []
    groups_set: set[str] = set()
    weights: dict[str, int] = {}

    for kt in config.terms:
        # Deduplicate by term string; first weight/group wins for scoring.
        if kt.term in seen_set:
            continue
        pat = _compile_pattern(
            kt.term,
            case_sensitive=config.case_sensitive,
            short_term_max_len=config.short_term_max_len,
        )
        if pat.search(blob):
            seen_set.add(kt.term)
            seen_terms.append(kt.term)
            weights[kt.term] = kt.weight
            if kt.group not in groups_set:
                groups_set.add(kt.group)
                groups_order.append(kt.group)

    return KeywordMatchResult(
        matched=bool(seen_terms),
        terms=tuple(seen_terms),
        groups=tuple(groups_order),
        weights=weights,
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
