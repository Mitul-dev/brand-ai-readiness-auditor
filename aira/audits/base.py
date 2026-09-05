"""Shared helper for constructing findings with deterministic scoring."""
from __future__ import annotations

from typing import Any

from ..findings import Evidence, Finding, compute_confidence, resolve_severity


def make_finding(
    *,
    check_id: str,
    category: str,
    title: str,
    observation: str,
    impact: str,
    action_summary: str,
    steps: list[str],
    url: str | None = None,
    details: str = "",
    metrics: dict[str, Any] | None = None,
    affected_urls: list[str] | None = None,
    journey_stage: str | None = None,
    benign_explanations: list[str] | None = None,
    dimension: str = "discoverability",
    reach: float = 0.0,
    on_important_page: bool = False,
    severity_override: str | None = None,
    sample_size: int = 1,
    affected: int = 1,
    direct_dom_evidence: bool = True,
    deterministic: bool = True,
    conflicting_signals: bool = False,
    corroborating_sources: int = 1,
) -> Finding:
    severity = resolve_severity(check_id, reach=reach,
                               on_important_page=on_important_page,
                               override=severity_override)
    confidence, reason = compute_confidence(
        deterministic=deterministic, sample_size=sample_size, affected=affected,
        direct_dom_evidence=direct_dom_evidence,
        conflicting_signals=conflicting_signals,
        corroborating_sources=corroborating_sources,
    )
    return Finding(
        id="",  # assigned in finalize()
        check_id=check_id,
        category=category,
        title=title,
        journey_stage=journey_stage,
        severity=severity,
        confidence=confidence,
        confidence_reason=reason,
        dimension=dimension,
        reach=round(reach, 3),
        benign_explanations=benign_explanations or [],
        evidence=Evidence(
            url=url, observation=observation, details=details,
            metrics=metrics or {},
            affected_urls=affected_urls or ([url] if url else []),
        ),
        impact=impact,
        suggested_action={"summary": action_summary, "priority": "medium",
                          "steps": steps},
    )
