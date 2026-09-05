"""URL normalization, SSRF guard and crawl-bound tests."""
from __future__ import annotations

import pytest

from aira.config import AuditConfig
from aira.urls import (
    UnsafeUrlError, looks_like_page, normalize_url, path_depth,
    registrable_host, same_site, validate_target,
)


@pytest.mark.parametrize("raw,expected", [
    ("HTTP://Example.com:80/a//b/?utm_source=x&q=1#frag", "http://example.com/a/b?q=1"),
    ("https://Example.com", "https://example.com/"),
    ("https://example.com/path/", "https://example.com/path"),
    ("https://example.com/?gclid=1", "https://example.com/"),
])
def test_normalize(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["mailto:a@b.com", "javascript:void(0)", "#top",
                                 "data:text/html,x", "ftp://example.com/x"])
def test_normalize_rejects_non_pages(raw):
    assert normalize_url(raw) is None


def test_duplicate_urls_collapse():
    a = normalize_url("https://example.com/page?b=2&utm_medium=x")
    b = normalize_url("https://example.com/page/?b=2")
    assert a == b


def test_asset_urls_are_not_pages():
    assert not looks_like_page("https://x.com/a.js")
    assert not looks_like_page("https://x.com/img/a.PNG")
    assert looks_like_page("https://x.com/products/widget")


def test_same_site_and_registrable_host():
    assert registrable_host("www.Example.com") == "example.com"
    assert same_site("https://www.a.com/x", "https://a.com/y")
    assert not same_site("https://a.com/x", "https://b.com/y")


def test_depth():
    assert path_depth("https://a.com/") == 0
    assert path_depth("https://a.com/a/b/c") == 3


def test_ssrf_guard_blocks_private_targets():
    cfg = AuditConfig()
    for target in ("http://127.0.0.1:8000", "http://localhost/", "http://169.254.169.254/"):
        with pytest.raises(UnsafeUrlError):
            validate_target(target, cfg)


def test_ssrf_guard_can_be_opened_for_local_fixtures():
    cfg = AuditConfig(allow_private_networks=True)
    assert validate_target("http://127.0.0.1:8000", cfg).host == "127.0.0.1"


def test_credentials_and_schemes_rejected():
    cfg = AuditConfig(allow_private_networks=True)
    with pytest.raises(UnsafeUrlError):
        validate_target("http://user:pw@127.0.0.1/", cfg)
    with pytest.raises(UnsafeUrlError):
        validate_target("file:///etc/passwd", cfg)


def test_bare_domain_gets_https():
    cfg = AuditConfig(allow_private_networks=True)
    assert validate_target("127.0.0.1", cfg).scheme == "https"
