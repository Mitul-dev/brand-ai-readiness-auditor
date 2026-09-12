"""Page versus non-page resource classification.

Component and fragment endpoints, JSON APIs and utility routes must not be
audited as though they were pages a visitor could land on, and must not appear
in page-level denominators.
"""
from __future__ import annotations

import pytest

from conftest import check_ids, find_check

from aira.resources import (
    API_RESOURCE, ASSET, COMPONENT_FRAGMENT, PAGE, UTILITY_ENDPOINT,
    classify_resource, path_shape,
)


def _classify(url, **kw):
    base = dict(content_type="text/html", status=200, fetched=True,
                has_html_element=True, has_head=True, has_title=True,
                word_count=400, outgoing_internal_links=10,
                incoming_internal_links=3, sibling_pattern_count=0)
    base.update(kw)
    return classify_resource(url=url, **base)


# --- fragments: identified by document shape, not by vendor URL --------------

@pytest.mark.parametrize("url", [
    "https://example.com/homepage/fragments/hero",
    "https://example.com/content-fragments/promo",
    "https://example.com/experience-fragments/site/header",
    "https://example.com/components/cta-band",
    "https://example.com/partials/footer",
    "https://example.com/blocks/teaser",
])
def test_fragment_markup_is_not_a_page(url):
    v = _classify(url, has_html_element=False, has_head=False, has_title=False,
                  word_count=4, outgoing_internal_links=0)
    assert v.is_page is False
    assert v.kind == COMPONENT_FRAGMENT


def test_naked_markup_is_a_fragment_whatever_the_url():
    """The primary signal is document shape - no vendor path vocabulary needed."""
    v = _classify("https://example.com/some/ordinary/path",
                  has_html_element=False, has_head=False, has_title=False,
                  word_count=5, outgoing_internal_links=0)
    assert v.is_page is False
    assert "without <html>" in v.reasons[0]


def test_api_and_asset_content_types_are_not_pages():
    assert _classify("https://example.com/api/v1/products",
                     content_type="application/json").kind == API_RESOURCE
    assert _classify("https://example.com/feed",
                     content_type="application/xml").kind == API_RESOURCE
    assert _classify("https://example.com/x.pdf",
                     content_type="application/pdf").kind == ASSET


def test_search_endpoint_returning_a_stub_is_a_utility_endpoint():
    v = _classify("https://example.com/search", has_title=False, word_count=5,
                  outgoing_internal_links=1)
    assert v.kind == UTILITY_ENDPOINT
    assert v.is_page is False


# --- precision: real pages must survive -------------------------------------

def test_a_real_page_is_a_page():
    assert _classify("https://example.com/products/flow-meter").is_page is True


def test_a_real_page_under_a_component_like_path_is_still_a_page():
    """A complete document is a page even if its URL contains 'modules'."""
    v = _classify("https://example.com/modules/training-courses",
                  word_count=900, outgoing_internal_links=14)
    assert v.is_page is True
    assert v.kind == PAGE


def test_a_content_page_about_apis_is_still_a_page():
    v = _classify("https://example.com/api/getting-started",
                  word_count=1200, outgoing_internal_links=18)
    assert v.is_page is True


def test_unfetched_url_is_not_treated_as_a_page():
    assert _classify("https://example.com/x", fetched=False, status=None).is_page is False


def test_path_shape_groups_repeated_implementation_urls():
    assert path_shape("https://example.com/content-fragments/a/b") == "content-fragments/a"
    assert path_shape("https://example.com/") == ""


# --- end to end: fragments must not pollute the audit -----------------------

def test_fragment_endpoints_do_not_become_important_pages(audit):
    report, ev, findings = audit("component_endpoints")
    non_pages = {p.url for p in ev.non_page_resources}
    assert len(non_pages) >= 3, "the fixture must expose component endpoints"
    for page in ev.pages:
        if page.url in non_pages:
            assert page.importance == 0.0
            assert page.is_page is False
            assert page.role == "non_page"
            assert page.resource_reasons


def test_page_level_denominators_exclude_non_pages(audit):
    report, ev, findings = audit("component_endpoints")
    real = len(ev.html_pages)
    assert real == report["site_context"]["counts"]["pages"]
    assert report["site_context"]["non_page_resources_excluded"] >= 3
    for f in findings:
        for key in ("html_pages", "pages_checked", "important_pages"):
            if key in f.evidence.metrics:
                assert f.evidence.metrics[key] <= real, \
                    f"{f.check_id} counted non-page resources in {key}"


def test_no_page_level_findings_cite_a_fragment_url(audit):
    """Issue 4: one non-page artefact must not generate a cluster of findings."""
    report, ev, findings = audit("component_endpoints")
    non_pages = {p.url for p in ev.non_page_resources}
    page_level = {"missing_h1", "thin_important_page", "no_next_step",
                  "page_identity_unclear", "important_page_orphaned",
                  "important_page_deep", "sitemap_missing_important_pages",
                  "context_loss_orphan", "missing_meta_description"}
    for f in findings:
        if f.check_id in page_level:
            cited = set(f.evidence.affected_urls)
            assert not (cited & non_pages), \
                f"{f.check_id} was raised against non-page resource(s) {cited & non_pages}"


def test_non_page_resources_are_still_recorded_as_evidence(audit):
    report, ev, findings = audit("component_endpoints")
    listed = report["site_context"]["counts"]
    assert listed["non_page_resources"] >= 3
    sample = report["site_context"]["non_page_resources"]
    assert sample and all(item["kind"] and item["reasons"] for item in sample)
