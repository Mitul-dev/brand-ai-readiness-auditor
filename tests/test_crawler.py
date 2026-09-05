"""Crawler behaviour: bounds, robots, redirects, de-duplication."""
from __future__ import annotations

from conftest import make_config

from aira.crawler import crawl_site
from aira.urls import validate_target


def _crawl(url, **cfg):
    c = make_config(**cfg)
    return crawl_site(validate_target(url, c), c)


def test_page_limit_is_respected(serve):
    result = _crawl(serve("good_site"), max_pages=4)
    assert len(result.pages) <= 4


def test_depth_limit_is_respected(serve):
    result = _crawl(serve("good_site"), max_depth=1, max_pages=30)
    assert max(p.depth for p in result.pages) <= 1


def test_no_duplicate_urls_are_fetched(serve):
    result = _crawl(serve("good_site"), max_pages=30)
    urls = [p.url for p in result.pages]
    assert len(urls) == len(set(urls))


def test_robots_is_honoured(serve):
    result = _crawl(serve("robots_blocked"), max_pages=10)
    assert all(not p.robots_allowed for p in result.pages)
    assert all(p.html == "" for p in result.pages)


def test_robots_can_be_read_and_sitemap_discovered(serve):
    result = _crawl(serve("good_site"), max_pages=30)
    assert result.robots_status == 200
    assert result.sitemap_locations, "sitemap referenced from robots.txt should be found"
    assert len(result.sitemap_urls) >= 8


def test_missing_sitemap_is_not_an_error(serve):
    result = _crawl(serve("poor_context"))
    assert result.sitemap_locations == []
    assert result.pages, "crawl should still succeed without a sitemap"


def test_redirects_are_recorded_not_looped(serve):
    # the fixture server redirects /about -> /about/
    result = _crawl(serve("good_site"), max_pages=30)
    redirected = [p for p in result.pages if p.redirect_chain]
    assert redirected, "directory URLs should redirect"
    assert all(len(p.redirect_chain) <= 2 for p in redirected)


def test_sitemap_only_pages_are_reachable(serve):
    result = _crawl(serve("poor_navigation"), max_pages=20, max_depth=1)
    urls = {p.url for p in result.pages}
    assert any(u.endswith("/orphan-contact") for u in urls), \
        "a page linked from nowhere should still be picked up from the sitemap"
