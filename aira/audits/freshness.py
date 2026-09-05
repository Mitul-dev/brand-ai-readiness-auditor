"""Freshness, fact consistency and corroboration (the TRUST / REPRESENT stages).

Two ideas drive this module:

1. *Consistency over correctness.* We never claim a fact is wrong - we only
   report that the same fact is stated differently in different places, which is
   something we can actually observe.
2. *Normalize before comparing.* Legal suffixes, punctuation, casing and common
   abbreviations are stripped first, so "ABC Technologies Pvt Ltd", "ABC
   Technologies" and "ABC Tech" do not produce a finding, while "ABC
   Technologies" versus "Zenith Motors" does.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from ..config import AuditConfig
from ..evidence import SiteEvidence
from ..facts import name_similarity, normalize_org_name
from ..findings import Finding
from .base import make_finding


def audit(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    out += _entity_consistency(ev, cfg)
    out += _contact_consistency(ev, cfg)
    out += _structured_vs_visible(ev, cfg)
    out += _freshness(ev, cfg)
    return out


def _structured_vs_visible(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    """The name in structured data versus the name shown on the page.

    Structured data is what a machine reads; the H1 is what a person reads. When
    they disagree, an automated system may attribute the wrong title, product or
    article to the page - and nothing on the page reveals the mismatch.
    """
    mismatched: list[tuple[str, str, str]] = []
    for p in ev.html_pages:
        if not p.jsonld_primary_name or not p.h1:
            continue
        visible = p.h1[0].strip()
        if not visible:
            continue
        a = normalize_org_name(p.jsonld_primary_name)
        b = normalize_org_name(visible)
        if not a or not b:
            continue
        if name_similarity(a, b) < cfg.name_similarity_threshold:
            mismatched.append((p.url, p.jsonld_primary_name, visible))
    if not mismatched:
        return []
    return [make_finding(
        check_id="structured_visible_mismatch", category="discoverability",
        journey_stage="extract", dimension="fact_consistency",
        title=(f"On {len(mismatched)} page(s) the name in structured data differs "
               "from the heading shown to visitors"),
        url=mismatched[0][0],
        observation="; ".join(
            f"{url}: structured data says {machine!r} while the H1 reads {human!r}"
            for url, machine, human in mismatched[:5]),
        details=("Compared after the same normalization used for organization names, "
                 "so abbreviations and legal suffixes do not count as a mismatch."),
        metrics={"mismatched_pages": len(mismatched),
                 "pages_with_both_signals": sum(
                     1 for p in ev.html_pages if p.jsonld_primary_name and p.h1),
                 "examples": [{"url": u, "structured": m, "visible": h}
                              for u, m, h in mismatched[:5]]},
        affected_urls=[u for u, _, _ in mismatched],
        impact=("The machine-readable and human-readable versions of the same page "
                "disagree, so an automated system may extract and repeat a name the "
                "page never shows to a visitor."),
        action_summary="Generate the structured-data name from the same source as the visible heading.",
        steps=["Identify which of the two values is authoritative for each listed page.",
               "Emit the structured-data name from the same field that renders the H1, rather than from a separate template.",
               "Add a check that fails the build when the two diverge."],
        benign_explanations=[
            "A product page may legitimately show a short display name in the H1 "
            "and a full catalogue name in structured data; confirm per page.",
        ],
        reach=len(mismatched) / max(len(ev.html_pages), 1), on_important_page=True,
        sample_size=len(ev.html_pages) or 1, affected=len(mismatched),
        corroborating_sources=2,
    )]


def _cluster_names(values: list[dict[str, str]], threshold: float
                   ) -> list[list[dict[str, str]]]:
    """Greedy clustering of name observations by normalized similarity."""
    clusters: list[list[dict[str, str]]] = []
    for obs in values:
        norm = obs.get("normalized", "")
        if not norm:
            continue
        placed = False
        for cluster in clusters:
            if name_similarity(norm, cluster[0]["normalized"]) >= threshold:
                cluster.append(obs)
                placed = True
                break
        if not placed:
            clusters.append([obs])
    clusters.sort(key=len, reverse=True)
    return clusters


def _entity_consistency(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    names = [o for o in ev.facts_by_kind.get("organization_name", [])
             if o.get("normalized")]
    if len(names) < 2:
        return []
    clusters = _cluster_names(names, cfg.name_similarity_threshold)
    if len(clusters) < 2:
        return []

    # Ignore singleton clusters that come from a single weak source (a page
    # title suffix on one page is not enough to claim an identity conflict).
    strong_sources = {"jsonld", "og", "footer"}
    significant = [
        c for c in clusters
        if len(c) >= 2 or any(o["source"] in strong_sources for o in c)
    ]
    if len(significant) < 2:
        return []

    def describe(cluster: list[dict[str, str]]) -> str:
        by_source: dict[str, str] = {}
        for o in cluster:
            by_source.setdefault(o["source"], o["value"])
        return " / ".join(f"{v!r} ({k})" for k, v in list(by_source.items())[:4])

    lines = [describe(c) for c in significant[:4]]
    all_urls = sorted({o["url"] for c in significant for o in c})
    jsonld_involved = any(o["source"] == "jsonld"
                          for c in significant for o in c)
    return [make_finding(
        check_id="entity_name_conflict", category="discoverability",
        journey_stage="represent", dimension="entity_clarity",
        title="The site presents more than one organization name that do not normalize to the same entity",
        url=ev.target_url,
        observation="Distinct name variants observed: " + "; ".join(lines),
        details=(
            "Names were compared after stripping legal suffixes, punctuation and "
            "casing, and after allowing common abbreviations, so variants such as "
            "'X Ltd' vs 'X' are not counted as a conflict. "
            f"Similarity threshold: {cfg.name_similarity_threshold}."
        ),
        metrics={
            "distinct_name_clusters": len(significant),
            "observations": len(names),
            "variants": [c[0]["value"] for c in significant[:6]],
            "sources": sorted({o["source"] for c in significant for o in c}),
        },
        affected_urls=all_urls[:10],
        impact=("When a site refers to itself by names that do not resolve to one "
                "entity, automated systems can split the brand into several entities "
                "or attach the wrong one, which weakens how the brand is represented."),
        action_summary="Choose one canonical organization name and use it consistently, declaring alternatives explicitly.",
        steps=[
            "Pick the canonical public name of the organization.",
            "Use it in the Organization JSON-LD 'name' field and in og:site_name.",
            "Put the registered legal name in 'legalName' and any trading variants in 'alternateName' rather than mixing them in prose.",
            "Align the footer, page titles and about page with the canonical name.",
        ],
        benign_explanations=[
            "A site that genuinely operates several brands, or that has recently "
            "rebranded, will show more than one name legitimately; the fix is then "
            "to model them explicitly rather than to pick one.",
            "A footer naming a parent or holding company alongside the trading name "
            "is normal corporate practice.",
        ],
        reach=min(1.0, len(all_urls) / max(len(ev.html_pages) or 1, 1)),
        on_important_page=True,
        sample_size=len(ev.html_pages) or 1, affected=len(all_urls),
        corroborating_sources=len({o["source"] for c in significant for o in c}),
        conflicting_signals=not jsonld_involved,
    )]


def _contact_consistency(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    for kind, label in (("phone", "phone number"), ("email", "email address")):
        obs = ev.facts_by_kind.get(kind, [])
        distinct: dict[str, list[dict[str, str]]] = defaultdict(list)
        for o in obs:
            if o.get("normalized"):
                distinct[o["normalized"]].append(o)
        if len(distinct) < 2:
            continue
        # A site may legitimately list several contacts (sales / support / regional).
        # We only report when a *single* declared identity source disagrees with the
        # visible pages, i.e. JSON-LD says one thing and the page says another.
        jsonld_vals = {o["normalized"] for o in obs if o["source"] == "jsonld"}
        page_vals = {o["normalized"] for o in obs if o["source"] != "jsonld"}
        if not jsonld_vals or not page_vals or jsonld_vals & page_vals:
            continue
        # Tolerate formatting differences that survive normalization (a value
        # captured with an extra leading digit, an extension, and so on).
        if any(j in pv or pv in j for j in jsonld_vals for pv in page_vals):
            continue
        example_jsonld = next(o for o in obs if o["source"] == "jsonld")
        example_page = next(o for o in obs if o["source"] != "jsonld")
        out.append(make_finding(
            check_id="contact_fact_conflict", category="discoverability",
            journey_stage="trust", dimension="fact_consistency",
            title=f"The {label} in structured data does not match the {label} shown on the site",
            url=example_jsonld["url"],
            observation=(
                f"Structured data on {example_jsonld['url']} declares "
                f"{example_jsonld['value']!r}, while {example_page['url']} shows "
                f"{example_page['value']!r} in its {example_page['source']}."),
            details=(f"Distinct normalized values found: "
                     f"{', '.join(sorted(distinct)[:6])}"),
            metrics={"distinct_values": len(distinct),
                     "jsonld_values": sorted(jsonld_vals),
                     "page_values": sorted(page_vals)[:6]},
            affected_urls=sorted({o["url"] for o in obs})[:10],
            impact=("Machine-readable and visible values that disagree give automated "
                    "systems no way to decide which contact detail is authoritative, "
                    f"so the wrong {label} may be repeated."),
            action_summary=f"Make the {label} in structured data identical to the one published on the contact page.",
            steps=[f"Decide which {label} is authoritative.",
                   "Update the Organization structured data to that value.",
                   "Update the visible contact block and footer to match.",
                   "Where several contacts genuinely exist, model them as separate contactPoint entries with a contactType."],
            benign_explanations=[
                f"A site may publish several {label}s for different departments or "
                "regions; that is only a defect if the structured-data value is not "
                "one of them.",
            ],
            reach=0.4, on_important_page=True,
            sample_size=len(ev.html_pages) or 1, affected=len(distinct),
            corroborating_sources=2,
        ))
    return out


def _freshness(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    """Report a *risk*, never a claim that content is definitely out of date."""
    dated = [p for p in ev.html_pages if p.latest_date]
    if len(dated) < 3:
        return []
    current_year = datetime.now(timezone.utc).year
    stale_years = cfg.stale_days // 365
    cutoff = current_year - max(stale_years, 1)
    stale = [p for p in dated if int(p.latest_date) <= cutoff]
    if len(stale) < max(2, 0.5 * len(dated)):
        return []
    latest_overall = max(int(p.latest_date) for p in dated)
    return [make_finding(
        check_id="freshness_risk", category="discoverability",
        journey_stage="trust", dimension="freshness",
        title="Potential freshness risk: the most recent dates on the site are several years old",
        url=stale[0].url,
        observation=(
            f"{len(stale)} of {len(dated)} dated pages show no date later than "
            f"{cutoff}; the newest date found anywhere on the crawled pages is "
            f"{latest_overall}."),
        details=("Dates were read from time elements, article metadata and JSON-LD "
                 "datePublished/dateModified values. An old date does not prove the "
                 "content is out of date - it only means nothing on the page signals "
                 "recency."),
        metrics={"dated_pages": len(dated), "pages_at_or_before_cutoff": len(stale),
                 "cutoff_year": cutoff, "newest_year_found": latest_overall},
        affected_urls=[p.url for p in stale][:10],
        impact=("Without a recent date signal, automated systems have no evidence that "
                "the information still holds, so they may prefer more recently dated "
                "third-party sources when describing the brand."),
        action_summary="Publish explicit last-updated dates and refresh the pages whose facts have changed.",
        steps=["Review the listed pages and correct any facts that have changed.",
               "Add dateModified to the page's structured data when content is revised.",
               "Show a visible 'last updated' date on pages where recency matters.",
               "Avoid auto-bumping dates on unchanged pages - that removes the signal's value."],
        benign_explanations=[
            "Reference content that has not changed is correctly left undated; an "
            "old date is not evidence that the facts are wrong.",
        ],
        reach=len(stale) / max(len(dated), 1), on_important_page=True,
        sample_size=len(dated), affected=len(stale),
        conflicting_signals=True,  # dates are indirect evidence; keeps confidence honest
    )]
