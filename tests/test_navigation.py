"""Navigation detection regression tests.

"No <nav> element" and "no navigation" are different claims. These tests pin the
boundary: a site whose navigation works may only ever produce a low-severity
markup observation, while a site with genuinely no navigation still reports.
"""
from __future__ import annotations

import pytest

from conftest import find_check

from aira.navigation import ABSENT, PROBABLE, STRONG, WEAK, analyse_navigation

LINKS = ["/", "/about", "/products", "/contact"]


def _obs(url, *, nav=(), header=(), footer=(), internal=None,
         nav_landmark=False, header_landmark=False, footer_landmark=False):
    return {
        "url": url,
        "nav_links": list(nav),
        "header_links": list(header),
        "footer_links": list(footer),
        "internal_links": list(internal if internal is not None
                               else set(nav) | set(header) | set(footer)),
        "has_nav_landmark": nav_landmark,
        "has_header_landmark": header_landmark,
        "has_footer_landmark": footer_landmark,
    }


def _site(builder, count=5):
    pages = [builder(f"/p{i}") for i in range(count)]
    return pages, pages[0]


# --- 1. proper <nav> ---------------------------------------------------------

def test_semantic_nav_element_is_strong():
    pages, home = _site(lambda u: _obs(u, nav=LINKS, nav_landmark=True))
    nav = analyse_navigation(pages, home)
    assert nav.strength == STRONG
    assert nav.has_semantic_landmark is True


# --- 2. role=navigation (recorded by the parser as the same landmark) --------

def test_role_navigation_is_strong():
    pages, home = _site(lambda u: _obs(u, nav=LINKS, nav_landmark=True))
    assert analyse_navigation(pages, home).strength == STRONG


# --- 3. header link cluster, no <nav> ---------------------------------------

def test_header_link_cluster_without_nav_element_is_functional():
    pages, home = _site(lambda u: _obs(u, header=LINKS, header_landmark=True))
    nav = analyse_navigation(pages, home)
    assert nav.is_functional
    assert nav.has_semantic_landmark is False
    assert nav.repeated_link_count >= 3


# --- 4. footer navigation ----------------------------------------------------

def test_footer_navigation_is_functional():
    pages, home = _site(lambda u: _obs(u, footer=LINKS, footer_landmark=True))
    nav = analyse_navigation(pages, home)
    assert nav.is_functional
    assert nav.pages_with_footer_links == len(pages)


# --- 5. plain repeated links, no landmarks at all ---------------------------

def test_repeated_links_with_no_landmark_are_still_navigation():
    pages, home = _site(lambda u: _obs(u, internal=LINKS))
    nav = analyse_navigation(pages, home)
    assert nav.is_functional, "links repeated on every page are navigation"
    assert nav.repeated_link_count == len(LINKS)
    assert nav.has_semantic_landmark is False


# --- 6. genuinely navigation-poor ------------------------------------------

def test_pages_with_no_shared_links_are_absent():
    pages = [_obs(f"/p{i}", internal=[f"/only-{i}"]) for i in range(5)]
    nav = analyse_navigation(pages, pages[0])
    assert nav.strength in (ABSENT, WEAK)
    assert nav.repeated_link_count == 0


def test_isolated_pages_are_absent():
    pages = [_obs(f"/p{i}", internal=[]) for i in range(5)]
    assert analyse_navigation(pages, pages[0]).strength == ABSENT


# --- 7. rendering unavailable: raw HTML evidence is labelled as such ---------

def test_evidence_source_is_recorded():
    pages, home = _site(lambda u: _obs(u, nav=LINKS, nav_landmark=True))
    assert analyse_navigation(pages, home, "raw_html").evidence_source == "raw_html"
    assert analyse_navigation(pages, home, "rendered_dom").to_dict()[
        "evidence_source"] == "rendered_dom"


# --- 8. navigation on most but not all pages --------------------------------

def test_navigation_on_most_pages_is_still_functional():
    pages = [_obs(f"/p{i}", nav=LINKS, nav_landmark=True) for i in range(4)]
    pages.append(_obs("/odd", internal=[]))
    nav = analyse_navigation(pages, pages[0])
    assert nav.is_functional
    assert nav.pages_with_nav_landmark == 4
    assert nav.pages_considered == 5


def test_single_page_site_does_not_claim_absent_navigation():
    pages = [_obs("/", internal=LINKS + ["/faq"])]
    assert analyse_navigation(pages, pages[0]).strength == PROBABLE


# --- severity contract through the full audit -------------------------------

def test_functional_navigation_without_landmark_is_low_severity(audit):
    """The reported false positive: header/footer nav, no <nav>, was HIGH."""
    report, ev, findings = audit("nav_without_landmark")
    assert ev.navigation["strength"] in (STRONG, PROBABLE)
    assert find_check(findings, "weak_navigation") is None, \
        "functional navigation must never be reported as weak"
    f = find_check(findings, "missing_nav_landmark")
    assert f is not None
    assert f.severity == "low"
    assert f.evidence.metrics["repeated_link_count"] >= 3
    assert f.benign_explanations


def test_genuinely_absent_navigation_is_still_reported(audit):
    report, ev, findings = audit("poor_navigation")
    assert ev.navigation["strength"] == ABSENT
    f = find_check(findings, "weak_navigation")
    assert f is not None
    assert f.severity in ("medium", "high")


def test_semantic_navigation_site_reports_nothing(audit):
    report, ev, findings = audit("good_site")
    assert ev.navigation["strength"] == STRONG
    assert find_check(findings, "weak_navigation") is None
    assert find_check(findings, "missing_nav_landmark") is None


def test_missing_nav_landmark_can_never_be_high(audit):
    """Severity contract: a markup-only observation is capped at low."""
    from aira.findings import BASE_SEVERITY, resolve_severity
    assert BASE_SEVERITY["missing_nav_landmark"] == "low"
    assert resolve_severity("missing_nav_landmark", reach=1.0,
                            on_important_page=True) in ("low", "medium")
