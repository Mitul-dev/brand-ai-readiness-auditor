"""Redirect classification regression tests.

A safety refusal, a redirect misconfiguration and a dead server are three
different facts. These tests pin each one to its own outcome, severity and
report shape so they can never collapse back into "site unreachable".
"""
from __future__ import annotations

import http.server
import socket
import threading

import pytest

from conftest import find_check, make_config

from aira.config import AuditConfig
from aira.crawler import crawl_site
from aira.evidence import POLICY_REFUSAL_OUTCOMES, build_evidence
from aira.orchestrator import run_audit_with_evidence
from aira.urls import validate_target

PAGE = ('<!doctype html><html lang="en"><head><title>Northwind Instruments - hardware</title>'
        '<meta name="description" content="Calibrated hardware."></head><body>'
        '<nav><a href="/">Home</a> <a href="/about">About</a> '
        '<a href="/contact">Contact</a></nav><main><h1>{h1}</h1><p>{t}</p>'
        '<p><a href="/contact">Contact us</a></p></main></body></html>')
TEXT = ("We build calibrated measurement instruments for laboratories and support "
        "installation, training and annual servicing for research groups. ") * 3


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RouteServer:
    """Serves an exact routing table, so redirect shapes are fully controlled."""

    def __init__(self, routes):
        self.routes = routes
        self.port = _free_port()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):  # noqa: N802
                path = self.path.split("?", 1)[0].rstrip("/") or "/"
                entry = outer.routes.get(path)
                if entry is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status, headers, body = entry
                if body == "__HANG__":
                    threading.Event().wait(30)
                    return
                payload = body.encode()
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value.replace("{PORT}", str(outer.port)))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


def _page(h1: str) -> str:
    return PAGE.format(h1=h1, t=TEXT)


def _html(status=200):
    return (status, {"Content-Type": "text/html"}, _page("Calibrated instruments"))


SITE = {
    "/about": (200, {"Content-Type": "text/html"}, _page("About us")),
    "/contact": (200, {"Content-Type": "text/html"}, _page("Contact")),
}


def _audit(url, **cfg):
    return run_audit_with_evidence(url, make_config(**cfg))


def _crawl_home(url, **cfg):
    c = make_config(**cfg)
    crawl = crawl_site(validate_target(url, c), c)
    return crawl.pages[0], build_evidence(crawl, c)


# --- 1-4: ordinary redirects must resolve, not be reported ------------------

@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_single_hop_redirect_to_200_is_not_a_finding(status):
    routes = {"/": (status, {"Location": "http://127.0.0.1:{PORT}/home"}, ""),
              "/home": _html(), **SITE}
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url)
    assert ev.home_outcome == "ok"
    assert ev.home_reachable is True
    assert find_check(findings, "site_unreachable") is None
    assert find_check(findings, "homepage_redirects_offsite") is None
    assert ev.pages[0].fetched is True
    assert ev.pages[0].redirect_count == 1


def test_multi_hop_same_site_redirect_resolves():
    routes = {"/": (301, {"Location": "http://127.0.0.1:{PORT}/a"}, ""),
              "/a": (301, {"Location": "http://127.0.0.1:{PORT}/home"}, ""),
              "/home": _html(), **SITE}
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url)
    assert ev.home_outcome == "ok"
    assert ev.pages[0].redirect_count == 2
    assert find_check(findings, "site_unreachable") is None


def test_same_site_redirect_reaches_the_final_page_content():
    routes = {"/": (301, {"Location": "http://127.0.0.1:{PORT}/home"}, ""),
              "/home": _html(), **SITE}
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url)
    home = ev.home
    assert home is not None and home.word_count > 20
    assert home.fetched is True


# --- 5: cross-domain redirect refused by the safety guard -------------------

def test_cross_domain_redirect_is_low_severity_not_unreachable():
    """A country/locale redirect we decline to follow is not a site outage."""
    routes = {"/": (301, {"Location": "http://other-country.example/"}, "")}
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url)

    assert ev.home_outcome == "external_redirect"
    assert ev.home_outcome in POLICY_REFUSAL_OUTCOMES
    assert ev.home_reachable is True, "the origin answered; the site is not down"

    assert find_check(findings, "site_unreachable") is None
    f = find_check(findings, "homepage_redirects_offsite")
    assert f is not None
    assert f.severity == "low"
    assert f.suggested_action["priority"] in ("low", "medium")
    assert "other-country.example" in f.evidence.observation
    assert f.evidence.metrics["origin_responded"] is True
    assert f.evidence.metrics["destination_crawled"] is False
    assert f.benign_explanations

    assert report["summary"]["critical"] == 0
    assert report["site_context"]["home_outcome"] == "external_redirect"


def test_cross_domain_redirect_preserves_the_full_redirect_evidence():
    routes = {"/": (301, {"Location": "http://127.0.0.1:{PORT}/step"}, ""),
              "/step": (301, {"Location": "http://other-country.example/in/"}, "")}
    with RouteServer(routes) as srv:
        page, ev = _crawl_home(srv.url)
    assert page.url == ev.target_url                      # original URL
    assert page.redirect_count if hasattr(page, "redirect_count") else True
    assert len(page.redirect_chain) == 2                  # redirect chain
    # absolutize deliberately preserves the trailing slash: /in and /in/ are the
    # same URL for de-duplication but not for following a redirect.
    assert page.redirect_refused_target == "http://other-country.example/in/"
    assert page.final_attempted_url == "http://other-country.example/in/"
    assert page.redirect_refusal_reason == "external_domain"
    assert page.fetched is False                          # nothing was fetched
    assert page.final_fetched_url is None
    assert ev.home_outcome == "external_redirect"


def test_safety_guard_still_refuses_to_follow_external_redirects():
    """The fix must not weaken the guard - the destination is never fetched."""
    routes = {"/": (301, {"Location": "http://other-country.example/"}, "")}
    with RouteServer(routes) as srv:
        page, ev = _crawl_home(srv.url)
    assert page.fetched is False
    assert page.html == ""
    assert len(ev.pages) == 1


def test_score_is_not_assessed_rather_than_zero_when_nothing_was_crawled():
    routes = {"/": (301, {"Location": "http://other-country.example/"}, "")}
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url)
    assert report["ai_readiness"]["overall"] is None
    assert report["ai_readiness"]["assessed"] is False
    assert report["summary"]["ai_readiness_assessed"] is False


# --- 6-8: genuine redirect problems -----------------------------------------

def test_redirect_loop_is_a_redirect_problem():
    routes = {"/": (302, {"Location": "http://127.0.0.1:{PORT}/a"}, ""),
              "/a": (302, {"Location": "http://127.0.0.1:{PORT}/"}, "")}
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url)
    assert ev.home_outcome == "redirect_loop"
    assert ev.home_reachable is False
    f = find_check(findings, "redirect_configuration_error")
    assert f is not None
    assert f.severity in ("high", "critical")
    assert "loop" in f.title.lower()
    assert find_check(findings, "site_unreachable") is None


def test_redirect_limit_exceeded_is_a_redirect_problem():
    routes = {f"/{i}": (302, {"Location": "http://127.0.0.1:{PORT}/%d" % (i + 1)}, "")
              for i in range(1, 12)}
    routes["/"] = (302, {"Location": "http://127.0.0.1:{PORT}/1"}, "")
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url, max_redirects=3)
    assert ev.home_outcome == "redirect_limit"
    f = find_check(findings, "redirect_configuration_error")
    assert f is not None
    assert f.evidence.metrics["outcome"] == "redirect_limit"


def test_missing_location_header_is_a_redirect_problem():
    routes = {"/": (302, {}, "")}
    with RouteServer(routes) as srv:
        report, ev, findings = _audit(srv.url)
    assert ev.home_outcome == "bad_location"
    f = find_check(findings, "redirect_configuration_error")
    assert f is not None
    assert find_check(findings, "site_unreachable") is None


def test_address_guard_refuses_a_redirect_to_a_private_address():
    """The guard itself: a private redirect target is refused before any request.

    The origin must stay loopback for the fixture server to be reachable, so the
    guard is exercised directly rather than through a full crawl.
    """
    from aira.crawler import SiteCrawler

    cfg = AuditConfig(allow_private_networks=False, respect_robots=False)
    target = validate_target("https://example.com/", cfg)
    crawler = SiteCrawler(target, cfg)
    assert crawler._may_fetch("http://127.0.0.1/admin") == "non_public_address"
    assert crawler._may_fetch("http://169.254.169.254/latest/meta-data/") == \
        "non_public_address"

    # The off-site rule is checked separately: with the address guard disabled a
    # cross-domain target is refused for being off-site, not for its address.
    open_cfg = AuditConfig(allow_private_networks=True, respect_robots=False)
    open_crawler = SiteCrawler(validate_target("https://example.com/", open_cfg),
                               open_cfg)
    assert open_crawler._may_fetch("https://other-domain.example/") == "external_domain"
    assert open_crawler._may_fetch("https://example.com/page") is None


def test_private_redirect_outcome_is_reported_distinctly():
    """A refused private redirect is its own finding, never 'site unreachable'."""
    from datetime import datetime, timezone

    from aira.audits import discoverability
    from aira.crawler import RawPage
    from aira.evidence import SiteEvidence, classify_home_outcome

    raw = RawPage(url="https://example.com/", final_url="http://10.0.0.5/",
                  status=301, ok=False, depth=0,
                  redirect_chain=["https://example.com/"],
                  redirect_outcome="refused_non_public_address",
                  redirect_refusal_reason="non_public_address",
                  redirect_refused_target="http://10.0.0.5/")
    assert classify_home_outcome(raw) == "private_redirect"

    ev = SiteEvidence(site="example.com", target_url="https://example.com/",
                      audited_at=datetime.now(timezone.utc).isoformat(), config={})
    ev.home_status = 301
    ev.home_outcome = "private_redirect"
    ev.home_redirect_target = "http://10.0.0.5/"
    ev.home_reachable = True
    findings = discoverability.audit(ev, AuditConfig())
    ids = {f.check_id for f in findings}
    assert "redirect_to_private_address" in ids
    assert "site_unreachable" not in ids


# --- 9-10: genuine accessibility failures still report as such --------------

def test_connection_failure_is_site_unreachable():
    report, ev, findings = run_audit_with_evidence(
        "http://127.0.0.1:9/", make_config(request_timeout=2.0, max_pages=2))
    assert ev.home_outcome == "transport_error"
    assert ev.home_reachable is False
    f = find_check(findings, "site_unreachable")
    assert f is not None
    assert f.severity == "critical"


def test_timeout_is_site_unreachable():
    with RouteServer({"/": (200, {"Content-Type": "text/html"}, "__HANG__")}) as srv:
        report, ev, findings = _audit(srv.url, request_timeout=1.0)
    assert ev.home_outcome == "transport_error"
    f = find_check(findings, "site_unreachable")
    assert f is not None
    assert f.severity == "critical"


def test_server_error_on_homepage_is_site_unreachable():
    with RouteServer({"/": (503, {"Content-Type": "text/html"}, "down")}) as srv:
        report, ev, findings = _audit(srv.url)
    assert ev.home_outcome == "http_error"
    assert ev.home_reachable is False
    f = find_check(findings, "site_unreachable")
    assert f is not None
    assert f.evidence.metrics["home_status"] == 503


def test_not_found_homepage_is_site_unreachable():
    with RouteServer({"/other": _html()}) as srv:
        report, ev, findings = _audit(srv.url)
    assert ev.home_outcome == "http_error"
    assert find_check(findings, "site_unreachable") is not None
