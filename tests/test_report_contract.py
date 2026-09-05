"""Report schema, finding contract, dedupe and orchestrator behaviour."""
from __future__ import annotations

import json

import pytest

from conftest import make_config

from aira.findings import (
    Evidence, Finding, SEVERITY_ORDER, compute_confidence, compute_priority,
    dedupe, finalize, resolve_severity,
)
from aira.orchestrator import AuditError, run_audit
from aira.report import assert_valid, validate_report


def _finding(check_id="entity_name_conflict", category="discoverability",
             url="https://x.com/", severity="high", reach=0.5) -> Finding:
    return Finding(
        id="X-001", check_id=check_id, category=category, title="t",
        evidence=Evidence(url=url, observation="obs", details="", metrics={"a": 1},
                          affected_urls=[url]),
        impact="i", suggested_action={"summary": "s", "priority": "medium",
                                      "steps": ["a"]},
        severity=severity, confidence=0.9, reach=reach)


# --- schema -----------------------------------------------------------------

def test_report_matches_required_schema(audit):
    report, ev, findings = audit("multi_problem")
    assert_valid(report)
    for key in ("site", "audited_at", "summary", "findings"):
        assert key in report
    for key in ("total_findings", "critical", "high", "medium"):
        assert key in report["summary"]
    for f in report["findings"]:
        for key in ("id", "title", "severity", "evidence", "suggested_action"):
            assert key in f
        assert isinstance(f["evidence"], str) and f["evidence"].strip()
        assert f["suggested_action"]["summary"]
        assert f["suggested_action"]["priority"] in ("high", "medium", "low")


def test_report_is_json_serializable(audit):
    report, ev, findings = audit("multi_problem")
    json.loads(json.dumps(report))


def test_validator_rejects_a_broken_report():
    bad = {"site": "x", "audited_at": "now",
           "summary": {"total_findings": 1, "critical": 0, "high": 0, "medium": 0},
           "findings": [{"id": "F-001", "title": "t", "severity": "nope",
                         "evidence": "", "suggested_action": {"summary": "",
                                                              "priority": "urgent"}}]}
    problems = validate_report(bad)
    assert any("severity" in p for p in problems)
    assert any("evidence" in p for p in problems)
    assert any("priority" in p for p in problems)


def test_finding_ids_are_unique_and_sequential(audit):
    report, ev, findings = audit("multi_problem")
    ids = [f["id"] for f in report["findings"]]
    assert ids == [f"F-{i:03d}" for i in range(1, len(ids) + 1)]


def test_summary_counts_match_findings(audit):
    report, ev, findings = audit("multi_problem")
    for sev in ("critical", "high", "medium", "low"):
        assert report["summary"][sev] == sum(
            1 for f in report["findings"] if f["severity"] == sev)


# --- evidence quality -------------------------------------------------------

def test_every_finding_carries_concrete_evidence(audit):
    report, ev, findings = audit("multi_problem", render=True)
    for f in report["findings"]:
        details = f["technical_details"]
        assert details["observation"], f"{f['id']} has no observation"
        assert details["metrics"], f"{f['id']} has no metrics"
        assert f["impact"], f"{f['id']} has no impact statement"
        assert f["suggested_action"]["steps"], f"{f['id']} has no fix steps"
        assert any(ch.isdigit() for ch in f["evidence"]), \
            f"{f['id']} evidence should quote a measured value: {f['evidence'][:120]}"


def test_affected_urls_are_real_crawled_urls(audit):
    report, ev, findings = audit("multi_problem")
    crawled = {p.url for p in ev.pages} | {ev.target_url,
                                           ev.target_url.rstrip("/") + "/robots.txt"}
    for f in report["findings"]:
        for url in f["affected_urls"]:
            assert url in crawled, f"{f['id']} cites a URL that was never crawled: {url}"


# --- deterministic scoring --------------------------------------------------

def test_severity_is_deterministic_and_capped():
    assert resolve_severity("robots_blocks_site", reach=1.0,
                            on_important_page=True) == "critical"
    # a widespread engagement problem must not outrank a blocking failure
    assert resolve_severity("no_next_step", reach=1.0,
                            on_important_page=True) == "high"
    assert resolve_severity("missing_meta_description", reach=0.05,
                            on_important_page=False) == "low"


def test_confidence_reflects_evidence_quality():
    strong, reason = compute_confidence(deterministic=True, sample_size=16,
                                        affected=14, direct_dom_evidence=True)
    weak, _ = compute_confidence(deterministic=True, sample_size=1, affected=1,
                                 direct_dom_evidence=False,
                                 conflicting_signals=True)
    assert strong > weak
    assert 0.3 <= weak < strong <= 0.98
    assert "14/16" in reason or "sample" in reason


def test_priority_is_explainable_and_monotone():
    high = _finding(severity="critical", reach=1.0)
    low = _finding(severity="low", reach=0.1)
    hband, hscore, hreason = compute_priority(high)
    lband, lscore, lreason = compute_priority(low)
    assert hscore > lscore
    assert hband == "high" and lband == "low"
    assert "impact" in hreason and "reach" in hreason


# --- dedupe -----------------------------------------------------------------

def test_same_check_on_same_scope_is_merged():
    a = _finding(check_id="entity_name_conflict", category="discoverability")
    b = _finding(check_id="entity_name_conflict", category="discoverability")
    b.evidence.affected_urls = ["https://x.com/about"]
    b.evidence.observation = "organization name differs across pages"
    merged = dedupe([a, b])
    assert len(merged) == 1
    assert set(merged[0].evidence.affected_urls) == {"https://x.com/",
                                                     "https://x.com/about"}
    assert "Corroborated by" in merged[0].evidence.details


def test_cross_module_group_is_merged():
    """Synonymous reachability checks collapse into one finding."""
    a = _finding(check_id="important_page_deep")
    b = _finding(check_id="important_page_orphaned")
    assert len(dedupe([a, b])) == 1


def test_findings_from_different_categories_are_never_merged():
    """Crawler reachability and visitor context loss are different problems."""
    a = _finding(check_id="important_page_deep", category="discoverability")
    b = _finding(check_id="context_loss_orphan", category="engagement")
    assert len(dedupe([a, b])) == 2


def test_merge_keeps_the_higher_severity():
    a = _finding(check_id="important_page_deep", severity="medium")
    b = _finding(check_id="important_page_deep", severity="high")
    merged = dedupe([a, b])[0]
    assert merged.severity == "high"


def test_distinct_checks_are_not_merged():
    a = _finding(check_id="missing_h1")
    b = _finding(check_id="invalid_structured_data")
    assert len(dedupe([a, b])) == 2


def test_finalize_orders_and_renumbers():
    items = finalize([_finding(severity="low", reach=0.1),
                      _finding(check_id="site_unreachable", severity="critical",
                               reach=1.0)])
    assert items[0].severity == "critical"
    assert [f.id for f in items] == ["F-001", "F-002"]


# --- orchestrator safety ----------------------------------------------------

def test_orchestrator_rejects_private_targets_by_default():
    with pytest.raises(AuditError):
        run_audit("http://127.0.0.1:1/", make_config(allow_private_networks=False))


def test_orchestrator_rejects_malformed_input():
    for bad in ("", "not a url", "file:///etc/passwd"):
        with pytest.raises(AuditError):
            run_audit(bad, make_config())


def test_audit_survives_an_unreachable_host(serve):
    """A dead port must yield a report, not an exception."""
    report = run_audit("http://127.0.0.1:9/",
                       make_config(request_timeout=2.0, max_pages=2))
    assert_valid(report)
    assert report["findings"][0]["severity"] == "critical"
    assert report["findings"][0]["title"].lower().startswith("the site homepage")
