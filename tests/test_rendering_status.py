"""Rendering status must be stated, never inferred from a zero.

"0 pages rendered" can mean the browser was missing, every navigation failed,
the budget ran out, or nothing needed rendering. A report that cannot tell those
apart invites the reader to conclude that JavaScript was irrelevant.
"""
from __future__ import annotations

import pytest

from conftest import find_check, make_config

from aira.config import AuditConfig
from aira.render import (
    ALL_FAILED, BROWSER_UNAVAILABLE, COMPLETE, NOT_REQUESTED, NO_CANDIDATES,
    RenderRun, render_pages,
)


def test_rendering_disabled_is_reported_as_not_requested():
    run = render_pages(["https://example.com/"], AuditConfig(render=False))
    assert run.status == NOT_REQUESTED
    assert run.evidence_available is False
    assert "disabled" in run.detail


def test_no_candidates_is_distinct_from_failure():
    run = render_pages([], AuditConfig(render=True))
    assert run.status == NO_CANDIDATES
    assert run.evidence_available is False
    assert run.failed == 0


def test_browser_unavailable_is_its_own_status(monkeypatch):
    monkeypatch.setattr("aira.render.renderer_available",
                        lambda: (False, "playwright not importable"))
    run = render_pages(["https://example.com/"], AuditConfig(render=True))
    assert run.status == BROWSER_UNAVAILABLE
    assert run.evidence_available is False
    assert "playwright" in (run.error_sample or "")


def test_every_status_is_carried_into_the_report(audit):
    report, ev, findings = audit("good_site", render=False)
    rendering = report["site_context"]["rendering"]
    assert rendering["status"] == NOT_REQUESTED
    assert rendering["evidence_available"] is False
    assert rendering["detail"]


def test_zero_rendered_never_silently_implies_javascript_is_absent(audit):
    report, ev, findings = audit("js_only", render=False)
    assert report["summary"]["pages_rendered"] == 0
    assert ev.render_evidence_available is False
    # The audit must say so rather than leaving the zero to be interpreted.
    assert any("rendering evidence unavailable" in n for n in ev.notes)
    # and must make no JavaScript claim at all
    assert find_check(findings, "js_dependent_content") is None


def test_absence_claims_are_caveated_without_rendered_evidence(audit):
    """A 'thin content' claim is weaker when JS content could not be seen."""
    report, ev, findings = audit("multi_problem", render=False)
    thin = find_check(findings, "thin_important_page")
    if thin is None:
        pytest.skip("fixture did not raise the thin-content check")
    assert "No rendered evidence was available" in thin.evidence.details
    assert thin.benign_explanations
    assert thin.confidence <= 0.85


def test_successful_rendering_reports_complete(audit):
    report, ev, findings = audit("good_site", render=True, max_rendered_pages=3)
    rendering = report["site_context"]["rendering"]
    assert rendering["status"] in (COMPLETE, "partial")
    assert rendering["evidence_available"] is True
    assert rendering["succeeded"] >= 1
    assert ev.render_evidence_available is True


def test_rendering_evidence_flag_drives_the_navigation_source_label(audit):
    report, ev, findings = audit("good_site", render=False)
    assert ev.navigation["evidence_source"] == "raw_html"
