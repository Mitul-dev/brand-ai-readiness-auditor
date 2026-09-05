"""Audit orchestrator - the single composition point.

Deterministic from end to end: validate -> crawl -> evidence -> audits ->
normalize -> dedupe -> score -> report -> schema check. The agent layer sits
*around* this, interpreting and presenting the result; it does not decide
severity, confidence or priority.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .audits import discoverability, engagement, freshness
from .config import AuditConfig
from .crawler import crawl_site
from .evidence import SiteEvidence, build_evidence
from .findings import Finding, dedupe, finalize
from .report import assert_valid, build_report, validate_report
from .scoring import compute_score
from .urls import UnsafeUrlError, validate_target

log = logging.getLogger("aira.orchestrator")

AuditFn = Callable[[SiteEvidence, AuditConfig], list[Finding]]

AUDIT_MODULES: dict[str, AuditFn] = {
    "discoverability-audit": discoverability.audit,
    "freshness-corroboration": freshness.audit,
    "engagement-audit": engagement.audit,
}


class AuditError(RuntimeError):
    pass


def run_audit(url: str, config: AuditConfig | None = None, *,
              include_evidence_model: bool = False,
              modules: list[str] | None = None) -> dict[str, Any]:
    """Run a full audit and return a schema-valid report dictionary."""
    cfg = config or AuditConfig()
    started = time.perf_counter()

    try:
        target = validate_target(url, cfg)
    except UnsafeUrlError as exc:
        raise AuditError(f"invalid or unsafe audit target: {exc}") from exc
    log.info("auditing %s", target.url)

    crawl = crawl_site(target, cfg)
    evidence = build_evidence(crawl, cfg)

    selected = modules or list(AUDIT_MODULES)
    raw_findings: list[Finding] = []
    for name in selected:
        fn = AUDIT_MODULES.get(name)
        if fn is None:
            log.warning("unknown audit module ignored: %s", name)
            continue
        try:
            produced = fn(evidence, cfg)
        except Exception:  # a broken check must not sink the whole audit
            log.exception("audit module %s failed", name)
            evidence.notes.append(f"audit module {name} failed and was skipped")
            continue
        for i, f in enumerate(produced, start=1):
            f.id = f"{name[:1].upper()}-{i:03d}"
        raw_findings.extend(produced)
        log.info("%s produced %d finding(s)", name, len(produced))

    merged = dedupe(raw_findings)
    findings = finalize(merged)
    score = compute_score(findings, evidence)
    runtime = time.perf_counter() - started
    report = build_report(evidence, findings, score, runtime_s=runtime,
                          include_evidence_model=include_evidence_model)
    assert_valid(report)
    return report


def run_audit_with_evidence(url: str, config: AuditConfig | None = None
                            ) -> tuple[dict[str, Any], SiteEvidence, list[Finding]]:
    """Variant used by tests: returns the report plus the intermediate objects."""
    cfg = config or AuditConfig()
    started = time.perf_counter()
    target = validate_target(url, cfg)
    crawl = crawl_site(target, cfg)
    evidence = build_evidence(crawl, cfg)
    raw: list[Finding] = []
    for name, fn in AUDIT_MODULES.items():
        produced = fn(evidence, cfg)
        for i, f in enumerate(produced, start=1):
            f.id = f"{name[:1].upper()}-{i:03d}"
        raw.extend(produced)
    findings = finalize(dedupe(raw))
    score = compute_score(findings, evidence)
    report = build_report(evidence, findings, score,
                          runtime_s=time.perf_counter() - started)
    problems = validate_report(report)
    if problems:
        raise AuditError("; ".join(problems))
    return report, evidence, findings
