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
