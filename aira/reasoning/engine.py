"""Reasoning Engine: coordinates provider execution, finding enrichment, and strategic synthesis.

DETERMINISTIC DATA COLLECTION
        ↓
OBJECTIVE EVIDENCE
        ↓
AGENT REASONING (This Module)
        ↓
FINDING
        ↓
RECOMMENDATION
"""
from __future__ import annotations

import logging
import os
from typing import Any

from aira.evidence import SiteEvidence
from aira.findings import Finding
from aira.reasoning.providers import (
    DeterministicReasoningProvider,
    LLMReasoningProvider,
    ReasoningProvider,
)
from aira.reasoning.validation import validate_invariance

log = logging.getLogger("aira.reasoning")


class ReasoningEngine:
    """Executes the Agent Reasoning stage over deterministic findings and evidence."""

    def __init__(self, provider: ReasoningProvider | None = None) -> None:
        if provider is not None:
            self.provider = provider
        else:
            llm_key = os.getenv("AIRA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            if llm_key:
                self.provider = LLMReasoningProvider(api_key=llm_key)
            else:
                self.provider = DeterministicReasoningProvider()

    def process(
        self,
        evidence: SiteEvidence,
        findings: list[Finding],
    ) -> tuple[list[Finding], dict[str, Any]]:
        """Apply agent reasoning to enrich findings and synthesize executive strategy.
        
        Guarantees:
        - Never raises an unhandled exception that disrupts the audit.
        - Preserves all deterministic metrics, severities, and scores.
        - Returns additive strategic reasoning and finding enrichments.
        """
        if not findings:
            strategy = self.provider.synthesize_strategy(evidence, [])
            return findings, strategy

        # Snapshot for invariance verification
        original_snapshot = [
            (f.id, f.severity, f.priority, f.confidence, f.reach) for f in findings
        ]

        # 1. Grounded Finding Enrichment
        for finding in findings:
            try:
                enrichment = self.provider.enrich_finding(finding, evidence, findings)
                finding.reasoning = enrichment
                finding.enhanced_by_reasoning = True
            except Exception as exc:
                log.warning("Reasoning provider failed on %s (%s); omitting enrichment", finding.id, exc)
                finding.reasoning = {}
                finding.enhanced_by_reasoning = False

        # 2. Strategic Strategy Synthesis
        try:
            strategy = self.provider.synthesize_strategy(evidence, findings)
        except Exception as exc:
            log.warning("Strategy synthesis failed (%s); using deterministic fallback", exc)
            strategy = DeterministicReasoningProvider().synthesize_strategy(evidence, findings)

        # 3. Assert Metric Invariance
        for orig, f in zip(original_snapshot, findings):
            if (f.id, f.severity, f.priority, f.confidence, f.reach) != orig:
                # Restore invariants if altered
                f.id, f.severity, f.priority, f.confidence, f.reach = orig
                log.error("Invariant violation detected and rectified on finding %s", f.id)

        return findings, strategy
