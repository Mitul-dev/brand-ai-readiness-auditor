"""Multi-signal navigation detection.

The absence of a ``<nav>`` element is not the absence of navigation. Plenty of
working sites build their primary navigation from a header link cluster, a
footer link cluster, or simply the same set of internal links repeated in the
same place on every page. Judging navigation by the landmark alone produces a
confident, high-severity finding about a site whose navigation is perfectly
usable.

This module separates two questions that were previously conflated:

* **Is navigation present?** - answered from behaviour: are there repeated,
  consistent internal link clusters across the site?
* **Is navigation marked up semantically?** - answered from landmarks.

The first is a real user-facing and machine-readability problem. The second is
an implementation-quality observation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STRONG = "strong"
PROBABLE = "probable"
WEAK = "weak"
ABSENT = "absent"

# Share of pages a link must appear on before it counts as part of a repeated,
# site-wide navigation set.
REPEAT_SHARE = 0.6
MIN_PAGES_FOR_REPEAT = 3
MIN_REPEATED_LINKS = 3


@dataclass(slots=True)
class NavigationEvidence:
    strength: str = ABSENT
    pages_considered: int = 0
    pages_with_nav_landmark: int = 0
    pages_with_header_landmark: int = 0
    pages_with_footer_landmark: int = 0
    pages_with_header_links: int = 0
    pages_with_footer_links: int = 0
    repeated_link_count: int = 0
    repeated_links: list[str] = field(default_factory=list)
    repeated_link_share: float = 0.0
    home_internal_links: int = 0
    median_internal_links: int = 0
    semantic_landmark_share: float = 0.0
    signals: list[str] = field(default_factory=list)
    evidence_source: str = "raw_html"

    @property
    def has_semantic_landmark(self) -> bool:
        return self.semantic_landmark_share >= 0.5

    @property
    def is_functional(self) -> bool:
        return self.strength in (STRONG, PROBABLE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strength": self.strength,
            "pages_considered": self.pages_considered,
            "pages_with_nav_landmark": self.pages_with_nav_landmark,
            "pages_with_header_landmark": self.pages_with_header_landmark,
            "pages_with_footer_landmark": self.pages_with_footer_landmark,
            "pages_with_header_links": self.pages_with_header_links,
            "pages_with_footer_links": self.pages_with_footer_links,
            "repeated_link_count": self.repeated_link_count,
            "repeated_links": self.repeated_links[:12],
            "repeated_link_share": self.repeated_link_share,
            "home_internal_links": self.home_internal_links,
            "median_internal_links": self.median_internal_links,
            "semantic_landmark_share": self.semantic_landmark_share,
            "signals": self.signals,
            "evidence_source": self.evidence_source,
        }


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def analyse_navigation(observations: list[dict[str, Any]],
                       home: dict[str, Any] | None,
                       evidence_source: str = "raw_html") -> NavigationEvidence:
    """Classify site navigation from per-page link and landmark observations.

    Each observation is a mapping with ``url``, ``nav_links``, ``header_links``,
    ``footer_links``, ``internal_links``, ``has_nav_landmark``,
    ``has_header_landmark`` and ``has_footer_landmark``.
    """
    nav = NavigationEvidence(evidence_source=evidence_source)
    pages = [o for o in observations if o.get("url")]
    nav.pages_considered = len(pages)
    if not pages:
        return nav

    nav.pages_with_nav_landmark = sum(1 for o in pages if o.get("has_nav_landmark"))
    nav.pages_with_header_landmark = sum(
        1 for o in pages if o.get("has_header_landmark"))
    nav.pages_with_footer_landmark = sum(
        1 for o in pages if o.get("has_footer_landmark"))
    nav.pages_with_header_links = sum(
        1 for o in pages if len(o.get("header_links") or []) >= 2)
    nav.pages_with_footer_links = sum(
        1 for o in pages if len(o.get("footer_links") or []) >= 2)
    nav.semantic_landmark_share = round(nav.pages_with_nav_landmark / len(pages), 3)
    nav.home_internal_links = len((home or {}).get("internal_links") or [])
    nav.median_internal_links = _median(
        [len(o.get("internal_links") or []) for o in pages])

    # The behavioural signal: internal links that appear on most pages are, by
    # definition, site-wide navigation - whatever markup carries them.
    counts: dict[str, int] = {}
    for o in pages:
        for link in set(o.get("internal_links") or []):
            counts[link] = counts.get(link, 0) + 1
    threshold = max(MIN_PAGES_FOR_REPEAT, int(round(REPEAT_SHARE * len(pages))))
    repeated = sorted([u for u, c in counts.items() if c >= threshold])
    nav.repeated_links = repeated
    nav.repeated_link_count = len(repeated)
    nav.repeated_link_share = round(
        (max(counts.get(u, 0) for u in repeated) / len(pages)) if repeated else 0.0, 3)

    signals: list[str] = []
    if nav.semantic_landmark_share >= 0.5:
        signals.append(
            f"{nav.pages_with_nav_landmark}/{len(pages)} pages carry a nav landmark")
    if nav.repeated_link_count >= MIN_REPEATED_LINKS:
        signals.append(
            f"{nav.repeated_link_count} internal links repeat on at least "
            f"{threshold} of {len(pages)} pages")
    if nav.pages_with_header_links >= 0.5 * len(pages):
        signals.append(
            f"{nav.pages_with_header_links}/{len(pages)} pages have a header link cluster")
    if nav.pages_with_footer_links >= 0.5 * len(pages):
        signals.append(
            f"{nav.pages_with_footer_links}/{len(pages)} pages have a footer link cluster")
    nav.signals = signals

    landmark_ok = nav.semantic_landmark_share >= 0.5
    repeated_ok = nav.repeated_link_count >= MIN_REPEATED_LINKS
    cluster_ok = (nav.pages_with_header_links >= 0.5 * len(pages)
                  or nav.pages_with_footer_links >= 0.5 * len(pages))

    # A single crawled page cannot demonstrate repetition; fall back to whether
    # the page offers a usable set of internal links at all.
    if len(pages) < MIN_PAGES_FOR_REPEAT:
        if landmark_ok or nav.home_internal_links >= 4:
            nav.strength = PROBABLE
        elif nav.home_internal_links >= 1:
            nav.strength = WEAK
        else:
            nav.strength = ABSENT
        return nav

    if landmark_ok and (repeated_ok or cluster_ok):
        nav.strength = STRONG
    elif repeated_ok and cluster_ok:
        nav.strength = STRONG
    elif repeated_ok or cluster_ok or landmark_ok:
        nav.strength = PROBABLE
    elif nav.median_internal_links >= 2 or nav.home_internal_links >= 4:
        nav.strength = WEAK
    else:
        nav.strength = ABSENT
    return nav
