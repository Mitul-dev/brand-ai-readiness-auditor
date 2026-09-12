"""Validation and grounding guardrails for agent reasoning.

Enforces:
1. Evidence Grounding: URLs or metrics cited in reasoning must originate from
   measured SiteEvidence or Finding.evidence. No hallucinated pages or facts.
2. Metric Invariance: Reasoning never overrides or alters deterministic scores,
   confidence, reach, or severity rankings.
"""
from __future__ import annotations

import re
from typing import Any

from aira.evidence import SiteEvidence
from aira.findings import Finding

URL_REGEX = re.compile(r"https?://[^\s\"'>)]+", re.IGNORECASE)

# Quantified claims: "14 of 16 pages", "0/18", "75% of". These read as
# measurements, so they must correspond to a number the deterministic layer
# actually recorded.
COUNT_CLAIM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:of|/|out of)\s*(\d+(?:\.\d+)?)\b",
                            re.IGNORECASE)
PERCENT_CLAIM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*%")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Upper bounds on anything a model returns, so a runaway response cannot be
# carried into the report.
MAX_TEXT_CHARS = 1200
MAX_LIST_ITEMS = 12
MAX_ITEM_CHARS = 400


class ReasoningValidationError(ValueError):
    """Raised when reasoning output violates grounding or invariance rules."""


def extract_known_urls(evidence: SiteEvidence, findings: list[Finding]) -> set[str]:
    """Collect all valid, observed URLs from the deterministic evidence layer."""
    known: set[str] = set()
    if evidence.target_url:
        known.add(evidence.target_url.rstrip("/"))
    for p in evidence.pages:
        if p.url:
            known.add(p.url.rstrip("/"))
        if p.final_url:
            known.add(p.final_url.rstrip("/"))
    for f in findings:
        if f.evidence.url:
            known.add(f.evidence.url.rstrip("/"))
        for u in f.evidence.affected_urls:
            known.add(u.rstrip("/"))
    return known


def validate_grounding(text: str, known_urls: set[str]) -> list[str]:
    """Identify any URLs in text that were not in the observed evidence.
    
    Standard external documentation references (e.g., schema.org, robots.txt specs)
    are permitted as educational citations, but site page URLs must be grounded.
    """
    allowed_domains = (
        "schema.org",
        "w3.org",
        "developers.google.com",
        "www.robotstxt.org",
        "json-ld.org",
    )
    violations: list[str] = []
    for match in URL_REGEX.finditer(text):
        url = match.group(0).rstrip(".,;")
        if any(domain in url for domain in allowed_domains):
            continue
        cleaned = url.rstrip("/")
        if cleaned not in known_urls:
            violations.append(url)
    return violations


def sanitize_text_grounding(text: str, known_urls: set[str]) -> str:
    """Strip or redact ungrounded site URLs from reasoning text while preserving references."""
    violations = validate_grounding(text, known_urls)
    sanitized = text
    for bad_url in violations:
        sanitized = sanitized.replace(bad_url, "[unverified URL]")
    return sanitized


def _numbers_in(value: Any) -> set[str]:
    """Every numeric token appearing anywhere in a value, normalized."""
    out: set[str] = set()
    for token in NUMBER_RE.findall(str(value)):
        out.add(token)
        if token.endswith(".0"):
            out.add(token[:-2])
        out.add(str(int(float(token))) if float(token).is_integer() else token)
    return out


def grounded_numbers(finding: Finding, evidence: SiteEvidence | None = None) -> set[str]:
    """Numbers the deterministic layer actually measured for this finding."""
    known = _numbers_in(finding.evidence.metrics)
    known |= _numbers_in(finding.evidence.observation)
    known |= _numbers_in(finding.evidence.details)
    known |= _numbers_in(len(finding.evidence.affected_urls))
    known |= _numbers_in(round(finding.reach * 100))
    known |= _numbers_in(finding.confidence)
    if evidence is not None:
        known |= _numbers_in(len(evidence.pages))
        known |= _numbers_in(len(evidence.html_pages))
    return known


def sanitize_metric_claims(text: str, known_numbers: set[str]) -> str:
    """Redact quantified claims whose numbers were never measured.

    A model asked to explain a finding will sometimes invent a plausible-looking
    count. Ratios and percentages are the shapes that read as measurements, so
    they are checked against the numbers the evidence layer recorded and replaced
    with a neutral phrase when they do not match.
    """
    if not text:
        return text

    def _check_count(match: re.Match) -> str:
        part, whole = match.group(1), match.group(2)
        if part in known_numbers and whole in known_numbers:
            return match.group(0)
        return "[unverified count]"

    def _check_percent(match: re.Match) -> str:
        value = match.group(1)
        if value in known_numbers:
            return match.group(0)
        rounded = str(int(round(float(value))))
        if rounded in known_numbers:
            return match.group(0)
        return "[unverified proportion]"

    text = COUNT_CLAIM_RE.sub(_check_count, text)
    return PERCENT_CLAIM_RE.sub(_check_percent, text)


def coerce_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Accept only a string, bounded in length."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def coerce_enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """Accept only one of a fixed set of values."""
    if isinstance(value, str):
        candidate = value.strip()
        for option in allowed:
            if candidate.lower() == option.lower():
                return option
    return default


def coerce_list(value: Any, max_items: int = MAX_LIST_ITEMS,
                item_limit: int = MAX_ITEM_CHARS) -> list[str]:
    """Accept only a list of strings, bounded in count and item length."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:max_items]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:item_limit])
        elif isinstance(item, dict):
            rendered = "; ".join(
                f"{k}: {v}" for k, v in list(item.items())[:4]
                if isinstance(k, str) and isinstance(v, (str, int, float)))
            if rendered:
                out.append(rendered[:item_limit])
    return out


def clean_reasoning_text(value: Any, known_urls: set[str],
                         known_numbers: set[str]) -> str:
    """Full cleaning pass for free text returned by a model."""
    text = coerce_text(value)
    if not text:
        return ""
    text = sanitize_text_grounding(text, known_urls)
    return sanitize_metric_claims(text, known_numbers)


def validate_invariance(original_findings: list[Finding], enriched_findings: list[Finding]) -> None:
    """Ensure agent reasoning has not mutated deterministic scores, severities, or priorities."""
    if len(original_findings) != len(enriched_findings):
        raise ReasoningValidationError(
            f"Finding count changed during reasoning: {len(original_findings)} -> {len(enriched_findings)}"
        )
    for orig, enriched in zip(original_findings, enriched_findings):
        if orig.id != enriched.id:
            raise ReasoningValidationError(f"Finding ID mismatch: {orig.id} != {enriched.id}")
        if orig.severity != enriched.severity:
            raise ReasoningValidationError(
                f"Severity tampered on {orig.id}: {orig.severity} -> {enriched.severity}"
            )
        if orig.priority != enriched.priority:
            raise ReasoningValidationError(
                f"Priority tampered on {orig.id}: {orig.priority} -> {enriched.priority}"
            )
        if orig.confidence != enriched.confidence:
            raise ReasoningValidationError(
                f"Confidence tampered on {orig.id}: {orig.confidence} -> {enriched.confidence}"
            )
        if orig.reach != enriched.reach:
            raise ReasoningValidationError(
                f"Reach tampered on {orig.id}: {orig.reach} -> {enriched.reach}"
            )
