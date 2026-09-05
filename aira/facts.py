"""Generic extraction and normalization of business facts.

The point is *comparison*, not completeness: we extract the same kinds of value
from several places (JSON-LD, visible text, footer, meta) so that later checks
can look for contradictions. Nothing here assumes a site has any given fact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable
from urllib.parse import urlsplit

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?<![\d/])(?:\+\d{1,3}[\s\-]?)?(?:\(\d{2,4}\)[\s\-]?)?"
    r"\d(?:[\d\s\-]{7,13})\d(?![\d])"
)
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")

# Only genuine *legal form* markers are stripped. Descriptive words such as
# "technologies" or "solutions" are part of the brand and are kept; the
# Tech/Technologies style of abbreviation is handled by token-prefix matching in
# :func:`name_similarity` instead.
LEGAL_SUFFIXES = (
    "pvt ltd", "private limited", "pty ltd", "public limited company",
    "llp", "llc", "inc", "ltd", "limited", "gmbh", "bv", "nv", "sa", "srl",
    "spa", "plc", "corp", "corporation", "incorporated", "sarl", "ag", "oy",
    "ab", "kk", "co",
)

STOPWORDS = {"the", "a", "an", "and", "of", "for", "&"}

SOCIAL_HOSTS = (
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "youtube.com", "github.com", "crunchbase.com", "wikipedia.org",
    "wikidata.org", "tiktok.com", "pinterest.com", "threads.net", "mastodon",
)


@dataclass(slots=True)
class FactObservation:
    """One value of one fact, plus where it came from."""
    kind: str          # organization_name | email | phone | address | price | social
    value: str
    normalized: str
    source: str        # jsonld | footer | title | contact_block | og | text
    url: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value,
                "normalized": self.normalized, "source": self.source,
                "url": self.url}


def normalize_org_name(name: str) -> str:
    """Casefold, strip punctuation, drop legal suffixes and stopwords."""
    s = (name or "").lower()
    s = re.sub(r"[‘’“”]", "'", s)
    s = re.sub(r"[^a-z0-9&\s.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()
    while tokens and " ".join(tokens[-2:]) in LEGAL_SUFFIXES:
        tokens = tokens[:-2]
    while tokens and tokens[-1].strip(".") in {x.strip(".") for x in LEGAL_SUFFIXES}:
        tokens = tokens[:-1]
    tokens = [t for t in tokens if t not in STOPWORDS]
    return " ".join(tokens).strip(" .")


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def normalize_address(value: str) -> str:
    s = (value or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    repl = {"street": "st", "road": "rd", "avenue": "ave", "suite": "ste",
            "floor": "fl", "building": "bldg", "number": "no"}
    return " ".join(repl.get(t, t) for t in s.split()).strip()


def name_similarity(a: str, b: str) -> float:
    """Similarity of two normalized names; abbreviation-aware."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()

    def token_match(x: str, y: str) -> bool:
        # "tech" vs "technologies": one token is a >=3-char prefix of the other
        if x == y:
            return True
        short, long_ = (x, y) if len(x) <= len(y) else (y, x)
        return len(short) >= 3 and long_.startswith(short)

    def subset(small: list[str], big: list[str]) -> bool:
        return all(any(token_match(s, b) for b in big) for s in small)

    # one is a subset of the other -> trading name vs legal name, or abbreviation
    if subset(ta, tb) or subset(tb, ta):
        return 0.95
    base = 0.8 if (ta and tb and token_match(ta[0], tb[0])) else 0.0
    initials_a = "".join(t[0] for t in ta)
    initials_b = "".join(t[0] for t in tb)
    if initials_a == b.replace(" ", "") or initials_b == a.replace(" ", ""):
        return 0.93
    return max(base, SequenceMatcher(None, a, b).ratio())


def _jsonld_strings(node: Any, key: str) -> list[str]:
    out: list[str] = []
    v = node.get(key)
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, list):
        out.extend([x for x in v if isinstance(x, str)])
    return out


def _address_to_text(addr: Any) -> str | None:
    if isinstance(addr, str):
        return addr
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in (
            "streetAddress", "addressLocality", "addressRegion",
            "postalCode", "addressCountry")]
        parts = [p for p in parts if isinstance(p, str) and p.strip()]
        if parts:
            return ", ".join(parts)
    if isinstance(addr, list) and addr:
        return _address_to_text(addr[0])
    return None


def extract_from_jsonld(nodes: list[dict[str, Any]], url: str) -> list[FactObservation]:
    obs: list[FactObservation] = []
    for node in nodes:
        types = node.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        types_l = [str(t).lower() for t in types]
        org_like = any(t in ("organization", "corporation", "localbusiness",
                             "onlinestore", "store", "ngo", "educationalorganization")
                       or t.endswith("business") for t in types_l)
        if org_like or "website" in types_l:
            for n in _jsonld_strings(node, "name"):
                obs.append(FactObservation("organization_name", n,
                                           normalize_org_name(n), "jsonld", url))
            for n in _jsonld_strings(node, "legalName"):
                obs.append(FactObservation("organization_name", n,
                                           normalize_org_name(n), "jsonld", url))
        if org_like:
            for e in _jsonld_strings(node, "email"):
                obs.append(FactObservation("email", e, normalize_email(e),
                                           "jsonld", url))
            for t in _jsonld_strings(node, "telephone"):
                obs.append(FactObservation("phone", t, normalize_phone(t),
                                           "jsonld", url))
            addr = _address_to_text(node.get("address"))
            if addr:
                obs.append(FactObservation("address", addr,
                                           normalize_address(addr), "jsonld", url))
            for s in _jsonld_strings(node, "sameAs"):
                obs.append(FactObservation("social", s, s.lower().rstrip("/"),
                                           "jsonld", url))
        if "product" in types_l:
            offers = node.get("offers")
            offers = offers if isinstance(offers, list) else ([offers] if offers else [])
            for off in offers:
                if isinstance(off, dict) and off.get("price") is not None:
                    val = f"{off.get('priceCurrency', '')} {off.get('price')}".strip()
                    obs.append(FactObservation("price", val,
                                               re.sub(r"[^0-9.]", "", str(off.get("price"))),
                                               "jsonld", url))
    return obs


def brand_from_title(title: str) -> str | None:
    """Sites usually put the brand after a separator in <title>."""
    if not title:
        return None
    parts = re.split(r"\s[|–—\-·:]\s", title)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < 2:
        return None
    cand = parts[-1]
    if len(cand) > 60 or len(cand.split()) > 6:
        return None
    return cand


def extract_from_text(text: str, source: str, url: str) -> list[FactObservation]:
    obs: list[FactObservation] = []
    for m in EMAIL_RE.findall(text or "")[:10]:
        if m.lower().endswith((".png", ".jpg", ".webp")):
            continue
        obs.append(FactObservation("email", m, normalize_email(m), source, url))
    for m in PHONE_RE.findall(text or "")[:10]:
        norm = normalize_phone(m)
        if len(norm) >= 10:
            obs.append(FactObservation("phone", m.strip(), norm, source, url))
    return obs


def extract_socials(links: Iterable[str], url: str) -> list[FactObservation]:
    out: list[FactObservation] = []
    seen: set[str] = set()
    for link in links:
        host = (urlsplit(link).hostname or "").lower()
        if any(h in host for h in SOCIAL_HOSTS):
            key = link.lower().rstrip("/")
            if key not in seen:
                seen.add(key)
                out.append(FactObservation("social", link, key, "text", url))
    return out


def group_by_kind(obs: list[FactObservation]) -> dict[str, list[FactObservation]]:
    out: dict[str, list[FactObservation]] = {}
    for o in obs:
        out.setdefault(o.kind, []).append(o)
    return out
