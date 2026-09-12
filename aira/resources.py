"""Page versus non-page resource classification.

Crawling a large site turns up URLs that are not navigable pages: component and
fragment endpoints, JSON APIs, search and utility routes, tracking pixels. They
answer with HTTP 200 and sometimes with HTML, so a naive crawler treats them as
pages - and then reports them for having no H1, no navigation, no call to action
and no sitemap entry. Those are five findings about one artefact that was never
a page.

Classification uses generic, cross-CMS signals only. No site-specific patterns
are encoded: the URL vocabulary below is the conventional wording used across
many platforms, and it is never the sole basis for a decision - document shape
and content type carry more weight than any path token.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Resource kinds
PAGE = "page"
COMPONENT_FRAGMENT = "component_fragment"
API_RESOURCE = "api_resource"
ASSET = "asset"
UTILITY_ENDPOINT = "utility_endpoint"
UNKNOWN_NON_PAGE = "other_non_page"

NON_PAGE_KINDS = frozenset(
    {COMPONENT_FRAGMENT, API_RESOURCE, ASSET, UTILITY_ENDPOINT, UNKNOWN_NON_PAGE})

# Conventional path vocabulary for implementation endpoints. Widely used across
# content platforms; treated as a hint, never as proof on its own.
FRAGMENT_TOKENS = frozenset({
    "fragment", "fragments", "content-fragment", "content-fragments",
    "experience-fragment", "experience-fragments", "component", "components",
    "partial", "partials", "include", "includes", "snippet", "snippets",
    "embed", "embeds", "widget", "widgets", "module", "modules",
    "block", "blocks", "chunk", "chunks", "ajax", "xhr", "async",
    "jcr:content", "_jcr_content", "_fragment", "_partial", "_next",
    "_nuxt", "__data", "hybrid-action", "render",
})
API_TOKENS = frozenset({
    "api", "apis", "graphql", "gql", "rest", "jsonapi", "wp-json", "oembed",
    "rpc", "v1", "v2", "v3", "feed", "rss", "atom", "data",
})
UTILITY_TOKENS = frozenset({
    "search", "suche", "recherche", "buscar", "filter", "sort", "print",
    "amp", "preview", "ping", "health", "healthz", "status", "beacon",
    "pixel", "track", "tracking", "analytics", "csrf", "captcha",
})

HTML_CONTENT_TYPES = ("text/html", "application/xhtml")
STRUCTURED_CONTENT_TYPES = ("application/json", "application/ld+json", "text/json",
                            "application/xml", "text/xml", "application/rss",
                            "application/atom")


@dataclass(frozen=True, slots=True)
class ResourceVerdict:
    kind: str
    is_page: bool
    confidence: float
    reasons: tuple[str, ...]

    @property
    def is_non_page(self) -> bool:
        return not self.is_page


def _segments(url: str) -> list[str]:
    return [seg.lower() for seg in urlsplit(url).path.split("/") if seg]


def _tokens(url: str) -> set[str]:
    segs = _segments(url)
    words = {w for seg in segs for w in re.split(r"[-_.]+", seg) if w}
    return set(segs) | words


def classify_resource(
    *,
    url: str,
    content_type: str,
    status: int | None,
    fetched: bool,
    has_html_element: bool,
    has_head: bool,
    has_title: bool,
    word_count: int,
    outgoing_internal_links: int,
    incoming_internal_links: int,
    sibling_pattern_count: int = 0,
) -> ResourceVerdict:
    """Decide whether a fetched URL behaves like a standalone navigable page.

    ``sibling_pattern_count`` is how many other crawled URLs share this URL's
    leading path shape; a repeated implementation path is a stronger signal than
    a single odd URL.
    """
    reasons: list[str] = []
    ctype = (content_type or "").lower()
    tokens = _tokens(url)

    # 1. Content type that is not HTML at all.
    if any(t in ctype for t in STRUCTURED_CONTENT_TYPES):
        return ResourceVerdict(API_RESOURCE, False, 0.97,
                               (f"content-type is {ctype.split(';')[0]}",))
    if ctype and not any(t in ctype for t in HTML_CONTENT_TYPES):
        return ResourceVerdict(ASSET, False, 0.95,
                               (f"content-type is {ctype.split(';')[0]}",))

    # 2. Nothing was fetched: no basis to call it a page.
    if not fetched or not status or not (200 <= status < 300):
        return ResourceVerdict(UNKNOWN_NON_PAGE, False, 0.9,
                               ("no successful response body was retrieved",))

    # 3. Document shape. Naked markup with no <html>/<head>/<title> is a
    #    fragment, whatever its URL looks like. This is the primary signal.
    document_shape = sum((has_html_element, has_head, has_title))
    if document_shape == 0:
        reasons.append("response is markup without <html>, <head> or <title>, "
                       "so it is not a standalone document")
        return ResourceVerdict(COMPONENT_FRAGMENT, False, 0.94, tuple(reasons))

    # 4. URL vocabulary. Only decisive when the document is *also* weak, so a
    #    real page that happens to live under /modules/ is not misclassified.
    weak_document = document_shape < 3 or word_count < 25
    if tokens & API_TOKENS and weak_document:
        return ResourceVerdict(
            API_RESOURCE, False, 0.8,
            ("URL uses API path vocabulary and the response is not a full document",))
    if tokens & FRAGMENT_TOKENS:
        if weak_document:
            return ResourceVerdict(
                COMPONENT_FRAGMENT, False, 0.85,
                ("URL uses component or fragment path vocabulary and the response "
                 "lacks a complete document structure",))
        if sibling_pattern_count >= 2 and word_count < 120:
            return ResourceVerdict(
                COMPONENT_FRAGMENT, False, 0.7,
                (f"URL uses component or fragment path vocabulary and shares its "
                 f"path shape with {sibling_pattern_count} other crawled URLs",))
    if tokens & UTILITY_TOKENS and weak_document:
        return ResourceVerdict(
            UTILITY_ENDPOINT, False, 0.75,
            ("URL is a search or utility endpoint and the response is not a full "
             "document",))

    # 5. A complete document with no title and essentially no text is not a page
    #    a visitor could ever land on meaningfully.
    if not has_title and word_count < 25 and outgoing_internal_links == 0:
        return ResourceVerdict(
            UNKNOWN_NON_PAGE, False, 0.72,
            ("document has no title, almost no text and no internal links",))

    return ResourceVerdict(PAGE, True, 0.9, ("responds as a complete HTML document",))


def path_shape(url: str, depth: int = 2) -> str:
    """Leading path shape, used to spot repeated implementation URL patterns."""
    segs = _segments(url)
    return "/".join(segs[:depth])
