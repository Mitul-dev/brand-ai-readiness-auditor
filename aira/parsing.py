"""HTML -> structured observations. Pure functions, no network, no side effects."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .urls import normalize_url, same_site

NON_TEXT_TAGS = ("script", "style", "noscript", "template", "svg", "canvas")
WORD_RE = re.compile(r"[A-Za-z0-9'À-ɏ]+")


@dataclass(slots=True)
class ParsedPage:
    url: str
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    canonical: str | None = None
    lang: str = ""
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    headings_total: int = 0
    text: str = ""
    word_count: int = 0
    text_length: int = 0
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    nav_links: list[str] = field(default_factory=list)
    footer_text: str = ""
    jsonld_blocks: list[Any] = field(default_factory=list)
    jsonld_invalid: list[str] = field(default_factory=list)
    jsonld_types: list[str] = field(default_factory=list)
    microdata_types: list[str] = field(default_factory=list)
    og: dict[str, str] = field(default_factory=dict)
    images_total: int = 0
    images_without_alt: int = 0
    forms: int = 0
    has_main_landmark: bool = False
    has_nav_landmark: bool = False
    time_elements: list[str] = field(default_factory=list)
    cta_texts: list[str] = field(default_factory=list)


def soup_of(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def visible_text(soup: BeautifulSoup) -> str:
    clone = soup
    for tag in clone.find_all(NON_TEXT_TAGS):
        tag.decompose()
    body = clone.body or clone
    text = body.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def _collect_types(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend([x for x in t if isinstance(x, str)])
        for v in node.values():
            _collect_types(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_types(v, out)


def parse_page(html: str, url: str, site_url: str) -> ParsedPage:
    """Parse one HTML document into a :class:`ParsedPage`."""
    p = ParsedPage(url=url)
    if not html:
        return p
    soup = soup_of(html)

    if soup.title and soup.title.string:
        p.title = soup.title.string.strip()
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        p.lang = str(html_tag.get("lang")).strip()
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        content = (meta.get("content") or "").strip()
        if name == "description":
            p.meta_description = content
        elif name == "robots":
            p.meta_robots = content.lower()
        elif name.startswith("og:"):
            p.og[name[3:]] = content
    link_canon = soup.find("link", rel=lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])])
    if link_canon and link_canon.get("href"):
        p.canonical = normalize_url(link_canon["href"], url)

    p.h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    p.h2 = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
    p.headings_total = len(soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))
    p.has_main_landmark = bool(soup.find("main") or soup.find(attrs={"role": "main"}))
    p.has_nav_landmark = bool(soup.find("nav") or soup.find(attrs={"role": "navigation"}))
    p.forms = len(soup.find_all("form"))
    imgs = soup.find_all("img")
    p.images_total = len(imgs)
    p.images_without_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())
    p.time_elements = [
        (t.get("datetime") or t.get_text(" ", strip=True))
        for t in soup.find_all("time")
    ][:20]

    nav = soup.find("nav") or soup.find(attrs={"role": "navigation"})
    if nav:
        for a in nav.find_all("a", href=True):
            n = normalize_url(a["href"], url)
            if n and same_site(n, site_url):
                p.nav_links.append(n)
    footer = soup.find("footer") or soup.find(attrs={"role": "contentinfo"})
    if footer:
        p.footer_text = re.sub(r"\s+", " ", footer.get_text(" ", strip=True))[:2000]

    cta_words = ("buy", "get started", "sign up", "signup", "contact", "book",
                 "request", "demo", "subscribe", "learn more", "start", "try",
                 "order", "quote", "apply", "download", "shop", "call")
    for el in soup.find_all(["a", "button"]):
        t = el.get_text(" ", strip=True).lower()
        if t and len(t) <= 60 and any(w in t for w in cta_words):
            p.cta_texts.append(t)
    p.cta_texts = p.cta_texts[:30]

    for a in soup.find_all("a", href=True):
        n = normalize_url(a["href"], url)
        if not n:
            continue
        (p.internal_links if same_site(n, site_url) else p.external_links).append(n)
    p.internal_links = list(dict.fromkeys(p.internal_links))
    p.external_links = list(dict.fromkeys(p.external_links))

    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception as exc:
            p.jsonld_invalid.append(f"{type(exc).__name__}: {exc}")
            continue
        p.jsonld_blocks.append(data)
    types: list[str] = []
    _collect_types(p.jsonld_blocks, types)
    p.jsonld_types = sorted(set(types))
    p.microdata_types = sorted({
        str(el.get("itemtype")).rstrip("/").rsplit("/", 1)[-1]
        for el in soup.find_all(attrs={"itemtype": True})
    })

    # visible text last: it mutates the tree
    p.text = visible_text(soup)
    p.word_count = word_count(p.text)
    p.text_length = len(p.text)
    return p


def raw_text_metrics(html: str) -> tuple[int, int]:
    """(word_count, char_length) of the text present in the *initial* HTML."""
    if not html:
        return 0, 0
    text = visible_text(soup_of(html))
    return word_count(text), len(text)


def flatten_jsonld(blocks: list[Any]) -> list[dict[str, Any]]:
    """Flatten @graph containers into a list of typed nodes."""
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "@graph" in node and isinstance(node["@graph"], list):
                for child in node["@graph"]:
                    walk(child)
            if node.get("@type"):
                out.append(node)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(blocks)
    # de-duplicate by identity of serialized content
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for node in out:
        try:
            key = json.dumps(node, sort_keys=True, default=str)[:4000]
        except Exception:
            key = str(id(node))
        if key not in seen:
            seen.add(key)
            uniq.append(node)
    return uniq


def node_types(node: dict[str, Any]) -> list[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []
