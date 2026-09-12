"""Safe, bounded, read-only site crawler.

Guarantees:
  * GET/HEAD only - never posts, never submits forms, never authenticates.
  * robots.txt is fetched once and honoured (configurable, on by default).
  * Hard caps on pages, depth, bytes, concurrency and total wall-clock time.
  * URL de-duplication after normalization; redirect chains recorded, not looped.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import robotparser
from urllib.parse import urlsplit, urljoin

import httpx
from bs4 import BeautifulSoup

from .config import AuditConfig
from .urls import (
    Target, absolutize, normalize_url, looks_like_page, same_site, path_depth,
    resolve_is_private,
)

log = logging.getLogger("aira.crawler")

HTML_TYPES = ("text/html", "application/xhtml")

# Paths that lead into account, authentication or transactional areas. The audit
# is read-only and never touches authenticated areas, so these are not crawled at
# all - which also keeps them out of the findings, where they would be noise.
SKIP_PATH_TOKENS = (
    "login", "signin", "sign-in", "logout", "signout", "register", "signup",
    "sign-up", "account", "cart", "basket", "checkout", "password", "auth",
    "oauth", "admin", "wp-admin", "wp-login",
)


def parse_robots_groups(robots_txt: str | None) -> dict[str, dict[str, list[str]]]:
    """Parse robots.txt into ``{user_agent: {"allow": [...], "disallow": [...]}}``.

    ``urllib.robotparser`` answers "may *I* fetch this?" but cannot tell us what a
    *different* named agent is allowed to do. Retrieval-oriented crawlers are
    routinely named individually in robots.txt, so the audit needs the raw groups.
    """
    groups: dict[str, dict[str, list[str]]] = {}
    if not robots_txt:
        return groups
    current: list[str] = []
    expecting_agent = True
    for line in robots_txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            if not expecting_agent:
                current = []
                expecting_agent = True
            agent = val.lower()
            current.append(agent)
            groups.setdefault(agent, {"allow": [], "disallow": []})
        elif key in ("allow", "disallow") and current:
            expecting_agent = False
            for agent in current:
                groups[agent][key].append(val)
    return groups


def is_account_path(url: str) -> bool:
    import re as _re
    path = (urlsplit(url).path or "").lower()
    tokens = {t for t in _re.split(r"[/\-_.]+", path) if t}
    return bool(tokens & set(SKIP_PATH_TOKENS))


@dataclass(slots=True)
class RawPage:
    """One fetched page, before any interpretation."""
    url: str
    final_url: str
    status: int | None
    ok: bool
    depth: int
    redirect_chain: list[str] = field(default_factory=list)
    content_type: str = ""
    html: str = ""
    elapsed_ms: int = 0
    error: str | None = None
    robots_allowed: bool = True
    from_sitemap: bool = False
    discovered_from: str | None = None
    truncated: bool = False
    x_robots_tag: str = ""
    # --- redirect outcome ------------------------------------------------
    # A safety refusal is not the same event as a failed fetch, and the two must
    # stay distinguishable all the way into the report. ``fetched`` records
    # whether a final response body was actually retrieved; ``redirect_outcome``
    # records why the chain ended.
    fetched: bool = False
    redirect_outcome: str = "none"
    redirect_refusal_reason: str | None = None
    redirect_refused_target: str | None = None
    final_attempted_url: str = ""

    @property
    def final_fetched_url(self) -> str | None:
        return self.final_url if self.fetched else None


@dataclass(slots=True)
class CrawlResult:
    target: Target
    pages: list[RawPage] = field(default_factory=list)
    robots_txt: str | None = None
    robots_status: int | None = None
    robots_groups: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    robots_error: str | None = None
    sitemap_urls: list[str] = field(default_factory=list)
    sitemap_locations: list[str] = field(default_factory=list)
    sitemap_status: dict[str, int] = field(default_factory=dict)
    home_status: int | None = None
    budget_exhausted: bool = False
    notes: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def by_url(self) -> dict[str, RawPage]:
        return {p.final_url: p for p in self.pages}


class SiteCrawler:
    def __init__(self, target: Target, config: AuditConfig) -> None:
        self.target = target
        self.cfg = config
        self.result = CrawlResult(target=target)
        self._robots: robotparser.RobotFileParser | None = None
        self._seen: set[str] = set()
        self._started = 0.0

    # -- robots ---------------------------------------------------------
    async def _load_robots(self, client: httpx.AsyncClient) -> None:
        robots_url = urljoin(self.target.url, "/robots.txt")
        rp = robotparser.RobotFileParser()
        try:
            resp = await client.get(robots_url, follow_redirects=True)
            self.result.robots_status = resp.status_code
            if resp.status_code == 200 and resp.text:
                self.result.robots_txt = resp.text[:200_000]
                rp.parse(self.result.robots_txt.splitlines())
            else:
                rp.parse([])  # no robots.txt -> everything allowed
            self.result.robots_groups = parse_robots_groups(self.result.robots_txt)
        except Exception as exc:  # network / TLS / timeout
            self.result.robots_error = f"{type(exc).__name__}: {exc}"
            rp.parse([])
        self._robots = rp

    def allowed(self, url: str) -> bool:
        if not self.cfg.respect_robots or self._robots is None:
            return True
        try:
            return self._robots.can_fetch(self.cfg.user_agent, url) or \
                   self._robots.can_fetch("*", url)
        except Exception:
            return True

    # -- sitemap --------------------------------------------------------
    async def _load_sitemaps(self, client: httpx.AsyncClient) -> None:
        started = time.perf_counter()
        candidates: list[str] = []
        if self.result.robots_txt:
            for line in self.result.robots_txt.splitlines():
                if line.lower().startswith("sitemap:"):
                    loc = line.split(":", 1)[1].strip()
                    if loc:
                        candidates.append(loc)
        candidates.append(urljoin(self.target.url, "/sitemap.xml"))
        seen: set[str] = set()
        urls: list[str] = []
        for cand in candidates[:5]:
            if time.perf_counter() - started > (self.cfg.total_crawl_budget_s * 0.25):
                break
            norm = normalize_url(cand, self.target.url)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            try:
                resp = await client.get(norm, follow_redirects=True)
            except Exception:
                continue
            self.result.sitemap_status[norm] = resp.status_code
            if resp.status_code != 200:
                continue
            self.result.sitemap_locations.append(norm)
            urls.extend(self._parse_sitemap(resp.text, norm))
            # one level of sitemap-index expansion, bounded
            for child in self._sitemap_children(resp.text, norm)[:5]:
                if time.perf_counter() - started > (self.cfg.total_crawl_budget_s * 0.25):
                    break
                if child in seen:
                    continue
                seen.add(child)
                try:
                    cresp = await client.get(child, follow_redirects=True)
                except Exception:
                    continue
                self.result.sitemap_status[child] = cresp.status_code
                if cresp.status_code == 200:
                    self.result.sitemap_locations.append(child)
                    urls.extend(self._parse_sitemap(cresp.text, child))
        out: list[str] = []
        for u in urls:
            n = normalize_url(u, self.target.url)
            if n and n not in out:
                out.append(n)
        self.result.sitemap_urls = out[:2000]

    @staticmethod
    def _parse_sitemap(text: str, base: str) -> list[str]:
        try:
            soup = BeautifulSoup(text, "xml")
        except Exception:
            return []
        if soup.find("sitemapindex"):
            return []
        return [loc.get_text(strip=True) for loc in soup.find_all("loc")]

    @staticmethod
    def _sitemap_children(text: str, base: str) -> list[str]:
        try:
            soup = BeautifulSoup(text, "xml")
        except Exception:
            return []
        if not soup.find("sitemapindex"):
            return []
        return [loc.get_text(strip=True) for loc in soup.find_all("loc")]

    # -- fetching -------------------------------------------------------
    async def _fetch(self, client: httpx.AsyncClient, url: str, depth: int,
                     src: str | None) -> RawPage:
        page = RawPage(url=url, final_url=url, status=None, ok=False,
                       depth=depth, discovered_from=src)
        page.final_attempted_url = url
        if not self.allowed(url):
            page.robots_allowed = False
            page.error = "blocked by robots.txt"
            page.redirect_outcome = "refused_robots"
            return page
        host = urlsplit(url).hostname or ""
        if not self.cfg.allow_private_networks and resolve_is_private(host):
            page.error = "refused: non-public address"
            page.redirect_outcome = "refused_non_public_address"
            return page
        t0 = time.perf_counter()
        try:
            await self._get_following_redirects(client, url, page)
        except Exception as exc:
            page.error = f"{type(exc).__name__}: {exc}"
            if page.redirect_outcome == "none":
                page.redirect_outcome = "transport_error"
        page.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return page

    async def _get_following_redirects(self, client: httpx.AsyncClient, url: str,
                                       page: RawPage) -> None:
        """Follow redirects by hand, re-validating every hop.

        httpx's own ``follow_redirects`` would send us wherever the server points,
        including at a private address - a classic SSRF via open redirect. Each hop
        is therefore re-checked against the robots rules and the address guard, and
        the body is read as a stream so an oversized response can never be buffered
        whole.
        """
        current = url
        visited: set[str] = {url}
        for hop in range(self.cfg.max_redirects + 1):
            async with client.stream("GET", current) as resp:
                page.status = resp.status_code
                page.content_type = resp.headers.get("content-type", "")
                page.x_robots_tag = resp.headers.get("x-robots-tag", "")
                if resp.is_redirect and hop < self.cfg.max_redirects:
                    location = resp.headers.get("location", "")
                    nxt = absolutize(location, current)
                    if not nxt:
                        page.redirect_outcome = "bad_location"
                        page.error = (f"redirect response with an unusable Location "
                                      f"header: {location!r}")
                        page.final_attempted_url = current
                        return
                    if nxt in visited:
                        page.redirect_outcome = "loop"
                        page.error = f"redirect loop back to {nxt}"
                        page.final_attempted_url = nxt
                        return
                    visited.add(nxt)
                    page.redirect_chain.append(current)
                    verdict = self._may_fetch(nxt)
                    if verdict is not None:
                        # The origin server answered correctly; we are declining to
                        # follow it. That is a policy decision about *us*, not a
                        # statement about the availability of the site.
                        page.redirect_outcome = f"refused_{verdict}"
                        page.redirect_refusal_reason = verdict
                        page.redirect_refused_target = nxt
                        page.robots_allowed = verdict != "robots"
                        page.error = (f"redirect to {nxt} not followed "
                                      f"({verdict.replace('_', ' ')})")
                        page.final_url = nxt
                        page.final_attempted_url = nxt
                        return
                    current = nxt
                    page.redirect_outcome = "followed"
                    continue
                if resp.is_redirect:
                    page.redirect_outcome = "limit_exceeded"
                    page.error = (f"redirect limit of {self.cfg.max_redirects} "
                                  "hops exceeded")
                    page.final_attempted_url = current
                    return
                page.final_url = normalize_url(current) or current
                page.final_attempted_url = page.final_url
                page.fetched = True
                is_html = (any(t in page.content_type.lower() for t in HTML_TYPES)
                           or not page.content_type)
                if is_html:
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= self.cfg.max_bytes_per_page:
                            page.truncated = True
                            break
                    body = b"".join(chunks)[: self.cfg.max_bytes_per_page]
                    page.html = body.decode(resp.encoding or "utf-8",
                                            errors="replace")
                page.ok = 200 <= resp.status_code < 300
                return

    def _may_fetch(self, url: str) -> str | None:
        """Return a stable refusal code, or None when the URL may be fetched.

        Codes (not prose) so that downstream classification never has to match on
        wording: ``robots``, ``non_public_address``, ``external_domain``.
        """
        if not self.allowed(url):
            return "robots"
        host = urlsplit(url).hostname or ""
        if not self.cfg.allow_private_networks and resolve_is_private(host):
            return "non_public_address"
        if self.cfg.same_site_only and not same_site(url, self.target.url):
            return "external_domain"
        return None

    @staticmethod
    def extract_links(html: str, base_url: str) -> list[str]:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return []
        out: list[str] = []
        for a in soup.find_all("a", href=True):
            n = normalize_url(a["href"], base_url)
            if n:
                out.append(n)
        return out

    def _budget_left(self) -> bool:
        return (time.perf_counter() - self._started) < self.cfg.total_crawl_budget_s

    async def crawl(self) -> CrawlResult:
        self._started = time.perf_counter()
        limits = httpx.Limits(max_connections=self.cfg.concurrency,
                              max_keepalive_connections=self.cfg.concurrency)
        headers = {"User-Agent": self.cfg.user_agent,
                   "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=self.cfg.request_timeout,
            headers=headers, limits=limits, verify=True,
        ) as client:
            await self._load_robots(client)
            await self._load_sitemaps(client)

            frontier: list[tuple[str, int, str | None]] = [(self.target.url, 0, None)]
            sitemap_seeds = [u for u in self.result.sitemap_urls
                             if same_site(u, self.target.url)
                             and looks_like_page(u) and not is_account_path(u)]
            self._seen.add(self.target.url)
            sem = asyncio.Semaphore(self.cfg.concurrency)

            async def bounded(url: str, depth: int, src: str | None) -> RawPage:
                async with sem:
                    if self.cfg.delay_between_requests_s:
                        await asyncio.sleep(self.cfg.delay_between_requests_s)
                    return await self._fetch(client, url, depth, src)

            while frontier and len(self.result.pages) < self.cfg.max_pages:
                if not self._budget_left():
                    self.result.budget_exhausted = True
                    break
                room = self.cfg.max_pages - len(self.result.pages)
                batch = frontier[:room]
                frontier = frontier[room:]
                pages = await asyncio.gather(
                    *(bounded(u, d, s) for u, d, s in batch)
                )
                next_frontier: list[tuple[str, int, str | None]] = []
                for page in pages:
                    page.from_sitemap = page.url in set(self.result.sitemap_urls)
                    self.result.pages.append(page)
                    if page.final_url != page.url:
                        self._seen.add(page.final_url)
                    if not page.html or page.depth >= self.cfg.max_depth:
                        continue
                    for link in self.extract_links(page.html, page.final_url):
                        if link in self._seen or not looks_like_page(link):
                            continue
                        if is_account_path(link):
                            continue
                        if self.cfg.same_site_only and not same_site(link, self.target.url):
                            continue
                        self._seen.add(link)
                        next_frontier.append((link, page.depth + 1, page.final_url))
                frontier.extend(next_frontier)
                # Top up from the sitemap when link discovery runs dry, so that
                # sitemap-only pages still get audited.
                if not frontier and sitemap_seeds:
                    for u in sitemap_seeds:
                        d = path_depth(u)
                        if u not in self._seen and d <= self.cfg.max_depth:
                            self._seen.add(u)
                            frontier.append((u, d, "sitemap"))
                        if len(frontier) >= self.cfg.max_pages:
                            break
                    sitemap_seeds = []

        home = next((p for p in self.result.pages if p.url == self.target.url), None)
        self.result.home_status = home.status if home else None
        self.result.duration_s = round(time.perf_counter() - self._started, 2)
        return self.result


def crawl_site(target: Target, config: AuditConfig) -> CrawlResult:
    """Synchronous wrapper around :class:`SiteCrawler`."""
    return asyncio.run(SiteCrawler(target, config).crawl())
