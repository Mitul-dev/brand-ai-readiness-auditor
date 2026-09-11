"""Agent Reasoning package for Brand AI Readiness Auditor.

Translates objective crawl evidence into grounded explanations, root cause analysis,
AI agent impacts, and a phased strategic remediation roadmap.
"""
from __future__ import annotations

from .engine import ReasoningEngine
from .providers import (
    DeterministicReasoningProvider,
    LLMReasoningProvider,
    ReasoningProvider,
)
from .validation import (
    ReasoningValidationError,
    extract_known_urls,
    sanitize_text_grounding,
    validate_grounding,
    validate_invariance,
)

__all__ = [
    "ReasoningEngine",
    "ReasoningProvider",
    "DeterministicReasoningProvider",
    "LLMReasoningProvider",
    "ReasoningValidationError",
    "extract_known_urls",
    "sanitize_text_grounding",
    "validate_grounding",
    "validate_invariance",
]
