"""Finding contract, deterministic severity / confidence / priority, dedupe.

Design rule: severity, confidence and priority are computed from *measured*
inputs (rule class, reach, evidence quality, fix cost). No language model picks
a number here; reasoning is used downstream to explain, not to score.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

SEVERITY_ORDER = ("low", "medium", "high", "critical")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}

JOURNEY_STAGES = ("discover", "access", "understand", "extract", "trust", "represent")
CATEGORIES = ("discoverability", "engagement", "trust")


@dataclass(slots=True)
class Evidence:
    url: str | None
    observation: str
    details: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    affected_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Finding:
    id: str
    check_id: str            # stable key for dedupe/merging
    category: str
    title: str
    evidence: Evidence
    impact: str
    suggested_action: dict[str, Any]
    journey_stage: str | None = None
    severity: str = "medium"
    confidence: float = 0.5
    confidence_reason: str = ""
    priority: str = "medium"
    priority_score: float = 0.0
    priority_reason: str = ""
    dimension: str = "discoverability"   # scoring dimension
    reach: float = 0.0                   # share of relevant pages affected
    # Conditions under which this finding would be a false positive. Recorded by
    # the check that raised it, so the agent layer can verify before presenting
    # and a reader can dismiss the finding on informed grounds.
    benign_explanations: list[str] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)
    reasoning: dict[str, Any] = field(default_factory=dict)
    enhanced_by_reasoning: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = self.evidence.to_dict()
        return d


# --- deterministic severity -------------------------------------------------

# Base severity per check class, chosen from the *mechanism* of the failure:
# a page that cannot be reached at all outranks one that is merely harder to
# interpret. These base levels are an implementation choice, documented in the
# README, not an official hackathon rule.
BASE_SEVERITY: dict[str, str] = {
    "site_unreachable": "critical",
    "homepage_redirects_offsite": "low",
    "redirect_configuration_error": "high",
    "redirect_to_private_address": "high",
    "robots_blocks_site": "critical",
    "important_page_robots_blocked": "high",
    "ai_crawler_blocked": "high",
    "noindex_header_on_important_page": "high",
    "incomplete_structured_data": "medium",
    "structured_visible_mismatch": "medium",
    "sitemap_broken_urls": "medium",
    "sitemap_missing_important_pages": "low",
    "important_page_http_error": "high",
    "noindex_on_important_page": "high",
    "js_dependent_content": "high",
    "missing_organization_identity": "high",
    "entity_name_conflict": "high",
    "invalid_structured_data": "medium",
    "contact_fact_conflict": "medium",
    "missing_product_structured_data": "medium",
    "sitemap_missing": "medium",
    "important_page_deep": "medium",
    "important_page_orphaned": "medium",
    "canonical_conflict": "medium",
    "redirect_chain": "low",
    "missing_meta_description": "low",
    "thin_important_page": "medium",
    "missing_h1": "low",
    "freshness_risk": "low",
    "no_corroborating_entity_links": "low",
    "home_purpose_unclear": "high",
    "page_identity_unclear": "medium",
    "weak_navigation": "medium",
    "missing_nav_landmark": "low",
    "no_next_step": "medium",
    "context_loss_orphan": "medium",
    "facts_in_images": "medium",
}


def escalate(severity: str, steps: int = 1) -> str:
    idx = min(SEVERITY_RANK.get(severity, 1) + steps, len(SEVERITY_ORDER) - 1)
    return SEVERITY_ORDER[idx]


def de_escalate(severity: str, steps: int = 1) -> str:
    idx = max(SEVERITY_RANK.get(severity, 1) - steps, 0)
    return SEVERITY_ORDER[idx]


# "critical" is reserved for failures that stop retrieval of the site outright.
# Everything else is capped at "high" no matter how wide its reach, so that a
# widespread but non-blocking issue never outranks a blocking one.
MAY_BE_CRITICAL = frozenset({"site_unreachable", "robots_blocks_site"})


def resolve_severity(check_id: str, *, reach: float, on_important_page: bool,
                     override: str | None = None) -> str:
    """Base severity adjusted by reach and by whether important pages are hit."""
    if override:
        return override
    sev = BASE_SEVERITY.get(check_id, "medium")
    if reach >= 0.6 and on_important_page:
        sev = escalate(sev)
    elif reach <= 0.15 and not on_important_page:
        sev = de_escalate(sev)
    if sev == "critical" and check_id not in MAY_BE_CRITICAL:
        sev = "high"
    return sev


# --- deterministic confidence ----------------------------------------------

def compute_confidence(*, deterministic: bool, sample_size: int,
                       affected: int, direct_dom_evidence: bool,
                       conflicting_signals: bool = False,
                       corroborating_sources: int = 1) -> tuple[float, str]:
    """Build confidence from evidence quality, and explain it."""
    score = 0.5
    parts: list[str] = []
    if deterministic:
        score += 0.25
        parts.append("deterministic rule on measured values")
    if direct_dom_evidence:
        score += 0.1
        parts.append("direct DOM/HTTP observation")
    if sample_size >= 5:
        score += 0.08
        parts.append(f"sample of {sample_size} pages")
    elif sample_size <= 1:
        score -= 0.1
        parts.append("single-page sample")
    if sample_size and affected:
        share = affected / max(sample_size, 1)
        if share >= 0.8:
            score += 0.07
            parts.append(f"consistent across {affected}/{sample_size} pages")
        elif share <= 0.2:
            score -= 0.03
    if corroborating_sources >= 2:
        score += 0.05
        parts.append(f"{corroborating_sources} independent sources agree")
    if conflicting_signals:
        score -= 0.2
        parts.append("conflicting signals present")
    score = max(0.3, min(round(score, 2), 0.98))
    return score, "; ".join(parts) or "heuristic assessment"


# --- deterministic priority -------------------------------------------------

IMPACT_WEIGHT: dict[str, float] = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.25}

# Fixability: how cheap the recommended change typically is (1.0 = trivial).
FIXABILITY: dict[str, float] = {
    "robots_blocks_site": 1.0,
    "noindex_on_important_page": 1.0,
    "missing_meta_description": 0.95,
    "missing_h1": 0.95,
    "sitemap_missing": 0.9,
    "missing_organization_identity": 0.85,
    "invalid_structured_data": 0.85,
    "missing_product_structured_data": 0.7,
    "entity_name_conflict": 0.8,
    "contact_fact_conflict": 0.85,
    "canonical_conflict": 0.85,
    "redirect_chain": 0.8,
    "important_page_deep": 0.7,
    "important_page_orphaned": 0.75,
    "weak_navigation": 0.6,
    "missing_nav_landmark": 0.95,
    "no_next_step": 0.7,
    "js_dependent_content": 0.35,
    "site_unreachable": 0.4,
    "homepage_redirects_offsite": 0.9,
    "redirect_configuration_error": 0.8,
    "redirect_to_private_address": 0.8,
    "important_page_http_error": 0.7,
    "thin_important_page": 0.5,
    "freshness_risk": 0.6,
    "facts_in_images": 0.5,
    "home_purpose_unclear": 0.6,
    "page_identity_unclear": 0.7,
    "context_loss_orphan": 0.7,
    "no_corroborating_entity_links": 0.8,
    "important_page_robots_blocked": 0.9,
    "ai_crawler_blocked": 1.0,
    "noindex_header_on_important_page": 0.95,
    "incomplete_structured_data": 0.85,
    "structured_visible_mismatch": 0.8,
    "sitemap_broken_urls": 0.85,
    "sitemap_missing_important_pages": 0.9,
}


def compute_priority(finding: Finding) -> tuple[str, float, str]:
    impact = IMPACT_WEIGHT.get(finding.severity, 0.5)
    reach = max(0.1, min(finding.reach, 1.0))
    fixability = FIXABILITY.get(finding.check_id, 0.6)
    score = impact * (0.35 + 0.65 * reach) * finding.confidence * (0.55 + 0.45 * fixability)
    score = round(score, 4)
    if score >= 0.55:
        band = "high"
    elif score >= 0.28:
        band = "medium"
    else:
        band = "low"
    reason = (
        f"impact {impact:.2f} (severity {finding.severity}) x reach {reach:.2f} "
        f"x confidence {finding.confidence:.2f} x fixability {fixability:.2f}"
    )
    return band, score, reason


# --- normalization, dedupe, merge ------------------------------------------

def _merge_two(primary: Finding, other: Finding) -> Finding:
    """Fold *other* into *primary*, keeping the stronger signals."""
    if SEVERITY_RANK[other.severity] > SEVERITY_RANK[primary.severity]:
        primary.severity = other.severity
    primary.confidence = max(primary.confidence, other.confidence)
    primary.reach = max(primary.reach, other.reach)
    urls = list(dict.fromkeys(
        primary.evidence.affected_urls + other.evidence.affected_urls))
    primary.evidence.affected_urls = urls
    extra = other.evidence.observation
    if extra and extra not in primary.evidence.details:
        primary.evidence.details = (
            primary.evidence.details + " | " if primary.evidence.details else ""
        ) + f"Corroborated by {other.category} audit: {extra}"
    for k, v in other.evidence.metrics.items():
        primary.evidence.metrics.setdefault(k, v)
    primary.benign_explanations = list(dict.fromkeys(
        primary.benign_explanations + other.benign_explanations))
    primary.merged_from = list(dict.fromkeys(
        primary.merged_from + [other.id] + other.merged_from))
    return primary


# Checks from different modules that describe the same underlying problem.
MERGE_GROUPS: dict[str, str] = {
    # Only genuine synonyms are merged. "Hard to reach for a crawler" (depth) and
    # "the visitor has nowhere to go next" (context loss) are different problems
    # with different fixes, so they are deliberately NOT grouped together.
    "important_page_orphaned": "reachability",
    "important_page_deep": "reachability",
}


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    """Merge findings that share a check_id+scope, or a cross-module group."""
    out: dict[tuple[str, str], Finding] = {}
    order: list[tuple[str, str]] = []
    for f in findings:
        scope = f.evidence.url or "site"
        group = MERGE_GROUPS.get(f.check_id, f.check_id)
        # Never fold a discoverability finding into an engagement one (or the
        # reverse): they are reported to different owners and fixed differently.
        key = (f"{f.category}:{group}", scope)
        if key in out:
            _merge_two(out[key], f)
        else:
            out[key] = f
            order.append(key)
    return [out[k] for k in order]


def finalize(findings: list[Finding]) -> list[Finding]:
    """Assign priorities and stable public ids, sorted by importance."""
    for f in findings:
        band, score, reason = compute_priority(f)
        f.priority = band
        f.priority_score = score
        f.priority_reason = reason
        f.suggested_action["priority"] = band
    findings.sort(key=lambda f: (-SEVERITY_RANK[f.severity], -f.priority_score))
    for i, f in enumerate(findings, start=1):
        f.id = f"F-{i:03d}"
    return findings
