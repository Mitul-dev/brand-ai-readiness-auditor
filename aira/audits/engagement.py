"""On-site engagement audit.

Scoped deliberately to the challenge question - can a visitor who lands here
tell where they are, what is offered, and what to do next? - rather than to
general visual UX. Every check is grounded in structure that we measured, not in
an aesthetic opinion.
"""
from __future__ import annotations

import re

from ..config import AuditConfig
from ..evidence import PageEvidence, SiteEvidence
from ..findings import Finding
from .base import make_finding

OFFER_WORDS = re.compile(
    r"\b(we\s+(?:are|build|make|help|offer|provide|design|deliver|sell)|"
    r"our\s+(?:products?|services?|platform|software|team|mission)|"
    r"platform\s+for|software\s+for|solution[s]?\s+for|"
    r"helps?\s+\w+\s+to|for\s+(?:teams|businesses|companies|developers))", re.I)


# Wording-based signals below are English-language heuristics. Applying them to a
# site published in another language would manufacture findings, so they are
# gated on the site's declared language and only the structural signals (missing
# heading, missing title) are used elsewhere.
ENGLISH_LANGS = frozenset({"", "en"})


def _wording_checks_apply(ev: SiteEvidence) -> bool:
    return (ev.primary_lang or "").split("-")[0].lower() in ENGLISH_LANGS


def _looks_generic(title: str) -> bool:
    t = (title or "").strip().lower()
    if not t:
        return True
    generic = {"home", "homepage", "welcome", "index", "untitled", "page",
               "home page", "main", "site", "welcome!", "document"}
    return t in generic or len(t) < 6


def audit(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    out += _orientation(ev, cfg)
    out += _clarity(ev, cfg)
    out += _navigation(ev, cfg)
    out += _next_step(ev, cfg)
    out += _context_retention(ev, cfg)
    return out


def _orientation(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    home = ev.home
    if home is None or not home.ok:
        return []
    wording = _wording_checks_apply(ev)
    problems: list[str] = []
    metrics: dict[str, object] = {
        "title": home.title, "h1_count": len(home.h1),
        "word_count": home.word_count,
        "meta_description_present": bool(home.meta_description),
        "primary_lang": ev.primary_lang or "undeclared",
        "language_dependent_checks_applied": wording,
    }
    if not home.title:
        problems.append("the page has no title element")
    elif wording and _looks_generic(home.title):
        problems.append(f"the page title is {home.title!r}, which does not name the "
                        "brand or what the site is for")
    if not home.h1:
        problems.append("there is no H1 heading stating what the site is")
    elif wording and all(len(h.split()) <= 2 for h in home.h1):
        problems.append(f"the only H1 is {home.h1[0]!r}, which does not describe an offering")
    text = (home.text_sample or "")
    if wording and not OFFER_WORDS.search(text) and not home.meta_description:
        problems.append("neither the opening body text nor a meta description states "
                        "what the organization offers")
    if len(problems) < 2:
        return []
    return [make_finding(
        check_id="home_purpose_unclear", category="engagement",
        journey_stage=None, dimension="engagement",
        title="The homepage does not clearly state what the site is or what it offers",
        url=home.url,
        observation="On the homepage, " + "; ".join(problems) + ".",
        details=f"First 200 characters of visible homepage text: {text[:200]!r}",
        metrics=metrics,
        impact=("A visitor arriving from an AI answer or a search result has to work "
                "out what the organization does before deciding to stay, which is the "
                "point at which most arrivals are lost."),
        benign_explanations=[
            "A well-known brand may deliberately keep the homepage sparse and carry "
            "the explanation in imagery; confirm against the rendered page.",
        ],
        action_summary="State the offering in the title, the H1 and the opening paragraph of the homepage.",
        steps=["Write a title of the form '<Brand> - <what it does for whom>'.",
               "Make the H1 a plain-language statement of the offering.",
               "Put a one-sentence summary of the offering in the first visible paragraph.",
               "Add a meta description repeating that summary."],
        reach=1.0, on_important_page=True, sample_size=1, affected=1,
        direct_dom_evidence=True,
    )]


def _clarity(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    wording = _wording_checks_apply(ev)
    unclear: list[PageEvidence] = []
    for p in ev.html_pages:
        if p.role == "home" or p.importance < 0.5:
            continue
        weak_title = (not p.title) if not wording else _looks_generic(p.title)
        no_h1 = not p.h1
        if weak_title and no_h1:
            unclear.append(p)
    if not unclear:
        return []
    return [make_finding(
        check_id="page_identity_unclear", category="engagement",
        journey_stage=None, dimension="engagement",
        title=f"{len(unclear)} likely-important page(s) do not identify themselves to a visitor who lands on them directly",
        url=unclear[0].url,
        observation="; ".join(
            f"{p.url} has title {p.title!r} and no H1" for p in unclear[:5]),
        details=("A visitor arriving from an external answer lands mid-site; the title "
                 "and heading are the only orientation cues available."),
        metrics={"pages": len(unclear),
                 "important_pages": len(ev.important_pages)},
        affected_urls=[p.url for p in unclear],
        impact=("Visitors who land on these pages from an external link cannot tell "
                "what the page is or how it relates to the rest of the site, so they "
                "are likely to leave rather than continue."),
        action_summary="Give each page a descriptive title and a single H1 naming its subject.",
        steps=["Write a unique <title> that names the page and the brand.",
               "Add one H1 that states the page's subject.",
               "Add a one-line intro paragraph placing the page in context."],
        reach=len(unclear) / max(len(ev.important_pages) or 1, 1),
        on_important_page=True,
        sample_size=len(ev.important_pages) or 1, affected=len(unclear),
    )]


def _navigation(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    pages = ev.html_pages
    if len(pages) < 4:
        return []
    with_nav = [p for p in pages if p.has_nav_landmark]
    nav_share = len(with_nav) / len(pages)
    home = ev.home
    home_nav_links = home.outgoing_internal_links if home else 0
    if nav_share >= 0.6 or (home and home_nav_links >= 5 and home.has_nav_landmark):
        return []
    return [make_finding(
        check_id="weak_navigation", category="engagement",
        journey_stage=None, dimension="engagement",
        title="Most crawled pages expose no navigation region",
        url=(home.url if home else ev.target_url),
        observation=(
            f"{len(with_nav)} of {len(pages)} crawled HTML pages contain a <nav> "
            f"element or role=\"navigation\"; the homepage exposes "
            f"{home_nav_links} internal links in total."),
        details=("Navigation was detected structurally (nav landmark plus internal "
                 "links inside it), so a visually styled menu that uses neither will "
                 "also be reported here."),
        metrics={"pages_with_nav_landmark": len(with_nav), "pages": len(pages),
                 "nav_share": round(nav_share, 2),
                 "home_internal_links": home_nav_links},
        impact=("Without a consistent navigation region, a visitor who lands on an "
                "interior page has no reliable way to move to the rest of the site, "
                "so the visit usually ends on the landing page."),
        action_summary="Provide a consistent primary navigation region on every page, marked up as a nav landmark.",
        steps=["Wrap the primary menu in a <nav> element present on every template.",
               "Include links to the main sections (offering, pricing, about, contact).",
               "Make sure the links exist in the server-rendered HTML, not only after client-side hydration."],
        reach=1.0 - nav_share, on_important_page=True,
        sample_size=len(pages), affected=len(pages) - len(with_nav),
    )]


def _next_step(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    candidates = [p for p in ev.html_pages
                  if p.importance >= 0.5 and p.role in
                  ("home", "products", "services", "pricing", "about")]
    if not candidates:
        return []
    wording = _wording_checks_apply(ev)
    # Without reliable call-to-action wording (non-English site) the structural
    # signal alone must be stronger before anything is reported.
    link_ceiling = 3 if wording else 1
    dead_ends = [p for p in candidates
                 if (p.cta_count == 0 or not wording)
                 and p.outgoing_internal_links <= link_ceiling]
    if not dead_ends:
        return []
    return [make_finding(
        check_id="no_next_step", category="engagement",
        journey_stage=None, dimension="engagement",
        title=f"{len(dead_ends)} likely-important page(s) offer no obvious next action",
        url=dead_ends[0].url,
        observation="; ".join(
            f"{p.url} (role: {p.role}) contains no call-to-action link or button and "
            f"only {p.outgoing_internal_links} internal link(s)"
            for p in dead_ends[:5]),
        details=("Calls to action were detected by matching common action wording on "
                 "links and buttons (contact, get started, book, request, buy, "
                 "subscribe and similar). That wording list is English; on a site in "
                 "another language only the internal-link count is used, with a "
                 "stricter threshold."),
        metrics={"dead_end_pages": len(dead_ends),
                 "candidate_pages": len(candidates),
                 "primary_lang": ev.primary_lang or "undeclared",
                 "cta_wording_detection_applied": wording},
        affected_urls=[p.url for p in dead_ends],
        impact=("A visitor who has understood the offering has nowhere to go next, so "
                "interest does not convert into contact, signup or a deeper visit."),
        action_summary="Add one clear, primary next action to each of these pages.",
        steps=["Decide the single most useful next step for each page (contact, demo, pricing, signup).",
               "Add a clearly worded link or button for that step, in text rather than an image.",
               "Add two or three contextual links to closely related pages."],
        reach=len(dead_ends) / len(candidates), on_important_page=True,
        sample_size=len(candidates), affected=len(dead_ends),
    )]


def _context_retention(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    """Interior pages a visitor can reach but cannot leave meaningfully."""
    pages = [p for p in ev.html_pages if p.role != "home"]
    if len(pages) < 3:
        return []
    stranded = [p for p in pages
                if p.outgoing_internal_links <= 1 and p.word_count >= 50]
    if len(stranded) < max(2, 0.3 * len(pages)):
        return []
    return [make_finding(
        check_id="context_loss_orphan", category="engagement",
        journey_stage=None, dimension="engagement",
        title=f"{len(stranded)} interior page(s) link back to almost nothing else on the site",
        url=stranded[0].url,
        observation="; ".join(
            f"{p.url} has {p.outgoing_internal_links} outgoing internal link(s) "
            f"for {p.word_count} words of content" for p in stranded[:5]),
        details=("Counted anchor elements pointing at the same site in the "
                 "server-rendered HTML."),
        metrics={"stranded_pages": len(stranded), "interior_pages": len(pages)},
        affected_urls=[p.url for p in stranded],
        impact=("A visitor who arrives on one of these pages loses the thread of the "
                "site: there is no route onward, so the session ends there regardless "
                "of how good the content is."),
        action_summary="Add persistent navigation and contextual links to these pages.",
        steps=["Include the site's standard header and footer navigation on these templates.",
               "Add links to the parent section and to two or three related pages.",
               "Add breadcrumbs so the page's place in the site is explicit."],
        reach=len(stranded) / len(pages), on_important_page=True,
        sample_size=len(pages), affected=len(stranded),
    )]
