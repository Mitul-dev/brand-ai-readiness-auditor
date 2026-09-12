"""The reasoning layer must never let a model invent facts or shapes.

JSON that parses is not yet output that can be published: a model can return the
right type with the wrong contents, or the wrong type entirely, and either would
otherwise flow straight into the report.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aira.evidence import SiteEvidence
from aira.findings import Evidence, Finding
from aira.reasoning.engine import ReasoningEngine
from aira.reasoning.providers import (
    EFFORT_LEVELS, REMEDIATION_PHASES, DeterministicReasoningProvider,
    LLMReasoningProvider,
)
from aira.reasoning.validation import (
    coerce_enum, coerce_list, coerce_text, grounded_numbers,
    sanitize_metric_claims, validate_invariance, ReasoningValidationError,
)


def _evidence() -> SiteEvidence:
    return SiteEvidence(site="example.com", target_url="https://example.com/",
                        audited_at="2026-01-01T00:00:00+00:00", config={})


def _finding(**kw) -> Finding:
    base = dict(
        id="F-001", check_id="missing_h1", category="discoverability", title="t",
        evidence=Evidence(url="https://example.com/",
                          observation="3 of 4 important pages have no H1",
                          details="", metrics={"pages_without_h1": 3,
                                               "important_pages": 4},
                          affected_urls=["https://example.com/"]),
        impact="i", suggested_action={"summary": "s", "priority": "medium",
                                      "steps": ["a"]},
        severity="high", confidence=0.9, reach=0.5,
    )
    base.update(kw)
    return Finding(**base)


HOSTILE = {
    "root_cause_analysis": ("Affects 47 of 52 pages, see https://evil.example/x, "
                            "impacting 91% of products"),
    "ai_agent_impact": "x" * 50_000,
    "remediation_phase": {"nested": "object"},
    "estimated_effort": "'; DROP TABLE findings; --",
    "strategic_themes": "not a list",
    "remediation_roadmap": list(range(500)),
    "executive_summary": "We observed 99 of 120 pages failing",
    "primary_bottleneck_stage": "invented_stage",
}


# --- fabricated metrics ------------------------------------------------------

def test_invented_counts_are_redacted():
    provider = LLMReasoningProvider(api_key="test")
    with patch.object(provider, "_call_llm_json", return_value=HOSTILE):
        out = provider.enrich_finding(_finding(), _evidence(), [])
    assert "47 of 52" not in out["root_cause_analysis"]
    assert "[unverified count]" in out["root_cause_analysis"]
    assert "91%" not in out["root_cause_analysis"]


def test_measured_counts_survive_unchanged():
    provider = LLMReasoningProvider(api_key="test")
    grounded = {"root_cause_analysis": "This affects 3 of 4 important pages.",
                "ai_agent_impact": "Extraction is degraded."}
    with patch.object(provider, "_call_llm_json", return_value=grounded):
        out = provider.enrich_finding(_finding(), _evidence(), [])
    assert out["root_cause_analysis"] == "This affects 3 of 4 important pages."


def test_sanitize_metric_claims_is_precise():
    known = {"3", "4", "75"}
    assert sanitize_metric_claims("3 of 4 pages", known) == "3 of 4 pages"
    assert "[unverified count]" in sanitize_metric_claims("9 of 40 pages", known)
    assert sanitize_metric_claims("75% of pages", known) == "75% of pages"
    assert "[unverified proportion]" in sanitize_metric_claims("12% of pages", known)


def test_grounded_numbers_come_from_the_evidence():
    numbers = grounded_numbers(_finding(), _evidence())
    assert "3" in numbers and "4" in numbers
    assert "52" not in numbers


# --- invented URLs -----------------------------------------------------------

def test_invented_urls_are_redacted():
    provider = LLMReasoningProvider(api_key="test")
    with patch.object(provider, "_call_llm_json", return_value=HOSTILE):
        out = provider.enrich_finding(_finding(), _evidence(), [])
    assert "evil.example" not in out["root_cause_analysis"]
    assert "[unverified URL]" in out["root_cause_analysis"]


# --- malformed shapes --------------------------------------------------------

def test_wrong_types_are_coerced_to_safe_defaults():
    provider = LLMReasoningProvider(api_key="test")
    with patch.object(provider, "_call_llm_json", return_value=HOSTILE):
        out = provider.enrich_finding(_finding(), _evidence(), [])
        strategy = provider.synthesize_strategy(_evidence(), [_finding()])
    assert out["remediation_phase"] in REMEDIATION_PHASES
    assert out["estimated_effort"] in EFFORT_LEVELS
    assert isinstance(strategy["strategic_themes"], list)
    assert isinstance(strategy["remediation_roadmap"], list)
    assert len(strategy["remediation_roadmap"]) <= 12


def test_unbounded_text_is_truncated():
    provider = LLMReasoningProvider(api_key="test")
    with patch.object(provider, "_call_llm_json", return_value=HOSTILE):
        out = provider.enrich_finding(_finding(), _evidence(), [])
    assert len(out["ai_agent_impact"]) <= 1300


def test_non_object_response_falls_back():
    provider = LLMReasoningProvider(api_key="test")
    for bogus in (["a list"], "a string", 42, None):
        with patch.object(provider, "_call_llm_json", return_value=bogus):
            out = provider.enrich_finding(_finding(), _evidence(), [])
        assert out["root_cause_analysis"], "fallback must still produce reasoning"


def test_network_failure_falls_back():
    provider = LLMReasoningProvider(api_key="test")
    with patch.object(provider, "_call_llm_json", side_effect=OSError("boom")):
        out = provider.enrich_finding(_finding(), _evidence(), [])
        strategy = provider.synthesize_strategy(_evidence(), [_finding()])
    assert out["root_cause_analysis"]
    assert strategy["executive_summary"]


def test_coercion_helpers():
    assert coerce_text(123) == ""
    assert coerce_text("a" * 5000).endswith("...")
    assert coerce_enum("HIGH", ("low", "medium", "high"), "medium") == "high"
    assert coerce_enum({"x": 1}, ("low",), "low") == "low"
    assert coerce_list("nope") == []
    assert coerce_list([1, 2, "keep"]) == ["keep"]
    assert len(coerce_list(["x"] * 100)) <= 12


# --- counts are never taken from the model -----------------------------------

def test_stage_counts_are_recomputed_not_trusted():
    provider = LLMReasoningProvider(api_key="test")
    poisoned = dict(HOSTILE, findings_by_stage_count={"extract": 9999})
    with patch.object(provider, "_call_llm_json", return_value=poisoned):
        strategy = provider.synthesize_strategy(_evidence(), [_finding()])
    assert strategy["findings_by_stage_count"] != {"extract": 9999}


# --- deterministic scores are never touched ----------------------------------

def test_reasoning_cannot_change_severity_or_score():
    findings = [_finding(), _finding(id="F-002", severity="low", confidence=0.4)]
    before = [(f.id, f.severity, f.priority, f.confidence, f.reach) for f in findings]

    class Tamperer(DeterministicReasoningProvider):
        def enrich_finding(self, finding, evidence, related):
            finding.severity = "critical"
            finding.confidence = 1.0
            finding.reach = 1.0
            return {"root_cause_analysis": "x", "ai_agent_impact": "y"}

    findings, _ = ReasoningEngine(provider=Tamperer()).process(_evidence(), findings)
    after = [(f.id, f.severity, f.priority, f.confidence, f.reach) for f in findings]
    assert after == before, "deterministic values must be restored after reasoning"


def test_validate_invariance_detects_tampering():
    a, b = _finding(), _finding()
    b.severity = "low"
    with pytest.raises(ReasoningValidationError):
        validate_invariance([a], [b])


def test_provider_failure_does_not_break_the_audit():
    class Broken(DeterministicReasoningProvider):
        def enrich_finding(self, finding, evidence, related):
            raise RuntimeError("provider exploded")

        def synthesize_strategy(self, evidence, findings):
            raise RuntimeError("provider exploded")

    findings, strategy = ReasoningEngine(provider=Broken()).process(
        _evidence(), [_finding()])
    assert findings and findings[0].enhanced_by_reasoning is False
    assert strategy["executive_summary"], "a deterministic strategy must remain"


# --- works with no API key at all --------------------------------------------

def test_engine_defaults_to_deterministic_without_any_api_key(monkeypatch):
    monkeypatch.delenv("AIRA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = ReasoningEngine()
    assert isinstance(engine.provider, DeterministicReasoningProvider)
    findings, strategy = engine.process(_evidence(), [_finding()])
    assert findings[0].reasoning
    assert strategy["executive_summary"]


def test_llm_provider_without_key_uses_fallback_without_network():
    provider = LLMReasoningProvider(api_key=None)
    assert provider.is_configured() is False
    with patch.object(provider, "_call_llm_json",
                      side_effect=AssertionError("must not call the network")):
        out = provider.enrich_finding(_finding(), _evidence(), [])
        strategy = provider.synthesize_strategy(_evidence(), [_finding()])
    assert out["root_cause_analysis"] and strategy["executive_summary"]
