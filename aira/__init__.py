"""AIRA - AI Readiness Audit engine.

Deterministic evidence collection and evidence-backed auditing of websites for
AI discoverability and on-site engagement. The Agent Skills in ``skills/`` are
thin, documented wrappers around these modules.
"""
__version__ = "1.0.0"

__all__ = ["config", "urls", "crawler", "render", "parsing", "importance",
           "facts", "evidence", "findings", "audits", "scoring", "report",
           "orchestrator", "viewer"]
