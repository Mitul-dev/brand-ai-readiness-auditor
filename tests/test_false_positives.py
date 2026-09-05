"""False-positive control.

A healthy site must produce no findings, and benign variation (legal vs trading
names, valid JavaScript use, absent optional features) must not be reported as a
problem. These tests are as important as the detection tests: the rubric rewards
precision, not finding count.
"""
from __future__ import annotations

from conftest import check_ids, find_check


def test_good_site_produces_no_findings(audit):
    report, ev, findings = audit("good_site")
    assert findings == [], \
        "healthy site produced findings: " + ", ".join(f.check_id for f in findings)
    assert report["summary"]["total_findings"] == 0
    assert report["ai_readiness"]["overall"] >= 95


def test_good_site_stays_clean_with_rendering_enabled(audit):
    report, ev, findings = audit("good_site", render=True, max_rendered_pages=6)
    assert ev.rendered_page_count >= 1
    assert "js_dependent_content" not in check_ids(findings), \
        "server-rendered pages must not be flagged as JavaScript-dependent"
    assert findings == []


def test_legal_and_trading_name_variants_are_not_a_conflict(audit):
    report, ev, findings = audit("benign_variants")
    assert "entity_name_conflict" not in check_ids(findings), (
        "'Northwind Instruments', 'Northwind Instruments Ltd' and 'Northwind' "
        "must normalize to one entity")
    names = {o["value"] for o in ev.facts_by_kind.get("organization_name", [])}
    assert len(names) >= 2, "the fixture must actually contain name variants"


def test_valid_structured_data_is_not_reported(audit):
    report, ev, findings = audit("good_site")
    ids = check_ids(findings)
    assert "invalid_structured_data" not in ids
    assert "missing_organization_identity" not in ids
    assert "missing_product_structured_data" not in ids


def test_absent_optional_features_are_not_findings(audit):
    """A small site with no blog, no products and no pricing must not be punished."""
    report, ev, findings = audit("stale_content")
    ids = check_ids(findings)
    assert "missing_product_structured_data" not in ids
    assert "no_next_step" not in ids
    # freshness is the only intended defect of this fixture
    assert "freshness_risk" in ids


def test_dimension_is_null_when_not_applicable(audit):
    report, ev, findings = audit("poor_context")
    dims = report["ai_readiness"]["dimension_keys"]
    assert dims["freshness"] is None, \
        "a site with no date signals must report freshness as not applicable"
    assert report["ai_readiness"]["explanation"]["Freshness"].startswith("not applicable")


def test_thin_check_ignores_navigation_hubs(audit):
    report, ev, findings = audit("good_site")
    hub = next(p for p in ev.pages if p.role == "products")
    assert hub.outgoing_internal_links >= 6
    assert "thin_important_page" not in check_ids(findings)


def test_low_severity_issues_do_not_dominate_the_score(audit):
    report, ev, findings = audit("invalid_structured_data")
    assert report["ai_readiness"]["overall"] >= 85, \
        "a single medium finding must not collapse the score"


def test_redirect_to_directory_form_is_not_a_chain(audit):
    report, ev, findings = audit("good_site")
    assert "redirect_chain" not in check_ids(findings)


def test_non_english_site_produces_no_findings(audit):
    """English wording heuristics must not manufacture findings on a German site."""
    report, ev, findings = audit("non_english")
    assert ev.primary_lang == "de"
    assert findings == [], \
        "non-English healthy site produced findings: " + \
        ", ".join(f.check_id for f in findings)


def test_non_english_slugs_are_classified(audit):
    """Role detection must not collapse to 'other' outside English."""
    report, ev, findings = audit("non_english")
    roles = {p.role for p in ev.pages}
    assert {"contact", "products", "pricing", "about"} <= roles


def test_ai_agent_check_is_silent_when_agents_are_allowed(audit):
    report, ev, findings = audit("good_site")
    assert "ai_crawler_blocked" not in check_ids(findings)
    assert ev.ai_agent_rules == {}


def test_valid_complete_schema_raises_no_shape_finding(audit):
    report, ev, findings = audit("good_site")
    ids = check_ids(findings)
    assert "incomplete_structured_data" not in ids
    assert "structured_visible_mismatch" not in ids


def test_same_site_cross_canonical_is_not_reported(audit):
    """Only off-site or unresolvable canonicals are findings."""
    report, ev, findings = audit("good_site")
    assert "canonical_conflict" not in check_ids(findings)


def test_sitemap_checks_silent_when_sitemap_is_healthy(audit):
    report, ev, findings = audit("good_site")
    ids = check_ids(findings)
    assert "sitemap_broken_urls" not in ids
    assert "sitemap_missing_important_pages" not in ids


def test_fp_prone_checks_carry_benign_explanations(audit):
    """Every check that can misfire must say what would make it a false positive."""
    fp_prone = {"ai_crawler_blocked", "freshness_risk", "entity_name_conflict",
                "contact_fact_conflict", "canonical_conflict",
                "incomplete_structured_data", "structured_visible_mismatch",
                "no_corroborating_entity_links", "home_purpose_unclear",
                "noindex_header_on_important_page",
                "sitemap_missing_important_pages"}
    seen: set[str] = set()
    for fixture in ("multi_problem", "ai_crawler_blocked",
                    "incomplete_structured_data", "stale_content",
                    "entity_ambiguity", "stale_sitemap", "header_noindex"):
        report, ev, findings = audit(fixture)
        for f in findings:
            if f.check_id in fp_prone:
                seen.add(f.check_id)
                assert f.benign_explanations, \
                    f"{f.check_id} can misfire but offers no benign explanation"
    assert len(seen) >= 6, f"expected to exercise more FP-prone checks, saw {seen}"
