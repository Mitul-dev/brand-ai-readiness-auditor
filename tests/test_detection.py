"""Detection tests.

Each fixture encodes a known defect. Assertions check the *evidence* - the check
that fired, the journey stage, the numbers in the metrics and the severity band -
rather than merely that some finding exists.
"""
from __future__ import annotations

import pytest

from conftest import check_ids, find_check


# --- 2. ROBOTS-BLOCKED SITE ------------------------------------------------

def test_robots_blocked_site(audit):
    report, ev, findings = audit("robots_blocked")
    f = find_check(findings, "robots_blocks_site")
    assert f is not None, "a site-wide robots disallow must be reported"
    assert f.severity == "critical"
    assert f.journey_stage == "discover"
    assert "Disallow: /" in f.evidence.observation
    assert f.suggested_action["priority"] == "high"
    # it must not be misreported as an unreachable site
    assert "site_unreachable" not in check_ids(findings)


# --- 3. JAVASCRIPT-ONLY CONTENT --------------------------------------------

def test_javascript_only_content(audit):
    report, ev, findings = audit("js_only", render=True, max_rendered_pages=6)
    f = find_check(findings, "js_dependent_content")
    assert f is not None, "content added only by JavaScript must be detected"
    assert f.journey_stage == "extract"
    assert f.severity in ("high", "medium")
    m = f.evidence.metrics
    assert m["js_dependent_pages"] >= 1
    assert m["max_added_word_ratio"] >= m["threshold"]
    # evidence must quote the actual raw-vs-rendered numbers
    assert "initial HTML contains" in f.evidence.observation
    assert "rendered DOM contains" in f.evidence.observation
    steps = " ".join(f.suggested_action["steps"]).lower()
    assert "server-side" in steps or "ssr" in steps


def test_javascript_check_is_not_applicable_without_rendering(audit):
    report, ev, findings = audit("js_only", render=False)
    assert "js_dependent_content" not in check_ids(findings), \
        "the rendering check must stay silent when rendering did not run"
    assert ev.rendered_page_count == 0


# --- 4. MISSING STRUCTURED DATA --------------------------------------------

def test_missing_structured_data(audit):
    report, ev, findings = audit("missing_structured_data")
    f = find_check(findings, "missing_organization_identity")
    assert f is not None
    assert f.journey_stage == "represent"
    assert f.evidence.metrics["pages_with_org_schema"] == 0
    assert f.evidence.metrics["html_pages"] >= 5
    assert "0 of" in f.evidence.observation
    p = find_check(findings, "missing_product_structured_data")
    assert p is not None, "product-style pages without Product schema should be reported"
    assert p.evidence.metrics["with_product_schema"] == 0


# --- 5. INVALID STRUCTURED DATA --------------------------------------------

def test_invalid_structured_data(audit):
    report, ev, findings = audit("invalid_structured_data")
    f = find_check(findings, "invalid_structured_data")
    assert f is not None
    assert f.journey_stage == "extract"
    assert "JSONDecodeError" in f.evidence.observation
    assert f.evidence.metrics["pages_with_invalid_jsonld"] >= 1
    # the valid blocks elsewhere must not be reported as missing
    assert "missing_organization_identity" not in check_ids(findings)


# --- 6. STALE CONTENT -------------------------------------------------------

def test_stale_content_is_reported_as_a_risk(audit):
    report, ev, findings = audit("stale_content")
    f = find_check(findings, "freshness_risk")
    assert f is not None
    assert f.journey_stage == "trust"
    assert f.severity in ("medium", "low"), "staleness is a risk, not a blocker"
    assert "Potential freshness risk" in f.title
    assert f.evidence.metrics["newest_year_found"] <= 2020
    assert f.confidence <= 0.85, "indirect evidence must not claim high confidence"
    assert "does not prove" in f.evidence.details


# --- 7. ENTITY AMBIGUITY ----------------------------------------------------

def test_entity_ambiguity(audit):
    report, ev, findings = audit("entity_ambiguity")
    f = find_check(findings, "entity_name_conflict")
    assert f is not None
    assert f.journey_stage == "represent"
    assert f.dimension == "entity_clarity"
    assert f.evidence.metrics["distinct_name_clusters"] >= 2
    variants = " ".join(f.evidence.metrics["variants"]).lower()
    assert "vertex" in variants or "zenith" in variants or "helios" in variants
    assert f.severity == "high"


def test_contact_fact_conflict(audit):
    report, ev, findings = audit("entity_ambiguity")
    f = find_check(findings, "contact_fact_conflict")
    assert f is not None, "structured data disagreeing with the page must be reported"
    assert f.dimension == "fact_consistency"
    assert f.evidence.metrics["distinct_values"] >= 2


# --- 8. POOR NAVIGATION -----------------------------------------------------

def test_poor_navigation(audit):
    report, ev, findings = audit("poor_navigation")
    ids = check_ids(findings)
    assert "weak_navigation" in ids
    nav = find_check(findings, "weak_navigation")
    assert nav.evidence.metrics["pages_with_nav_landmark"] == 0
    assert nav.category == "engagement"
    orphan = find_check(findings, "important_page_orphaned")
    assert orphan is not None, "the unlinked contact page should be reported"
    assert orphan.evidence.metrics["orphan_pages"] >= 1


def test_deep_important_page_is_reported(audit):
    report, ev, findings = audit("poor_navigation", max_depth=5, max_pages=20)
    reach = find_check(findings, "important_page_deep") or \
        find_check(findings, "important_page_orphaned")
    assert reach is not None
    urls = " ".join(reach.evidence.affected_urls)
    assert "pricing" in urls or "contact" in urls


# --- 9. POOR CONTEXT RETENTION ---------------------------------------------

def test_poor_context_retention(audit):
    report, ev, findings = audit("poor_context")
    ids = check_ids(findings)
    assert "home_purpose_unclear" in ids
    assert "context_loss_orphan" in ids or "weak_navigation" in ids
    home = find_check(findings, "home_purpose_unclear")
    assert home.category == "engagement"
    assert "title" in home.evidence.observation.lower()


# --- 10. MULTIPLE SIMULTANEOUS PROBLEMS ------------------------------------

def test_multi_problem_site(audit):
    report, ev, findings = audit("multi_problem", render=True, max_rendered_pages=6)
    ids = check_ids(findings)
    expected = {"missing_organization_identity", "invalid_structured_data",
                "js_dependent_content", "home_purpose_unclear"}
    missing = expected - ids
    assert not missing, f"expected checks not raised: {sorted(missing)}"
    assert report["summary"]["total_findings"] >= 6
    assert report["ai_readiness"]["overall"] < 80
    # both audit areas must be represented
    categories = {f["category"] for f in report["findings"]}
    assert {"discoverability", "engagement"} <= categories


def test_severity_ordering_and_priority(audit):
    report, ev, findings = audit("multi_problem")
    order = ["critical", "high", "medium", "low"]
    seen = [order.index(f["severity"]) for f in report["findings"]]
    assert seen == sorted(seen), "findings must be ordered by severity"
    for f in report["findings"]:
        assert 0.0 < f["priority_score"] <= 1.0
        assert f["priority_reason"], "priority must be explainable"
        assert f["confidence_reason"], "confidence must be explainable"


# --- 11. AI / ANSWER-ENGINE CRAWLERS BLOCKED --------------------------------

def test_named_ai_crawlers_blocked_in_robots(audit):
    """General crawling is allowed; the AI agents are singled out and disallowed."""
    report, ev, findings = audit("ai_crawler_blocked")
    f = find_check(findings, "ai_crawler_blocked")
    assert f is not None, "a robots.txt group disallowing AI crawlers must be detected"
    assert f.journey_stage == "discover"
    assert f.severity == "high"
    blocked = set(f.evidence.metrics["blocked_agents"])
    assert {"gptbot", "claudebot", "google-extended"} <= blocked
    # a partial restriction is recorded but not counted as a full block
    assert "perplexitybot" in f.evidence.metrics["partially_restricted_agents"]
    assert "perplexitybot" not in blocked
    # the site is not otherwise blocked, so the site-wide check must stay silent
    assert "robots_blocks_site" not in check_ids(findings)
    assert f.benign_explanations, "a deliberate content policy must be acknowledged"


# --- 12. STRUCTURED DATA THAT PARSES BUT IS UNUSABLE ------------------------

def test_incomplete_structured_data(audit):
    report, ev, findings = audit("incomplete_structured_data")
    f = find_check(findings, "incomplete_structured_data")
    assert f is not None, "valid JSON with missing required properties must be caught"
    assert f.journey_stage == "extract"
    obs = f.evidence.observation
    assert "'name' is empty" in obs or "has no 'url'" in obs
    assert "placeholder" in obs.lower() or any(
        "placeholder" in d.lower() for defs in
        f.evidence.metrics["defects"].values() for d in defs)


def test_structured_data_contradicting_the_visible_page(audit):
    report, ev, findings = audit("incomplete_structured_data")
    f = find_check(findings, "structured_visible_mismatch")
    assert f is not None, "a machine-readable name that differs from the H1 must be caught"
    assert f.dimension == "fact_consistency"
    example = f.evidence.metrics["examples"][0]
    assert example["structured"] != example["visible"]
    assert "Zenith" in example["structured"]


# --- 13. NOINDEX DELIVERED AS AN HTTP HEADER --------------------------------

def test_noindex_response_header_is_detected(audit):
    report, ev, findings = audit("header_noindex")
    f = find_check(findings, "noindex_header_on_important_page")
    assert f is not None, "X-Robots-Tag must be checked, not only the meta tag"
    assert "X-Robots-Tag" in f.evidence.observation
    assert f.severity == "high"


# --- 14. SITEMAP HEALTH ------------------------------------------------------

def test_sitemap_drift_is_detected(audit):
    report, ev, findings = audit("stale_sitemap")
    broken = find_check(findings, "sitemap_broken_urls")
    assert broken is not None, "sitemap entries that 404 must be reported"
    assert broken.evidence.metrics["broken_sitemap_urls"] >= 1
    assert "404" in broken.evidence.observation
    missing = find_check(findings, "sitemap_missing_important_pages")
    assert missing is not None, "important pages absent from the sitemap must be reported"
    assert missing.severity in ("low", "medium")
