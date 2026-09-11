"""Tests for the Agent Reasoning stage, providers, guardrails, and report integration."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aira.evidence import SiteEvidence
from aira.findings import Evidence, Finding
from aira.orchestrator import run_audit
from aira.reasoning import (
    DeterministicReasoningProvider,
    LLMReasoningProvider,
    ReasoningEngine,
    extract_known_urls,
    sanitize_text_grounding,
    validate_grounding,
    validate_invariance,
)
from aira.report import assert_valid


def _sample_finding(
    check_id: str = "js_dependent_content",
    stage: str = "access",
    severity: str = "high",
    reach: float = 0.5,
) -> Finding:
    return Finding(
        id="F-001",
        check_id=check_id,
        category="discoverability",
        title="Client-Side JavaScript Rendering Required",
        journey_stage=stage,
        severity=severity,
        confidence=0.85,
        priority="high",
        reach=reach,
        impact="Search spiders receive an empty shell.",
        suggested_action={"summary": "Pre-render HTML on server", "priority": "high", "steps": ["Enable SSR"]},
        evidence=Evidence(
            url="https://example.com/app",
            observation="raw 100 words -> rendered 1000 words (90% added by JavaScript)",
            metrics={"added_word_ratio": 0.90},
            affected_urls=["https://example.com/app"],
        ),
    )


def _sample_evidence() -> SiteEvidence:
    return SiteEvidence(
        site="example.com",
        target_url="https://example.com",
        audited_at="2026-09-06T12:00:00Z",
        config={},
    )


def test_deterministic_reasoning_without_api_keys():
    """Verify reasoning operates out-of-the-box deterministically without external keys."""
    engine = ReasoningEngine(provider=DeterministicReasoningProvider())
    evidence = _sample_evidence()
    findings = [_sample_finding()]

    enriched, strategy = engine.process(evidence, findings)

    # Finding enrichments
    assert len(enriched) == 1
    f = enriched[0]
    assert f.enhanced_by_reasoning is True
    assert "root_cause_analysis" in f.reasoning
    assert "JavaScript" in f.reasoning["root_cause_analysis"]
    assert "ai_agent_impact" in f.reasoning
    assert "remediation_phase" in f.reasoning
    assert f.reasoning["estimated_effort"] == "high"

    # Strategic synthesis
    assert "executive_summary" in strategy
    assert "example.com" in strategy["executive_summary"]
    assert strategy["primary_bottleneck_stage"] == "access"
    assert len(strategy["remediation_roadmap"]) == 3
    assert len(strategy["strategic_themes"]) >= 1


def test_evidence_grounding_guardrails():
    """Validate that ungrounded URLs are detected and sanitized, while docs are allowed."""
    known = {"https://example.com", "https://example.com/app"}
    
    # Text with grounded URL and allowed standard doc link
    valid_text = "Refer to https://schema.org/Organization for page https://example.com/app."
    violations = validate_grounding(valid_text, known)
    assert len(violations) == 0

    # Text with hallucinated external URL
    hallucinated_text = "See competitor details at https://fake-hallucination.com/profile."
    violations = validate_grounding(hallucinated_text, known)
    assert len(violations) == 1
    assert "https://fake-hallucination.com/profile" in violations

    sanitized = sanitize_text_grounding(hallucinated_text, known)
    assert "https://fake-hallucination.com/profile" not in sanitized
    assert "[unverified URL]" in sanitized


def test_invariance_guardrail_prevents_score_and_severity_tampering():
    """Verify that reasoning cannot mutate severity, priority, confidence, or reach."""
    findings = [_sample_finding(severity="high", reach=0.5)]
    original = [_sample_finding(severity="high", reach=0.5)]

    # Attempt to illegally tamper with finding properties
    findings[0].severity = "critical"
    
    with pytest.raises(Exception):
        validate_invariance(original, findings)


def test_reasoning_failure_preserves_audit_pipeline(audit):
    """If a reasoning provider raises an exception, the audit completes without failing."""
    class CrashingProvider(DeterministicReasoningProvider):
        def enrich_finding(self, finding, evidence, related):
            raise RuntimeError("Provider connection exploded")

    engine = ReasoningEngine(provider=CrashingProvider())
    evidence = _sample_evidence()
    findings = [_sample_finding()]

    # Must not raise
    processed, strategy = engine.process(evidence, findings)
    assert len(processed) == 1
    # Finding still exists, just without enrichment
    assert processed[0].enhanced_by_reasoning is False
    assert strategy is not None


def test_mocked_llm_provider_success():
    """Test optional LLM reasoning integration with valid JSON payload."""
    llm_mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "root_cause_analysis": "Client-side hydration prevents static scraping.",
                        "ai_agent_impact": "Copilots cannot extract tabular pricing.",
                        "remediation_phase": "Phase 1: Immediate Unblocking",
                        "estimated_effort": "high",
                    })
                }
            }
        ]
    }

    provider = LLMReasoningProvider(api_key="test-key-fake")
    evidence = _sample_evidence()
    finding = _sample_finding()

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = llm_mock_response
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        enrichment = provider.enrich_finding(finding, evidence, [finding])

    assert enrichment["root_cause_analysis"] == "Client-side hydration prevents static scraping."
    assert enrichment["ai_agent_impact"] == "Copilots cannot extract tabular pricing."


def test_mocked_llm_provider_timeout_falls_back_gracefully():
    """Verify that if LLM times out, it automatically falls back to deterministic reasoning."""
    import httpx

    provider = LLMReasoningProvider(api_key="test-key-fake")
    evidence = _sample_evidence()
    finding = _sample_finding()

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timed out")):
        enrichment = provider.enrich_finding(finding, evidence, [finding])

    # Should fall back cleanly without raising
    assert "root_cause_analysis" in enrichment
    assert "JavaScript" in enrichment["root_cause_analysis"]


def test_end_to_end_audit_contains_reasoning_and_passes_schema(audit):
    """End-to-end integration test running through the full audit pipeline with reasoning."""
    report, ev, findings = audit("multi_problem")

    # Contract schema validation
    assert_valid(report)

    # Additive strategic reasoning presence
    assert "strategic_reasoning" in report
    sr = report["strategic_reasoning"]
    assert "executive_summary" in sr
    assert "remediation_roadmap" in sr
    assert "strategic_themes" in sr

    # Finding additive reasoning presence
    for f in report["findings"]:
        assert "reasoning" in f
        assert "enhanced_by_reasoning" in f
        if f["enhanced_by_reasoning"]:
            assert "root_cause_analysis" in f["reasoning"]
            assert "ai_agent_impact" in f["reasoning"]
