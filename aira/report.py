"""Final report assembly and schema validation.

The required fields from the official handout are produced first and are never
removed; everything else is additive.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .evidence import SiteEvidence
from .findings import Finding
from .scoring import ScoreBreakdown

REQUIRED_FINDING_FIELDS = ("id", "title", "severity", "evidence", "suggested_action")
REQUIRED_TOP_FIELDS = ("site", "audited_at", "summary", "findings")
VALID_SEVERITIES = ("critical", "high", "medium", "low")


class SchemaError(ValueError):
    """Raised when the assembled report does not satisfy the required schema."""


def _evidence_sentence(f: Finding) -> str:
    """The official schema wants ``evidence`` as a string; keep the rich object too."""
    parts = [f.evidence.observation.strip()]
    if f.evidence.details:
        parts.append(f.evidence.details.strip())
    return " ".join(p for p in parts if p)[:1200]


def build_report(ev: SiteEvidence, findings: list[Finding],
                 score: ScoreBreakdown, *, runtime_s: float = 0.0,
                 include_evidence_model: bool = False,
                 strategic_reasoning: dict[str, Any] | None = None) -> dict[str, Any]:
    counts = {s: sum(1 for f in findings if f.severity == s) for s in VALID_SEVERITIES}
    report: dict[str, Any] = {
        "site": ev.site,
        "audited_at": ev.audited_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "total_findings": len(findings),
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "ai_readiness_score": score.overall,
            "ai_readiness_assessed": score.overall is not None,
            "pages_crawled": len(ev.pages),
            "pages_rendered": ev.rendered_page_count,
            "important_pages": len(ev.important_pages),
            "runtime_seconds": round(runtime_s, 2),
        },
        "ai_readiness": score.to_dict(),
        "site_context": {
            "target_url": ev.target_url,
            "home_status": ev.home_status,
            "robots_present": ev.robots_present,
            "robots_blocks_site": ev.robots_blocks_site,
            "sitemap_present": ev.sitemap_present,
            "sitemap_url_count": ev.sitemap_url_count,
            "renderer_available": ev.renderer_available,
            "rendering": ev.rendering,
            "navigation": ev.navigation,
            "home_outcome": ev.home_outcome,
            "home_redirect_target": ev.home_redirect_target,
            "non_page_resources_excluded": len(ev.non_page_resources),
            "counts": ev.counts(),
            "non_page_resources": [
                {"url": p.url, "kind": p.resource_kind,
                 "reasons": p.resource_reasons}
                for p in ev.non_page_resources
            ][:25],
            "crawl_budget_exhausted": ev.crawl_budget_exhausted,
            "page_roles": _role_histogram(ev),
            "notes": ev.notes,
        },
        "findings": [],
    }
    for f in findings:
        report["findings"].append({
            # --- required by the official schema ---
            "id": f.id,
            "title": f.title,
            "severity": f.severity,
            "evidence": _evidence_sentence(f),
            "suggested_action": {
                "summary": f.suggested_action["summary"],
                "priority": f.suggested_action.get("priority", f.priority),
                "steps": f.suggested_action.get("steps", []),
            },
            # --- additive fields ---
            "category": f.category,
            "journey_stage": f.journey_stage,
            "check_id": f.check_id,
            "confidence": f.confidence,
            "confidence_reason": f.confidence_reason,
            "impact": f.impact,
            "priority_score": f.priority_score,
            "priority_reason": f.priority_reason,
            "reach": f.reach,
            "affected_urls": f.evidence.affected_urls[:25],
            "technical_details": {
                "url": f.evidence.url,
                "observation": f.evidence.observation,
                "details": f.evidence.details,
                "metrics": f.evidence.metrics,
            },
            "possible_benign_explanations": f.benign_explanations,
            "merged_from_checks": f.merged_from,
            "reasoning": f.reasoning,
            "enhanced_by_reasoning": f.enhanced_by_reasoning,
        })
    if strategic_reasoning:
        report["strategic_reasoning"] = strategic_reasoning
    if include_evidence_model:
        report["evidence_model"] = ev.to_dict()
    return report


def _role_histogram(ev: SiteEvidence) -> dict[str, int]:
    hist: dict[str, int] = {}
    for p in ev.pages:
        hist[p.role] = hist.get(p.role, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: -kv[1]))


def validate_report(report: dict[str, Any]) -> list[str]:
    """Return a list of schema problems; empty list means valid."""
    problems: list[str] = []
    for key in REQUIRED_TOP_FIELDS:
        if key not in report:
            problems.append(f"missing top-level field: {key}")
    summary = report.get("summary", {})
    for key in ("total_findings", "critical", "high", "medium"):
        if key not in summary:
            problems.append(f"missing summary field: {key}")
    findings = report.get("findings")
    if not isinstance(findings, list):
        problems.append("findings must be a list")
        return problems
    if summary.get("total_findings") != len(findings):
        problems.append("summary.total_findings does not match len(findings)")
    seen_ids: set[str] = set()
    for i, f in enumerate(findings):
        for key in REQUIRED_FINDING_FIELDS:
            if key not in f:
                problems.append(f"finding[{i}] missing field: {key}")
        if f.get("id") in seen_ids:
            problems.append(f"duplicate finding id: {f.get('id')}")
        seen_ids.add(f.get("id"))
        if f.get("severity") not in VALID_SEVERITIES:
            problems.append(f"finding[{i}] invalid severity: {f.get('severity')!r}")
        if not isinstance(f.get("evidence"), str) or not f.get("evidence", "").strip():
            problems.append(f"finding[{i}] evidence must be a non-empty string")
        action = f.get("suggested_action")
        if not isinstance(action, dict):
            problems.append(f"finding[{i}] suggested_action must be an object")
        else:
            if not action.get("summary"):
                problems.append(f"finding[{i}] suggested_action.summary is empty")
            if action.get("priority") not in ("high", "medium", "low"):
                problems.append(
                    f"finding[{i}] suggested_action.priority invalid: "
                    f"{action.get('priority')!r}")
    for sev in ("critical", "high", "medium"):
        actual = sum(1 for f in findings if f.get("severity") == sev)
        if summary.get(sev) != actual:
            problems.append(f"summary.{sev} ({summary.get(sev)}) != actual ({actual})")
    return problems


def assert_valid(report: dict[str, Any]) -> None:
    problems = validate_report(report)
    if problems:
        raise SchemaError("; ".join(problems))
