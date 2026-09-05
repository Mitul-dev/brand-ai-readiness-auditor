"""Important-page detection.

Not every crawled page matters equally. We score pages with *generic* signals -
URL shape, title/heading vocabulary, navigation membership, incoming internal
links and depth - and never with hard-coded site names. Pages are classified into
roles (home, about, contact, pricing, products, services, faq, blog, legal,
other) so downstream checks can say "the pricing page" rather than "some page".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# URL-slug vocabulary per role. A small set of common non-English slugs is
# included for the roles that matter most: without it, every page on a
# non-English site falls back to "other", which both hides real findings and
# exempts pages from the checks that should protect them (a contact page that is
# short by design, for example, would be reported as thin content).
ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "about": ("about", "about-us", "company", "who-we-are", "our-story", "team",
              "ueber-uns", "uber-uns", "unternehmen", "a-propos", "qui-sommes-nous",
              "chi-siamo", "sobre", "sobre-nosotros", "nosotros", "empresa",
              "over-ons", "om-oss", "hakkimizda", "onas", "o-nas"),
    "contact": ("contact", "contact-us", "get-in-touch", "support", "help",
                "kontakt", "kontakta", "contacto", "contatti", "contato",
                "iletisim", "impressum"),
    "pricing": ("pricing", "price", "plans", "packages", "tariff", "cost",
                "preise", "preis", "tarifs", "prezzi", "precios", "precos",
                "planes", "prijzen"),
    "products": ("product", "products", "shop", "store", "catalog", "collections",
                 "item", "produkte", "produkt", "produits", "prodotti",
                 "productos", "produtos", "tienda", "negozio", "boutique",
                 "katalog", "webshop"),
    "services": ("service", "services", "solutions", "what-we-do", "offerings",
                 "dienstleistungen", "leistungen", "servizi", "servicios",
                 "servicos", "diensten", "losungen", "loesungen"),
    "faq": ("faq", "faqs", "questions", "knowledge-base", "haufige-fragen",
            "haeufige-fragen", "preguntas", "domande"),
    "blog": ("blog", "news", "articles", "insights", "press", "resources", "post",
             "nachrichten", "aktuelles", "noticias", "notizie", "actualites",
             "presse", "nieuws"),
    "legal": ("privacy", "terms", "legal", "cookie", "policy", "disclaimer",
              "gdpr", "datenschutz", "agb", "impressum", "mentions-legales",
              "privacidad", "privacy-policy", "aviso-legal"),
    "careers": ("careers", "jobs", "hiring", "vacancies", "karriere", "stellen",
                "emplois", "carriere", "empleo", "vagas"),
    # Account and transactional paths are never "important" for this audit: they
    # are meant to be private, and sites correctly disallow them in robots.txt.
    "account": ("login", "signin", "sign-in", "logout", "signout", "register",
                "signup", "sign-up", "account", "profile", "dashboard", "cart",
                "basket", "checkout", "password", "auth", "oauth", "admin",
                "wp-admin", "search", "anmelden", "registrieren", "warenkorb",
                "konto", "connexion", "panier", "carrito", "carrello",
                "iniciar-sesion", "suche", "recherche"),
}

TITLE_HINTS: dict[str, tuple[str, ...]] = {
    "about": ("about", "our story", "who we are", "company"),
    "contact": ("contact", "get in touch"),
    "pricing": ("pricing", "plans", "price"),
    "products": ("product", "shop", "store", "catalog"),
    "services": ("services", "solutions", "what we do"),
    "faq": ("faq", "frequently asked"),
    "blog": ("blog", "news", "article"),
    "legal": ("privacy", "terms", "cookie policy"),
    "careers": ("careers", "jobs"),
}

# Roles whose absence is never itself a finding - a site may legitimately have none.
OPTIONAL_ROLES = frozenset(ROLE_PATTERNS) | {"other"}

# Roles that carry public information the audit is actually about.
CONTENT_ROLES = frozenset({"home", "about", "contact", "pricing", "products",
                           "services", "faq", "blog", "careers"})


@dataclass(slots=True)
class PageRole:
    url: str
    role: str
    importance: float
    reasons: list[str] = field(default_factory=list)

    @property
    def is_important(self) -> bool:
        return self.importance >= 0.5


def _slug_tokens(url: str) -> set[str]:
    """Both the individual words of the path and its whole segments.

    Splitting on hyphens alone would make a multi-word pattern such as
    ``about-us`` or ``ueber-uns`` unmatchable, so full segments are kept too.
    """
    path = urlsplit(url).path.lower()
    segments = [seg for seg in path.split("/") if seg]
    words = [w for w in re.split(r"[/\-_.]+", path) if w]
    return set(segments) | set(words)


def classify_role(url: str, title: str, headings: list[str], is_home: bool) -> str:
    if is_home:
        return "home"
    tokens = _slug_tokens(url)
    for role, pats in ROLE_PATTERNS.items():
        if tokens & set(pats):
            return role
    haystack = " ".join([title or ""] + (headings or [])).lower()
    if haystack:
        for role, hints in TITLE_HINTS.items():
            if any(h in haystack for h in hints):
                return role
    return "other"


def score_importance(
    *,
    role: str,
    depth: int,
    in_nav: bool,
    incoming_links: int,
    in_sitemap: bool,
    word_count: int,
) -> tuple[float, list[str]]:
    """Return an importance score in [0, 1] plus human-readable reasons."""
    reasons: list[str] = []
    if role == "home":
        return 1.0, ["homepage"]

    score = 0.0
    role_weight = {
        "about": 0.34, "contact": 0.32, "pricing": 0.40, "products": 0.34,
        "services": 0.34, "faq": 0.26, "blog": 0.10, "careers": 0.06,
        "legal": 0.0, "account": 0.0, "other": 0.06,
    }.get(role, 0.06)
    if role_weight:
        score += role_weight
        if role not in ("other", "legal"):
            reasons.append(f"page role looks like '{role}'")

    if in_nav:
        score += 0.28
        reasons.append("linked from primary navigation")
    if depth <= 1:
        score += 0.16
        reasons.append(f"shallow (depth {depth})")
    elif depth == 2:
        score += 0.06
    if incoming_links >= 5:
        score += 0.16
        reasons.append(f"{incoming_links} incoming internal links")
    elif incoming_links >= 2:
        score += 0.08
    if in_sitemap:
        score += 0.05
    if word_count >= 400:
        score += 0.06
    if role == "legal":
        score = min(score, 0.35)  # legal pages are rarely the audit's concern
    if role == "account":
        return 0.0, ["account or transactional page: excluded from the audit"]
    return round(min(score, 1.0), 3), reasons
