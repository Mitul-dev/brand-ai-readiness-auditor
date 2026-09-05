"""AI Readiness Score.

An implementation enhancement, not an official hackathon requirement.

Each dimension starts at 100 and loses points only for findings that were
actually raised, weighted by severity, reach and confidence. A dimension whose
checks were all NOT APPLICABLE is reported as ``null`` rather than as a perfect
or a zero score, so a small site is not rewarded or punished for absent features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evidence import SiteEvidence
from .findings import Finding

DIMENSIONS = ("discoverability", "content_accessibility", "entity_clarity",
              "fact_consistency", "freshness", "engagement")

DIMENSION_LABELS = {
    "discoverability": "Discoverability",
    "content_accessibility": "Content Accessibility",
    "entity_clarity": "Entity Clarity",
    "fact_consistency": "Fact Consistency",
    "freshness": "Freshness",
    "engagement": "Engagement",
}

# Weight of the dimension in the overall score.
DIMENSION_WEIGHTS = {
    "discoverability": 0.25,
    "content_accessibility": 0.22,
    "entity_clarity": 0.18,
    "fact_consistency": 0.12,
    "freshness": 0.08,
    "engagement": 0.15,
}

SEVERITY_PENALTY = {"critical": 45.0, "high": 26.0, "medium": 13.0, "low": 5.0}


@dataclass(slots=True)
class ScoreBreakdown:
    overall: int
    dimensions: dict[str, int | None]
    explanation: dict[str, str] = field(default_factory=dict)
    applicable: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "dimensions": {DIMENSION_LABELS[k]: v for k, v in self.dimensions.items()},
            "dimension_keys": self.dimensions,
            "explanation": self.explanation,
            "applicable": self.applicable,
            "method": (
                "Each dimension starts at 100 and loses "
                "severity_penalty x (0.4 + 0.6 x reach) x confidence for every "
                "finding attributed to it. The overall score is the weighted mean "
                "of the applicable dimensions."
            ),
        }


def _applicability(ev: SiteEvidence) -> dict[str, bool]:
    """Which dimensions could be judged at all from what we observed."""
    html = len(ev.html_pages)
    rendered = any(p.rendering.ok for p in ev.pages)
    return {
        "discoverability": html >= 1,
        "content_accessibility": html >= 1,
        "entity_clarity": html >= 1,
        "fact_consistency": bool(ev.facts_by_kind.get("organization_name")
                                 or ev.facts_by_kind.get("phone")
                                 or ev.facts_by_kind.get("email")),
        "freshness": any(p.latest_date for p in ev.html_pages),
        "engagement": html >= 1,
    }


def compute_score(findings: list[Finding], ev: SiteEvidence) -> ScoreBreakdown:
    applicable = _applicability(ev)
    penalties: dict[str, float] = {d: 0.0 for d in DIMENSIONS}
    drivers: dict[str, list[str]] = {d: [] for d in DIMENSIONS}

    for f in findings:
        dim = f.dimension if f.dimension in penalties else "discoverability"
        base = SEVERITY_PENALTY.get(f.severity, 10.0)
        reach = max(0.1, min(f.reach or 0.3, 1.0))
        penalty = base * (0.4 + 0.6 * reach) * f.confidence
        penalties[dim] += penalty
        drivers[dim].append(f"{f.title} (-{penalty:.0f})")

    dims: dict[str, int | None] = {}
    explanation: dict[str, str] = {}
    for d in DIMENSIONS:
        if not applicable.get(d):
            dims[d] = None
            explanation[DIMENSION_LABELS[d]] = (
                "not applicable: no evidence of this kind was observable on this site")
            continue
        score = int(round(max(0.0, 100.0 - penalties[d])))
        dims[d] = score
        if drivers[d]:
            explanation[DIMENSION_LABELS[d]] = (
                f"{score}/100 after {len(drivers[d])} finding(s): "
                + "; ".join(drivers[d][:3]))
        else:
            explanation[DIMENSION_LABELS[d]] = f"{score}/100 - no findings in this dimension"

    live = {d: v for d, v in dims.items() if v is not None}
    if live:
        total_w = sum(DIMENSION_WEIGHTS[d] for d in live)
        overall = int(round(
            sum(DIMENSION_WEIGHTS[d] * v for d, v in live.items()) / total_w))
    else:
        overall = 0
    return ScoreBreakdown(overall=overall, dimensions=dims,
                          explanation=explanation, applicable=applicable)
