"""The Evidence Engine.

Turns raw crawler output into a compact, measurable, JSON-serializable model.
Audit modules read *only* this model - never raw HTML - so that every finding is
traceable to a number or a string that was actually observed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from .config import AuditConfig
from .crawler import CrawlResult, RawPage
from .facts import (
    FactObservation, brand_from_title, extract_from_jsonld, extract_from_text,
    extract_socials, normalize_org_name,
)
from .importance import classify_role, score_importance
from .parsing import ParsedPage, flatten_jsonld, node_types, parse_page, raw_text_metrics
from .render import RenderedPage, render_pages, renderer_available
from .urls import path_depth

log = logging.getLogger("aira.evidence")

DATE_META_KEYS = ("article:published_time", "article:modified_time",
                  "datepublished", "datemodified", "og:updated_time")
DATE_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+(\d{4})|"
    r"\b(19[89]\d|20[0-4]\d)\b", re.I)


@dataclass(slots=True)
class RenderEvidence:
    attempted: bool = False
    ok: bool = False
    raw_words: int = 0
    rendered_words: int = 0
    raw_chars: int = 0
    rendered_chars: int = 0
    added_word_ratio: float = 0.0
    js_dependent: bool = False
    rendered_only_excerpt: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PageEvidence:
    url: str
    role: str
    importance: float
    importance_reasons: list[str] = field(default_factory=list)

    # access
    status: int | None = None
    ok: bool = False
    robots_allowed: bool = True
    redirect_count: int = 0
    final_url: str = ""
    error: str | None = None
    depth: int = 0
    in_sitemap: bool = False
    in_primary_nav: bool = False
    incoming_internal_links: int = 0
    outgoing_internal_links: int = 0
    outgoing_external_links: int = 0

    # content
    title: str = ""
    title_length: int = 0
    meta_description: str = ""
    meta_robots: str = ""
    canonical: str | None = None
    lang: str = ""
    h1: list[str] = field(default_factory=list)
    h2_count: int = 0
    headings_total: int = 0
    word_count: int = 0
    text_length: int = 0
    images_total: int = 0
    images_without_alt: int = 0
    has_main_landmark: bool = False
    has_nav_landmark: bool = False
    cta_count: int = 0
    cta_examples: list[str] = field(default_factory=list)
    text_sample: str = ""

    # machine readability
    jsonld_types: list[str] = field(default_factory=list)
    jsonld_invalid: list[str] = field(default_factory=list)
    jsonld_defects: list[str] = field(default_factory=list)
    jsonld_primary_name: str = ""
    x_robots_tag: str = ""
    microdata_types: list[str] = field(default_factory=list)
    og_keys: list[str] = field(default_factory=list)

    # rendering
    rendering: RenderEvidence = field(default_factory=RenderEvidence)

    # freshness
    dates_found: list[str] = field(default_factory=list)
    latest_date: str | None = None

    facts: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rendering"] = self.rendering.to_dict()
        return d


@dataclass(slots=True)
class SiteEvidence:
    site: str
    target_url: str
    audited_at: str
    config: dict[str, Any]

    pages: list[PageEvidence] = field(default_factory=list)
    robots_present: bool = False
    robots_status: int | None = None
    robots_blocks_site: bool = False
    robots_blocked_paths: list[str] = field(default_factory=list)
    sitemap_present: bool = False
    sitemap_locations: list[str] = field(default_factory=list)
    sitemap_url_count: int = 0
    sitemap_coverage: float | None = None
    sitemap_broken_urls: list[str] = field(default_factory=list)
    ai_agent_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    primary_lang: str = ""
    home_status: int | None = None
    home_reachable: bool = False

    renderer_available: bool = False
    rendered_page_count: int = 0

    crawl_duration_s: float = 0.0
    crawl_budget_exhausted: bool = False
    notes: list[str] = field(default_factory=list)

    facts_by_kind: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    # -- convenience accessors used by audit modules ---------------------
    @property
    def html_pages(self) -> list[PageEvidence]:
        return [p for p in self.pages if p.ok and p.word_count > 0]

    @property
    def important_pages(self) -> list[PageEvidence]:
        return [p for p in self.pages if p.importance >= 0.5]

    def pages_with_role(self, role: str) -> list[PageEvidence]:
        return [p for p in self.pages if p.role == role]

    @property
    def home(self) -> PageEvidence | None:
        return next((p for p in self.pages if p.role == "home"), None)

    def counts(self) -> dict[str, int]:
        return {
            "crawled": len(self.pages),
            "html_ok": len(self.html_pages),
            "important": len(self.important_pages),
            "rendered": self.rendered_page_count,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "target_url": self.target_url,
            "audited_at": self.audited_at,
            "config": self.config,
            "site_level": {
                "robots_present": self.robots_present,
                "robots_status": self.robots_status,
                "robots_blocks_site": self.robots_blocks_site,
                "robots_blocked_paths": self.robots_blocked_paths,
                "sitemap_present": self.sitemap_present,
                "sitemap_locations": self.sitemap_locations,
                "sitemap_url_count": self.sitemap_url_count,
                "sitemap_coverage": self.sitemap_coverage,
                "sitemap_broken_urls": self.sitemap_broken_urls,
                "ai_agent_rules": self.ai_agent_rules,
                "primary_lang": self.primary_lang,
                "home_status": self.home_status,
                "home_reachable": self.home_reachable,
                "renderer_available": self.renderer_available,
                "rendered_page_count": self.rendered_page_count,
                "crawl_duration_s": self.crawl_duration_s,
                "crawl_budget_exhausted": self.crawl_budget_exhausted,
                "counts": self.counts(),
                "notes": self.notes,
            },
            "facts_by_kind": self.facts_by_kind,
            "pages": [p.to_dict() for p in self.pages],
        }


    # -- round-tripping so that skills can exchange evidence as JSON files --
    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SiteEvidence":
        """Rebuild a SiteEvidence from :meth:`to_dict` output.

        This is what makes the skills genuinely separable: the crawl skill writes
        an evidence file, and each audit skill reads it back without re-crawling.
        """
        site_level = data.get("site_level", {})
        ev = SiteEvidence(
            site=data["site"], target_url=data["target_url"],
            audited_at=data.get("audited_at", ""), config=data.get("config", {}),
            robots_present=site_level.get("robots_present", False),
            robots_status=site_level.get("robots_status"),
            robots_blocks_site=site_level.get("robots_blocks_site", False),
            robots_blocked_paths=site_level.get("robots_blocked_paths", []),
            sitemap_present=site_level.get("sitemap_present", False),
            sitemap_locations=site_level.get("sitemap_locations", []),
            sitemap_url_count=site_level.get("sitemap_url_count", 0),
            sitemap_coverage=site_level.get("sitemap_coverage"),
            sitemap_broken_urls=site_level.get("sitemap_broken_urls", []),
            ai_agent_rules=site_level.get("ai_agent_rules", {}),
            primary_lang=site_level.get("primary_lang", ""),
            home_status=site_level.get("home_status"),
            home_reachable=site_level.get("home_reachable", False),
            renderer_available=site_level.get("renderer_available", False),
            rendered_page_count=site_level.get("rendered_page_count", 0),
            crawl_duration_s=site_level.get("crawl_duration_s", 0.0),
            crawl_budget_exhausted=site_level.get("crawl_budget_exhausted", False),
            notes=site_level.get("notes", []),
            facts_by_kind=data.get("facts_by_kind", {}),
        )
        for pd in data.get("pages", []):
            pd = dict(pd)
            rendering = RenderEvidence(**pd.pop("rendering", {}))
            page = PageEvidence(**pd)
            page.rendering = rendering
            ev.pages.append(page)
        return ev


# ---------------------------------------------------------------------------

def _extract_dates(parsed: ParsedPage, html: str) -> list[str]:
    out: list[str] = []
    for key in DATE_META_KEYS:
        v = parsed.og.get(key.replace("og:", "")) if key.startswith("og:") else None
        if v:
            out.append(v)
    for t in parsed.time_elements:
        if t:
            out.append(t)
    for node in flatten_jsonld(parsed.jsonld_blocks):
        for k in ("datePublished", "dateModified", "uploadDate"):
            v = node.get(k)
            if isinstance(v, str):
                out.append(v)
    for m in DATE_RE.finditer(parsed.text[:6000]):
        out.append(m.group(0))
    return list(dict.fromkeys(out))[:25]


def raw_text_of(html: str) -> str:
    """Visible text of the initial HTML response (no JavaScript executed)."""
    if not html:
        return ""
    from .parsing import soup_of, visible_text
    return visible_text(soup_of(html))


def _latest_year(dates: list[str]) -> str | None:
    years: list[str] = []
    for d in dates:
        m = re.search(r"(19[89]\d|20[0-4]\d)", d)
        if m:
            years.append(m.group(1))
    return max(years) if years else None


# Crawlers operated by AI assistants, answer engines and retrieval systems.
# Named separately in robots.txt by convention, so a site can allow general
# search while blocking these - which is exactly the mechanism that makes a
# brand invisible to AI applications.
AI_AGENTS: dict[str, str] = {
    "gptbot": "OpenAI (training and retrieval)",
    "oai-searchbot": "OpenAI search",
    "chatgpt-user": "ChatGPT user-initiated fetch",
    "claudebot": "Anthropic",
    "claude-user": "Claude user-initiated fetch",
    "claude-searchbot": "Claude search",
    "anthropic-ai": "Anthropic (legacy token)",
    "perplexitybot": "Perplexity",
    "perplexity-user": "Perplexity user-initiated fetch",
    "google-extended": "Google AI (Gemini / AI Overviews grounding)",
    "applebot-extended": "Apple Intelligence",
    "ccbot": "Common Crawl (feeds many downstream systems)",
    "bytespider": "ByteDance",
    "amazonbot": "Amazon",
    "meta-externalagent": "Meta AI",
    "cohere-ai": "Cohere",
    "youbot": "You.com",
    "diffbot": "Diffbot",
}


def _rules_block_root(rules: dict[str, list[str]]) -> bool:
    """True when a robots group disallows everything with no re-allow."""
    disallow = [d for d in rules.get("disallow", []) if d.strip()]
    allow = [a for a in rules.get("allow", []) if a.strip()]
    if not any(d.strip() == "/" for d in disallow):
        return False
    return not any(a.strip() == "/" for a in allow)


def evaluate_ai_agent_rules(groups: dict[str, dict[str, list[str]]]
                            ) -> dict[str, dict[str, Any]]:
    """Which known AI/retrieval agents does this robots.txt restrict, and how?

    Only agents *named explicitly* are reported. An agent that simply falls back
    to the ``*`` group is not singled out here - that case is already covered by
    the site-wide robots check.
    """
    out: dict[str, dict[str, Any]] = {}
    for agent, label in AI_AGENTS.items():
        rules = groups.get(agent)
        if rules is None:
            continue
        blocked = _rules_block_root(rules)
        disallowed = [d for d in rules.get("disallow", []) if d.strip()]
        if blocked or disallowed:
            out[agent] = {
                "operator": label,
                "blocked_entirely": blocked,
                "disallow": disallowed[:10],
                "allow": [a for a in rules.get("allow", []) if a.strip()][:10],
            }
    return out


# Minimum properties that make a schema.org node usable to a consumer. Missing
# them does not break JSON parsing, but it does make the block uninformative -
# which is the failure the audit actually cares about.
SCHEMA_EXPECTATIONS: dict[str, tuple[str, ...]] = {
    "organization": ("name", "url"),
    "corporation": ("name", "url"),
    "localbusiness": ("name",),
    "onlinestore": ("name", "url"),
    "website": ("name", "url"),
    "product": ("name",),
    "article": ("headline", "datePublished"),
    "newsarticle": ("headline", "datePublished"),
    "blogposting": ("headline", "datePublished"),
    "faqpage": ("mainEntity",),
    "breadcrumblist": ("itemListElement",),
}

PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|%%|<%|\bundefined\b|\bnull\b|"
                            r"\byour[ _-]?(?:company|brand|site)\b|lorem ipsum", re.I)


def validate_schema_nodes(nodes: list[dict[str, Any]]) -> tuple[list[str], str]:
    """Return (defects, primary entity name) for a page's JSON-LD nodes.

    Checks the *shape* of syntactically valid structured data: absent expected
    properties, empty values and unreplaced template placeholders. This is the
    difference between "the JSON parses" and "a consumer can use it".
    """
    defects: list[str] = []
    primary_name = ""
    for node in nodes:
        types = [t.lower() for t in node_types(node)]
        for t in types:
            expected = SCHEMA_EXPECTATIONS.get(t)
            if not expected:
                continue
            for prop in expected:
                value = node.get(prop)
                if value is None:
                    defects.append(f"{node_types(node)[0]} node has no '{prop}'")
                elif isinstance(value, str) and not value.strip():
                    defects.append(f"{node_types(node)[0]} '{prop}' is empty")
                elif isinstance(value, (list, dict)) and not value:
                    defects.append(f"{node_types(node)[0]} '{prop}' is empty")
        for key, value in node.items():
            if isinstance(value, str) and PLACEHOLDER_RE.search(value):
                defects.append(
                    f"{(node_types(node) or ['node'])[0]} '{key}' still contains a "
                    f"template placeholder: {value[:60]!r}")
        if not primary_name and any(
                t in ("product", "article", "newsarticle", "blogposting")
                for t in types):
            for key in ("name", "headline"):
                v = node.get(key)
                if isinstance(v, str) and v.strip():
                    primary_name = v.strip()
                    break
    return list(dict.fromkeys(defects))[:8], primary_name


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def rendered_only_text(raw_text: str, rendered_text: str, limit: int = 260) -> str:
    """The first sentences that exist after rendering but not in the initial HTML.

    Word counts prove a gap exists; this shows a judge (or a developer) exactly
    which text a non-rendering client never sees.
    """
    if not rendered_text:
        return ""
    raw_norm = " ".join(raw_text.lower().split())
    picked: list[str] = []
    total = 0
    for sentence in SENTENCE_SPLIT_RE.split(rendered_text):
        sentence = sentence.strip()
        if len(sentence) < 25:
            continue
        if " ".join(sentence.lower().split()) in raw_norm:
            continue
        picked.append(sentence)
        total += len(sentence)
        if total >= limit:
            break
    excerpt = " ".join(picked)[:limit]
    return excerpt + ("..." if len(" ".join(picked)) > limit else "")


def _robots_blocked_paths(robots_txt: str | None) -> tuple[bool, list[str]]:
    """Detect a global disallow and list disallowed path prefixes."""
    if not robots_txt:
        return False, []
    blocks_all = False
    paths: list[str] = []
    agent = None
    for line in robots_txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            agent = val
        elif key == "disallow" and agent in ("*", None):
            if val == "/":
                blocks_all = True
            elif val:
                paths.append(val)
    return blocks_all, paths[:50]


def build_evidence(crawl: CrawlResult, config: AuditConfig) -> SiteEvidence:
    """Convert a :class:`CrawlResult` into the structured evidence model."""
    site_url = crawl.target.url
    ev = SiteEvidence(
        site=crawl.target.registrable_host,
        target_url=site_url,
        audited_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        config={"max_pages": config.max_pages, "max_depth": config.max_depth,
                "render": config.render, "respect_robots": config.respect_robots},
    )
    ev.robots_present = crawl.robots_status == 200
    ev.robots_status = crawl.robots_status
    ev.robots_blocks_site, ev.robots_blocked_paths = _robots_blocked_paths(crawl.robots_txt)
    ev.ai_agent_rules = evaluate_ai_agent_rules(crawl.robots_groups)
    ev.sitemap_present = bool(crawl.sitemap_locations)
    ev.sitemap_locations = crawl.sitemap_locations
    ev.sitemap_url_count = len(crawl.sitemap_urls)
    ev.home_status = crawl.home_status
    ev.home_reachable = crawl.home_status is not None and 200 <= crawl.home_status < 300
    ev.crawl_duration_s = crawl.duration_s
    ev.crawl_budget_exhausted = crawl.budget_exhausted
    ev.notes = list(crawl.notes)

    sitemap_set = set(crawl.sitemap_urls)

    # --- parse every fetched page --------------------------------------
    parsed_by_url: dict[str, ParsedPage] = {}
    raw_by_url: dict[str, RawPage] = {}
    for page in crawl.pages:
        raw_by_url[page.final_url] = page
        if page.html:
            parsed_by_url[page.final_url] = parse_page(page.html, page.final_url, site_url)

    # --- link graph -----------------------------------------------------
    incoming: dict[str, int] = {u: 0 for u in raw_by_url}
    nav_targets: set[str] = set()
    for url, parsed in parsed_by_url.items():
        for link in parsed.internal_links:
            if link in incoming and link != url:
                incoming[link] += 1
        nav_targets.update(parsed.nav_links)

    # --- rendering ------------------------------------------------------
    avail, why = renderer_available()
    ev.renderer_available = avail and config.render
    if config.render and not avail:
        ev.notes.append(f"rendering unavailable: {why}")

    render_candidates = sorted(
        [u for u, p in parsed_by_url.items() if raw_by_url[u].ok],
        key=lambda u: (-_prelim_importance(u, parsed_by_url[u], site_url, nav_targets), u),
    )
    rendered: dict[str, RenderedPage] = {}
    if ev.renderer_available:
        rendered = render_pages(render_candidates, config)
        ev.rendered_page_count = sum(1 for r in rendered.values() if r.ok)
        if rendered and ev.rendered_page_count == 0:
            first_error = next((r.error for r in rendered.values() if r.error), None)
            ev.notes.append(
                "rendering was attempted but no page rendered successfully "
                f"({first_error or 'unknown error'}); raw-vs-rendered checks were "
                "not applicable for this run")
        elif not rendered and config.render:
            ev.notes.append("no page was eligible for rendering")

    # --- per-page evidence ---------------------------------------------
    all_facts: list[FactObservation] = []
    for url, raw in raw_by_url.items():
        parsed = parsed_by_url.get(url, ParsedPage(url=url))
        is_home = url == site_url or (raw.url == site_url)
        # Only the title and H1 are used for role hints: sub-headings pick up
        # unrelated vocabulary and misclassify pages.
        role = classify_role(url, parsed.title, parsed.h1, is_home)
        depth = raw.depth if raw.depth is not None else path_depth(url)
        in_nav = url in nav_targets
        imp, reasons = score_importance(
            role=role, depth=depth, in_nav=in_nav,
            incoming_links=incoming.get(url, 0),
            in_sitemap=url in sitemap_set, word_count=parsed.word_count,
        )
        pe = PageEvidence(
            url=url, role=role, importance=imp, importance_reasons=reasons,
            status=raw.status, ok=raw.ok, robots_allowed=raw.robots_allowed,
            redirect_count=len(raw.redirect_chain), final_url=raw.final_url,
            error=raw.error, depth=depth, in_sitemap=url in sitemap_set,
            in_primary_nav=in_nav,
            incoming_internal_links=incoming.get(url, 0),
            outgoing_internal_links=len(parsed.internal_links),
            outgoing_external_links=len(parsed.external_links),
            title=parsed.title, title_length=len(parsed.title),
            meta_description=parsed.meta_description,
            meta_robots=parsed.meta_robots, canonical=parsed.canonical,
            lang=parsed.lang, h1=parsed.h1, h2_count=len(parsed.h2),
            headings_total=parsed.headings_total,
            word_count=parsed.word_count, text_length=parsed.text_length,
            images_total=parsed.images_total,
            images_without_alt=parsed.images_without_alt,
            has_main_landmark=parsed.has_main_landmark,
            has_nav_landmark=parsed.has_nav_landmark,
            cta_count=len(parsed.cta_texts),
            cta_examples=parsed.cta_texts[:5],
            text_sample=parsed.text[:400],
            jsonld_types=parsed.jsonld_types,
            jsonld_invalid=parsed.jsonld_invalid,
            microdata_types=parsed.microdata_types,
            og_keys=sorted(parsed.og.keys()),
            x_robots_tag=(raw.x_robots_tag or "").lower(),
        )
        nodes = flatten_jsonld(parsed.jsonld_blocks)
        pe.jsonld_defects, pe.jsonld_primary_name = validate_schema_nodes(nodes)

        # rendering evidence
        r = rendered.get(url)
        if r is not None:
            pe.rendering.attempted = True
            if r.ok:
                rp = parse_page(r.html, url, site_url)
                raw_words, raw_chars = raw_text_metrics(raw.html)
                pe.rendering.ok = True
                pe.rendering.raw_words = raw_words
                pe.rendering.raw_chars = raw_chars
                pe.rendering.rendered_words = rp.word_count
                pe.rendering.rendered_chars = rp.text_length
                denom = max(rp.word_count, 1)
                added = max(rp.word_count - raw_words, 0)
                pe.rendering.added_word_ratio = round(added / denom, 3)
                if added >= 40:
                    pe.rendering.rendered_only_excerpt = rendered_only_text(
                        raw_text_of(raw.html), rp.text)
                pe.rendering.js_dependent = (
                    rp.word_count >= config.min_raw_words_for_ratio
                    and pe.rendering.added_word_ratio >= config.js_dependency_ratio
                    and added >= 40
                )
                # rendered structured data may exist where raw had none
                if rp.jsonld_types and not pe.jsonld_types:
                    pe.jsonld_types = rp.jsonld_types
                    pe.importance_reasons.append("structured data only after rendering")
            else:
                pe.rendering.error = r.error

        # freshness
        pe.dates_found = _extract_dates(parsed, raw.html)
        pe.latest_date = _latest_year(pe.dates_found)

        # facts
        page_facts: list[FactObservation] = []
        page_facts += extract_from_jsonld(nodes, url)
        if parsed.footer_text:
            page_facts += extract_from_text(parsed.footer_text, "footer", url)
        if role in ("contact", "about", "home"):
            page_facts += extract_from_text(parsed.text[:8000], "text", url)
        brand = brand_from_title(parsed.title)
        if brand:
            page_facts.append(FactObservation("organization_name", brand,
                                              normalize_org_name(brand),
                                              "title", url))
        if parsed.og.get("site_name"):
            v = parsed.og["site_name"]
            page_facts.append(FactObservation("organization_name", v,
                                              normalize_org_name(v), "og", url))
        if parsed.footer_text:
            fb = _footer_brand(parsed.footer_text)
            if fb:
                page_facts.append(FactObservation("organization_name", fb,
                                                  normalize_org_name(fb),
                                                  "footer", url))
        page_facts += extract_socials(parsed.external_links, url)
        pe.facts = [f.as_dict() for f in page_facts]
        all_facts += page_facts
        ev.pages.append(pe)

    # sitemap coverage of crawled pages
    if sitemap_set:
        crawled = {p.url for p in ev.pages if p.ok}
        if crawled:
            ev.sitemap_coverage = round(
                len(crawled & sitemap_set) / len(crawled), 3)
        ev.sitemap_broken_urls = [
            p.url for p in ev.pages
            if p.url in sitemap_set and p.status and
            (p.status in (404, 410) or p.status >= 500)
        ][:20]

    langs = [p.lang.split("-")[0].lower() for p in ev.pages if p.lang]
    if langs:
        ev.primary_lang = max(set(langs), key=langs.count)

    grouped: dict[str, list[dict[str, str]]] = {}
    for f in all_facts:
        grouped.setdefault(f.kind, []).append(f.as_dict())
    ev.facts_by_kind = grouped
    ev.pages.sort(key=lambda p: (-p.importance, p.depth, p.url))
    return ev


COPYRIGHT_RE = re.compile(
    r"(?:©|\(c\)|copyright)\s*(?:\d{4}\s*[-–]\s*\d{4}|\d{4})?\s*,?\s*"
    r"([A-Z0-9][A-Za-z0-9&.,'\- ]{1,60}?)(?:\s*[.|·]|\s+All\s+rights|$)", re.I)


def _footer_brand(footer_text: str) -> str | None:
    m = COPYRIGHT_RE.search(footer_text)
    if not m:
        return None
    cand = m.group(1).strip(" .,|")
    if not cand or len(cand.split()) > 6:
        return None
    if cand.lower() in ("all rights reserved", "reserved"):
        return None
    return cand


def _prelim_importance(url: str, parsed: ParsedPage, site_url: str,
                       nav_targets: set[str]) -> float:
    is_home = url.rstrip("/") == site_url.rstrip("/")
    role = classify_role(url, parsed.title, parsed.h1, is_home)
    score, _ = score_importance(
        role=role, depth=path_depth(url), in_nav=url in nav_targets,
        incoming_links=0, in_sitemap=False, word_count=parsed.word_count)
    return score
