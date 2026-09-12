"""AI discoverability audit.

Checks are organised by the stage of the discoverability journey they break:

    DISCOVER -> ACCESS -> UNDERSTAND -> EXTRACT -> TRUST -> REPRESENT

Each check runs only when its precondition is actually observable; when a site
legitimately has nothing to check (no products, no blog, no structured data
requirement) the check yields nothing rather than a finding. Checks report the
number they measured so the report can show WHAT / WHERE / HOW WE KNOW.
"""
from __future__ import annotations

from typing import Any

from ..config import AuditConfig
from ..evidence import PageEvidence, SiteEvidence
from ..importance import CONTENT_ROLES
from ..urls import same_site
from ..findings import Finding
from .base import make_finding

ORG_TYPES = {"organization", "corporation", "localbusiness", "onlinestore",
             "store", "ngo", "educationalorganization", "website",
             "professionalservice", "restaurant", "medicalorganization"}
PRODUCT_TYPES = {"product", "productgroup", "offer", "aggregateoffer"}
ARTICLE_TYPES = {"article", "newsarticle", "blogposting", "techarticle"}


def _has_type(page: PageEvidence, wanted: set[str]) -> bool:
    return any(t.lower() in wanted for t in page.jsonld_types + page.microdata_types)


def audit(ev: SiteEvidence, config: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    out += _discover_stage(ev, config)
    out += _access_stage(ev, config)
    out += _understand_stage(ev, config)
    out += _extract_stage(ev, config)
    out += _represent_stage(ev, config)
    return out


# --------------------------------------------------------------- DISCOVER ---

def _discover_stage(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    pages = ev.pages

    # A site-wide robots disallow is reported as the robots problem, not as an
    # unreachable site: the pages exist, we simply must not fetch them.
    if ev.robots_blocks_site:
        blocked_note = ""
        if not ev.home_reachable:
            blocked_note = (" No page could be retrieved during this audit because "
                            "the crawler honours robots.txt.")
        out.append(make_finding(
            check_id="robots_blocks_site", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title="robots.txt disallows crawling of the whole site for all agents",
            url=ev.target_url.rstrip("/") + "/robots.txt",
            observation="robots.txt contains 'Disallow: /' under 'User-agent: *'."
                        + blocked_note,
            details="This instructs every compliant crawler not to fetch any page.",
            metrics={"robots_status": ev.robots_status,
                     "pages_retrieved": len(ev.html_pages)},
            impact=("Compliant automated systems will not retrieve site content at "
                    "all, so nothing on the site can be discovered, extracted or cited."),
            action_summary="Restrict the disallow rules to the paths that genuinely must stay private.",
            steps=[
                "Replace the blanket 'Disallow: /' with rules naming only private paths (for example /cart, /account).",
                "Keep public marketing, product and information pages allowed.",
                "Re-check robots.txt after deployment and confirm key URLs are allowed.",
            ],
            reach=1.0, on_important_page=True, sample_size=1, affected=1,
        ))
        return out

    # --- how did the homepage request actually end? -----------------------
    # A safety refusal, a redirect misconfiguration and a dead server are three
    # different facts. Only the last of them means the site is unreachable.
    if ev.home_outcome == "external_redirect":
        target = ev.home_redirect_target or "another domain"
        out.append(make_finding(
            check_id="homepage_redirects_offsite", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title="The homepage redirects to a different domain",
            url=ev.target_url,
            observation=(
                f"{ev.target_url} answered with HTTP {ev.home_status} and a Location "
                f"of {target}. The origin server responded normally; this audit does "
                "not follow redirects across registrable domains, so the destination "
                "was not crawled."),
            details=("Redirect chain observed: "
                     + " -> ".join(ev.home_redirect_chain + [target])
                     + ". This is the normal shape of a country, locale or brand "
                     "consolidation redirect and is not by itself a defect."),
            metrics={"home_status": ev.home_status,
                     "redirect_target": target,
                     "redirect_count": len(ev.home_redirect_chain),
                     "origin_responded": True,
                     "destination_crawled": False},
            impact=("Nothing here indicates the site is unavailable. It does mean the "
                    "audited hostname is not where the content lives, so this run "
                    "carries no evidence about the destination."),
            action_summary=f"Re-run the audit directly against {target} to audit the content.",
            steps=[
                f"Run the audit again with {target} as the target to assess the actual content.",
                "If the destination is a locale variant, audit the locale a given audience is served.",
                "Confirm the redirect is a 301 when the move is permanent, so the destination accumulates the authority.",
            ],
            benign_explanations=[
                "Country, locale and brand-consolidation redirects are normal and "
                "intentional; this finding records what happened, it does not assert "
                "a defect.",
                "The audit's own same-site policy, not the site, is the reason the "
                "destination was not crawled.",
            ],
            severity_override="low",
            reach=1.0, on_important_page=True, sample_size=1, affected=1,
        ))
        return out

    if ev.home_outcome in ("redirect_loop", "redirect_limit", "bad_location"):
        label = {"redirect_loop": "a redirect loop",
                 "redirect_limit": "more redirect hops than the limit allows",
                 "bad_location": "a redirect with an unusable Location header"}[
                     ev.home_outcome]
        out.append(make_finding(
            check_id="redirect_configuration_error", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title=f"The homepage request ended in {label}",
            url=ev.target_url,
            observation=(f"Requesting {ev.target_url} produced {label}. "
                         f"{ev.home_error or ''}").strip(),
            details=("Redirect chain observed: "
                     + (" -> ".join(ev.home_redirect_chain) or "none recorded")),
            metrics={"home_status": ev.home_status,
                     "redirect_count": len(ev.home_redirect_chain),
                     "outcome": ev.home_outcome,
                     "chain": ev.home_redirect_chain[:10]},
            impact=("No client can resolve the homepage to a final document, so the "
                    "entry point to the site cannot be retrieved by anything that "
                    "follows redirects the standard way."),
            action_summary="Fix the redirect rule so the homepage resolves to one final URL.",
            steps=["Trace the redirect chain with a client that does not follow redirects and inspect each Location header.",
                   "Remove the rule that sends the chain back on itself or lengthens it.",
                   "Make the homepage resolve in at most one hop."],
            reach=1.0, on_important_page=True, sample_size=1, affected=1,
        ))
        return out

    if ev.home_outcome == "private_redirect":
        out.append(make_finding(
            check_id="redirect_to_private_address", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title="The homepage redirects to a non-public network address",
            url=ev.target_url,
            observation=(
                f"{ev.target_url} answered with HTTP {ev.home_status} and a Location "
                f"of {ev.home_redirect_target}, which resolves to a private, loopback "
                "or otherwise non-public address. The redirect was not followed."),
            details="Refused by the address guard before any request was made to the target.",
            metrics={"home_status": ev.home_status,
                     "redirect_target": ev.home_redirect_target},
            impact=("A public URL that points at an internal address is unreachable "
                    "for any external client and is usually a misconfigured "
                    "environment or a leaked internal hostname."),
            action_summary="Point the redirect at the public hostname that should serve this content.",
            steps=["Check for an environment-specific redirect rule that leaked into production.",
                   "Replace the internal hostname with the public one.",
                   "Verify from outside your network that the homepage resolves."],
            reach=1.0, on_important_page=True, sample_size=1, affected=1,
        ))
        return out

    if ev.home_outcome == "robots_blocked":
        # The homepage itself is disallowed without a site-wide block. The server
        # is fine; we are the ones not fetching it.
        out.append(make_finding(
            check_id="important_page_robots_blocked", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title="robots.txt disallows the homepage",
            url=ev.target_url,
            observation=(f"robots.txt disallows {ev.target_url} for this crawler, so "
                         "the homepage was not fetched. The server itself was not "
                         "reported as failing."),
            details=("Disallowed path prefixes observed: "
                     + (", ".join(ev.robots_blocked_paths[:8]) or "not recorded")),
            metrics={"home_status": ev.home_status,
                     "robots_blocked_paths": ev.robots_blocked_paths[:8]},
            impact=("Compliant automated systems will not retrieve the site's entry "
                    "point, so the brand's own description of itself is unavailable "
                    "to them."),
            action_summary="Allow the homepage in robots.txt.",
            steps=["Remove the rule that matches the site root.",
                   "Restrict disallow rules to genuinely private paths.",
                   "Re-check with a robots.txt parser after deployment."],
            reach=1.0, on_important_page=True, sample_size=1, affected=1,
        ))
        return out

    if not ev.home_reachable:
        out.append(make_finding(
            check_id="site_unreachable", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title="The site homepage did not return a successful response",
            url=ev.target_url,
            observation=(
                f"A GET request to {ev.target_url} returned "
                f"{ev.home_status if ev.home_status is not None else 'no response'}"
                + (f" ({ev.home_error})" if ev.home_error else "") + "."),
            details=("Every downstream check depends on the homepage being "
                     f"retrievable. Classified outcome: {ev.home_outcome}. This is a "
                     "genuine failure to obtain a response, not a redirect the audit "
                     "declined to follow."),
            metrics={"home_status": ev.home_status,
                     "outcome": ev.home_outcome,
                     "error": ev.home_error,
                     "redirect_count": len(ev.home_redirect_chain)},
            impact=("If the entry point cannot be retrieved, automated systems have "
                    "no reliable starting point for the site and may fall back to "
                    "third-party descriptions of the brand."),
            action_summary="Make the homepage return HTTP 200 to unauthenticated, non-browser clients.",
            steps=[
                "Request the homepage with a plain HTTP client (no cookies, no JS) and record the status code.",
                "Check for bot filtering, geo-blocking or TLS errors that affect non-browser clients.",
                "Verify the canonical host (with and without www) resolves and serves the same content.",
            ],
            reach=1.0, on_important_page=True, sample_size=1, affected=1,
        ))
        return out

    # Only pages that carry public information count here: an account or
    # checkout path that robots.txt disallows is correct behaviour, not a defect.
    blocked_important = [p for p in pages
                         if not p.robots_allowed and p.importance >= 0.5
                         and p.role in CONTENT_ROLES]
    if blocked_important:
        reach = len(blocked_important) / max(len(ev.important_pages) or 1, 1)
        out.append(make_finding(
            check_id="important_page_robots_blocked", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title=f"{len(blocked_important)} likely-important page(s) are disallowed in robots.txt",
            url=blocked_important[0].url,
            observation="; ".join(
                f"{p.url} (role: {p.role}) is disallowed by robots.txt"
                for p in blocked_important[:5]),
            details=f"Disallowed path prefixes observed: {', '.join(ev.robots_blocked_paths[:8]) or 'n/a'}",
            metrics={"blocked_pages": len(blocked_important),
                     "important_pages": len(ev.important_pages)},
            affected_urls=[p.url for p in blocked_important],
            impact=("Content on these pages is unavailable to compliant automated "
                    "retrieval, so the facts they contain cannot be extracted or cited."),
            action_summary="Allow crawling of the informational pages that are currently disallowed.",
            steps=[
                "Review each disallowed prefix and confirm whether it really needs to be private.",
                "Add explicit Allow rules for the informational pages listed in this finding.",
                "Re-test with a robots.txt parser before and after the change.",
            ],
            reach=reach, on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(blocked_important),
        ))

    blocked_ai = {a: r for a, r in ev.ai_agent_rules.items()
                  if r.get("blocked_entirely")}
    partial_ai = {a: r for a, r in ev.ai_agent_rules.items()
                  if not r.get("blocked_entirely") and r.get("disallow")}
    if blocked_ai:
        listing = "; ".join(
            f"{agent} ({r['operator']})" for agent, r in list(blocked_ai.items())[:8])
        out.append(make_finding(
            check_id="ai_crawler_blocked", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title=(f"robots.txt blocks {len(blocked_ai)} named AI or answer-engine "
                   "crawler(s) from the entire site"),
            url=ev.target_url.rstrip("/") + "/robots.txt",
            observation=(
                f"robots.txt contains a 'Disallow: /' group for: {listing}. "
                "General crawling is not blocked, so these agents are singled out."),
            details=("Read from the per-user-agent groups in robots.txt. Agents that "
                     "merely fall back to the '*' group are not counted here."),
            metrics={"blocked_agents": sorted(blocked_ai),
                     "blocked_count": len(blocked_ai),
                     "partially_restricted_agents": sorted(partial_ai)},
            impact=("These are the crawlers that assistants and answer engines use to "
                    "reach a site. While they are disallowed, the brand cannot be "
                    "retrieved, quoted or cited by those systems no matter how good "
                    "the on-page content is - third-party descriptions are used instead."),
            action_summary=("Confirm whether this block is a deliberate content policy; "
                            "if AI visibility is the goal, allow the agents you want to "
                            "be discovered by."),
            steps=[
                "Decide per agent whether the goal is content protection or AI visibility - these pull in opposite directions.",
                "For agents you want to be discoverable in, remove the 'Disallow: /' from their group or narrow it to private paths.",
                "Keep training-only agents blocked separately from retrieval agents if you want citation without training use.",
                "Re-check robots.txt after deployment with each agent token.",
            ],
            benign_explanations=[
                "Blocking these agents is often a deliberate content-licensing or "
                "copyright decision, in which case this is working as intended and "
                "should be recorded as accepted rather than fixed.",
                "Some organisations block training crawlers while allowing "
                "retrieval crawlers; check the finding's agent list before acting.",
            ],
            reach=1.0, on_important_page=True, sample_size=1, affected=1,
        ))

    if not ev.sitemap_present and len(ev.html_pages) >= 5:
        out.append(make_finding(
            check_id="sitemap_missing", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title="No XML sitemap was found",
            url=ev.target_url,
            observation=("Neither /sitemap.xml nor any Sitemap: directive in "
                         "robots.txt returned a usable sitemap."),
            details=f"{len(ev.html_pages)} HTML pages were reachable by link following.",
            metrics={"sitemap_locations_tried": ev.sitemap_locations or ["/sitemap.xml"],
                     "html_pages_crawled": len(ev.html_pages)},
            impact=("Without a sitemap, automated systems must rely entirely on link "
                    "discovery, so pages that are weakly linked may never be reached."),
            action_summary="Publish an XML sitemap and reference it from robots.txt.",
            steps=[
                "Generate a sitemap listing canonical URLs of the public pages.",
                "Serve it at /sitemap.xml with HTTP 200 and content-type application/xml.",
                "Add a 'Sitemap: https://<host>/sitemap.xml' line to robots.txt.",
            ],
            reach=0.5, on_important_page=False,
            sample_size=len(ev.html_pages), affected=1,
        ))

    # 401/403 mean access control or bot filtering rather than a broken link, so
    # they are not reported as errors; only missing and server-failing pages are.
    error_statuses = {404, 410}
    if ev.sitemap_broken_urls:
        out.append(make_finding(
            check_id="sitemap_broken_urls", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title=f"{len(ev.sitemap_broken_urls)} URL(s) listed in the sitemap do not serve content",
            url=ev.sitemap_locations[0] if ev.sitemap_locations else ev.target_url,
            observation="; ".join(
                f"{p.url} is listed in the sitemap but returned HTTP {p.status}"
                for p in pages if p.url in set(ev.sitemap_broken_urls)),
            details=("The sitemap is the list a retrieval system is invited to trust; "
                     "entries that fail waste its crawl budget on this site."),
            metrics={"broken_sitemap_urls": len(ev.sitemap_broken_urls),
                     "sitemap_url_count": ev.sitemap_url_count},
            affected_urls=ev.sitemap_broken_urls,
            impact=("A sitemap containing dead URLs reduces the value of the whole "
                    "file: retrieval systems spend their budget on failures instead "
                    "of on the pages that matter."),
            action_summary="Regenerate the sitemap from live, canonical URLs only.",
            steps=["Remove the failing URLs from the sitemap.",
                   "Automate sitemap generation from the live routing table so it cannot drift.",
                   "Return 301 to a replacement where the content genuinely moved."],
            reach=min(1.0, len(ev.sitemap_broken_urls) / max(ev.sitemap_url_count, 1) * 5),
            on_important_page=False,
            sample_size=ev.sitemap_url_count or 1,
            affected=len(ev.sitemap_broken_urls),
        ))

    if ev.sitemap_present:
        absent = [p for p in ev.important_pages
                  if p.ok and not p.in_sitemap and p.role in CONTENT_ROLES
                  and p.role != "home"]
        if absent and len(absent) >= 2:
            out.append(make_finding(
                check_id="sitemap_missing_important_pages", category="discoverability",
                journey_stage="discover", dimension="discoverability",
                title=f"{len(absent)} likely-important page(s) are absent from the sitemap",
                url=absent[0].url,
                observation="; ".join(
                    f"{p.url} (role: {p.role}) is not listed in the sitemap"
                    for p in absent[:5]),
                details=(f"The sitemap lists {ev.sitemap_url_count} URL(s) and was "
                         f"found at {', '.join(ev.sitemap_locations[:2])}."),
                metrics={"missing_pages": len(absent),
                         "sitemap_url_count": ev.sitemap_url_count,
                         "sitemap_coverage_of_crawled_pages": ev.sitemap_coverage},
                affected_urls=[p.url for p in absent],
                impact=("A sitemap that omits the pages a brand most wants understood "
                        "leaves their discovery to link-following alone."),
                action_summary="Include these pages in the XML sitemap.",
                steps=["Add the listed canonical URLs to the sitemap.",
                       "Generate the sitemap from the live route list rather than by hand.",
                       "Set lastmod so consumers can tell what changed."],
                benign_explanations=[
                    "A sitemap that deliberately covers only one content type (for "
                    "example articles) is a legitimate design choice.",
                ],
                reach=len(absent) / max(len(ev.important_pages) or 1, 1),
                on_important_page=True,
                sample_size=len(ev.important_pages) or 1, affected=len(absent),
            ))

    errors = [p for p in pages
              if p.status and (p.status in error_statuses or p.status >= 500)
              and p.importance >= 0.4]
    if errors:
        reach = len(errors) / max(len(pages), 1)
        out.append(make_finding(
            check_id="important_page_http_error", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title=f"{len(errors)} linked page(s) returned an HTTP error",
            url=errors[0].url,
            observation="; ".join(f"{p.url} returned HTTP {p.status}" for p in errors[:5]),
            details="These URLs are linked from crawled pages but do not serve content.",
            metrics={"error_pages": len(errors), "crawled": len(pages),
                     "statuses": sorted({p.status for p in errors if p.status})},
            affected_urls=[p.url for p in errors],
            impact=("Links that resolve to errors waste retrieval attempts and can "
                    "leave referenced facts unavailable."),
            action_summary="Fix or remove the internal links that resolve to error responses.",
            steps=[
                "Confirm each failing URL and decide whether to restore it or redirect it.",
                "Update the internal links that point at removed URLs.",
                "Return 301 to a relevant replacement where content genuinely moved.",
            ],
            reach=reach, on_important_page=any(p.importance >= 0.5 for p in errors),
            sample_size=len(pages), affected=len(errors),
        ))

    chains = [p for p in pages if p.redirect_count >= 2]
    if chains:
        out.append(make_finding(
            check_id="redirect_chain", category="discoverability",
            journey_stage="discover", dimension="discoverability",
            title=f"{len(chains)} URL(s) resolve through a chain of two or more redirects",
            url=chains[0].url,
            observation="; ".join(
                f"{p.url} required {p.redirect_count} redirects" for p in chains[:5]),
            metrics={"pages_with_chains": len(chains), "crawled": len(pages)},
            affected_urls=[p.url for p in chains],
            impact="Redirect chains add latency and some clients stop following after a few hops.",
            action_summary="Collapse redirect chains so each old URL points directly at its final target.",
            steps=["Map each chain start to its final URL.",
                   "Replace intermediate hops with a single 301.",
                   "Update internal links to reference the final URL directly."],
            reach=len(chains) / max(len(pages), 1), on_important_page=False,
            sample_size=len(pages), affected=len(chains),
        ))
    return out


# ----------------------------------------------------------------- ACCESS ---

def _access_stage(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    noindex = [p for p in ev.pages
               if "noindex" in (p.meta_robots or "") and p.importance >= 0.5]
    if noindex:
        out.append(make_finding(
            check_id="noindex_on_important_page", category="discoverability",
            journey_stage="access", dimension="discoverability",
            title=f"{len(noindex)} likely-important page(s) carry a noindex directive",
            url=noindex[0].url,
            observation="; ".join(
                f"{p.url} has <meta name=\"robots\" content=\"{p.meta_robots}\">"
                for p in noindex[:5]),
            metrics={"noindex_pages": len(noindex),
                     "important_pages": len(ev.important_pages)},
            affected_urls=[p.url for p in noindex],
            impact=("A noindex directive asks retrieval systems not to keep the page, "
                    "so its content is unlikely to be surfaced or cited even though it "
                    "is publicly reachable."),
            action_summary="Remove the noindex directive from pages that are meant to be public.",
            steps=["Confirm each listed page is intended to be publicly discoverable.",
                   "Remove the noindex value from the robots meta tag / X-Robots-Tag header.",
                   "Keep noindex only on genuinely private or duplicate URLs."],
            reach=len(noindex) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(noindex),
        ))

    header_noindex = [p for p in ev.pages
                      if "noindex" in (p.x_robots_tag or "") and p.importance >= 0.5]
    if header_noindex:
        out.append(make_finding(
            check_id="noindex_header_on_important_page", category="discoverability",
            journey_stage="access", dimension="discoverability",
            title=(f"{len(header_noindex)} likely-important page(s) send a noindex "
                   "X-Robots-Tag response header"),
            url=header_noindex[0].url,
            observation="; ".join(
                f"{p.url} responded with X-Robots-Tag: {p.x_robots_tag}"
                for p in header_noindex[:5]),
            details=("The directive is in the HTTP response header, so it applies even "
                     "though nothing in the page markup says noindex - a common reason "
                     "this goes unnoticed."),
            metrics={"pages": len(header_noindex)},
            affected_urls=[p.url for p in header_noindex],
            impact=("Retrieval systems are asked not to retain these pages, so their "
                    "content is unlikely to be surfaced or cited."),
            action_summary="Remove the noindex directive from the response headers of pages meant to be public.",
            steps=["Find where the header is set (CDN, reverse proxy, framework middleware, staging config).",
                   "Remove noindex for the public routes listed here.",
                   "Re-check with a header-inspecting request after deployment."],
            benign_explanations=[
                "Staging, preview and duplicate URLs are correctly served with "
                "noindex; confirm the listed URLs are the production ones.",
            ],
            reach=len(header_noindex) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(header_noindex),
        ))

    # rendering dependency
    rendered = [p for p in ev.pages if p.rendering.ok]
    if rendered:
        js_pages = [p for p in rendered if p.rendering.js_dependent]
        if js_pages:
            important_hit = any(p.importance >= 0.5 for p in js_pages)
            reach = len(js_pages) / len(rendered)
            worst = max(js_pages, key=lambda p: p.rendering.added_word_ratio)
            out.append(make_finding(
                check_id="js_dependent_content", category="discoverability",
                journey_stage="extract", dimension="content_accessibility",
                title=("Substantial page content is absent from the initial HTML and "
                       "appears only after JavaScript execution"),
                url=worst.url,
                observation=(
                    f"On {worst.url} the initial HTML contains "
                    f"{worst.rendering.raw_words} words of visible text while the "
                    f"rendered DOM contains {worst.rendering.rendered_words} "
                    f"({int(worst.rendering.added_word_ratio * 100)}% of the visible "
                    "text is added by JavaScript)."
                ),
                details="; ".join(
                    f"{p.url}: raw {p.rendering.raw_words}w -> rendered "
                    f"{p.rendering.rendered_words}w "
                    f"({int(p.rendering.added_word_ratio * 100)}% added)"
                    for p in js_pages[:5]),
                metrics={
                    "js_dependent_pages": len(js_pages),
                    "rendered_pages": len(rendered),
                    "max_added_word_ratio": worst.rendering.added_word_ratio,
                    "threshold": cfg.js_dependency_ratio,
                    "rendered_only_excerpt": worst.rendering.rendered_only_excerpt,
                },
                affected_urls=[p.url for p in js_pages],
                impact=("Retrieval clients that do not execute JavaScript see only a "
                        "fraction of the page, so product, pricing or company facts "
                        "that live in the rendered DOM may not be extracted at all."),
                action_summary=("Serve the primary content of these pages in the initial "
                                "HTML response (server-side rendering, static generation "
                                "or hydration of pre-rendered markup)."),
                steps=[
                    "Identify which content blocks are injected client-side on the listed pages.",
                    "Render that content server-side (SSR/SSG) or inline it as pre-rendered markup that hydration replaces.",
                    "Re-test with JavaScript disabled and confirm the key facts appear in the raw HTML.",
                    "Where full SSR is impractical, mirror the key facts in JSON-LD delivered in the initial HTML.",
                ],
                reach=reach, on_important_page=important_hit,
                sample_size=len(rendered), affected=len(js_pages),
            ))

    deep = [p for p in ev.pages
            if p.importance >= 0.5 and p.role != "home" and p.depth >= 3]
    if deep:
        out.append(make_finding(
            check_id="important_page_deep", category="discoverability",
            journey_stage="access", dimension="discoverability",
            title=f"{len(deep)} likely-important page(s) sit {min(p.depth for p in deep)}+ clicks from the homepage",
            url=deep[0].url,
            observation="; ".join(
                f"{p.url} (role: {p.role}) is {p.depth} link hops from the homepage "
                f"with {p.incoming_internal_links} incoming internal link(s)"
                for p in deep[:5]),
            details="Depth is measured as the shortest link path found during the crawl.",
            metrics={"deep_pages": len(deep),
                     "max_depth_observed": max(p.depth for p in deep)},
            affected_urls=[p.url for p in deep],
            impact=("Bounded crawlers frequently stop before deep pages, so content "
                    "that is several hops away may never be retrieved."),
            action_summary="Link these pages from the primary navigation or from a shallow hub page.",
            steps=["Add the listed pages to the main navigation or footer navigation.",
                   "Create a shallow hub page that links to them if the navigation is full.",
                   "Include the URLs in the XML sitemap."],
            reach=len(deep) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(deep),
        ))

    orphans = [p for p in ev.pages
               if p.importance >= 0.5 and p.role != "home"
               and p.incoming_internal_links == 0 and p.ok]
    if orphans:
        out.append(make_finding(
            check_id="important_page_orphaned", category="discoverability",
            journey_stage="access", dimension="discoverability",
            title=f"{len(orphans)} likely-important page(s) receive no internal links from crawled pages",
            url=orphans[0].url,
            observation="; ".join(
                f"{p.url} (role: {p.role}) has 0 incoming internal links among "
                f"{len(ev.html_pages)} crawled pages"
                f"{'; not present in the sitemap' if not p.in_sitemap else ''}"
                for p in orphans[:5]),
            metrics={"orphan_pages": len(orphans),
                     "crawled_html_pages": len(ev.html_pages)},
            affected_urls=[p.url for p in orphans],
            impact=("Pages with no inbound internal links are reachable only if the URL "
                    "is already known, which makes their content easy for automated "
                    "systems to miss."),
            action_summary="Link these pages from relevant existing pages and include them in the sitemap.",
            steps=["Add contextual links from related pages and from the navigation.",
                   "Ensure the URLs appear in the XML sitemap.",
                   "Verify the links exist in the server-rendered HTML, not only after hydration."],
            reach=len(orphans) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(orphans),
        ))
    return out


# ------------------------------------------------------------- UNDERSTAND ---

def _understand_stage(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    html_pages = ev.html_pages
    if not html_pages:
        return out

    # Hub pages (navigation-heavy index pages) legitimately carry little prose,
    # so they are excluded rather than reported as thin.
    # Contact pages are legitimately short (an address and a form is the whole
    # point), so they are exempt; hub pages are exempt for the same reason.
    thin = [p for p in html_pages
            if p.importance >= 0.5 and p.word_count < cfg.thin_content_words
            and not p.rendering.js_dependent
            and p.outgoing_internal_links < 6
            and p.role not in ("contact", "legal")]
    if thin:
        out.append(make_finding(
            check_id="thin_important_page", category="discoverability",
            journey_stage="understand", dimension="content_accessibility",
            title=f"{len(thin)} likely-important page(s) contain very little extractable text",
            url=thin[0].url,
            observation="; ".join(
                f"{p.url} (role: {p.role}) has {p.word_count} words of visible text"
                f"{f' and {p.images_total} images' if p.images_total else ''}"
                for p in thin[:5]),
            details=(f"Threshold used: fewer than {cfg.thin_content_words} words. "
                     "Pages whose text is supplied by JavaScript are excluded here and "
                     "reported under the rendering check instead, as are contact and "
                     "legal pages and navigation hubs, which are short by design."
                     + ("" if ev.render_evidence_available else
                        " No rendered evidence was available for this run ("
                        f"{ev.rendering.get('status', 'unknown')}), so content that is "
                        "injected by JavaScript would not have been counted; this "
                        "finding is based on the server-rendered HTML alone.")),
            metrics={"thin_pages": len(thin), "threshold_words": cfg.thin_content_words,
                     "word_counts": {p.url: p.word_count for p in thin[:8]}},
            affected_urls=[p.url for p in thin],
            impact=("There is little textual substance for an automated system to "
                    "summarise or quote, so the page is unlikely to be used as a source "
                    "even when it is retrieved."),
            action_summary="Express the key information of these pages as readable body text.",
            steps=["Identify the facts the page is meant to convey.",
                   "Write them into the page body as text rather than as images or downloads.",
                   "Keep headings descriptive so the structure explains the content."],
            benign_explanations=([
                "Rendered evidence was not available for this run, so a page whose "
                "text is supplied by JavaScript could appear thin here while reading "
                "normally in a browser. Re-run with rendering enabled to confirm.",
            ] if not ev.render_evidence_available else []),
            reach=len(thin) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(thin),
            # Without rendered evidence the absence of text is not fully
            # established, so confidence must reflect that.
            conflicting_signals=not ev.render_evidence_available,
        ))

    missing_h1 = [p for p in html_pages if p.importance >= 0.5 and not p.h1]
    if missing_h1 and len(missing_h1) >= max(2, 0.3 * len(ev.important_pages)):
        out.append(make_finding(
            check_id="missing_h1", category="discoverability",
            journey_stage="understand", dimension="discoverability",
            title=f"{len(missing_h1)} likely-important page(s) have no H1 heading",
            url=missing_h1[0].url,
            observation="; ".join(
                f"{p.url} has no <h1> ({p.headings_total} headings of any level)"
                for p in missing_h1[:5]),
            metrics={"pages_without_h1": len(missing_h1),
                     "important_pages": len(ev.important_pages)},
            affected_urls=[p.url for p in missing_h1],
            impact=("Without a top-level heading the page's subject has to be inferred "
                    "from the title alone, which weakens topical understanding."),
            action_summary="Give each of these pages one descriptive H1 that names its subject.",
            steps=["Add a single <h1> stating what the page is about.",
                   "Keep the heading hierarchy ordered (h1 then h2 then h3).",
                   "Avoid using an image of text as the page heading."],
            reach=len(missing_h1) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(missing_h1),
        ))

    # Reported only when the page offers no authored summary at all - no meta
    # description and no og:description. A page that has one of them is not
    # missing a machine-readable summary, so this stays out of generic-SEO territory.
    no_desc = [p for p in html_pages
               if p.importance >= 0.5 and not p.meta_description
               and "description" not in p.og_keys]
    if no_desc and len(no_desc) >= max(3, 0.5 * len(ev.important_pages)):
        out.append(make_finding(
            check_id="missing_meta_description", category="discoverability",
            journey_stage="understand", dimension="discoverability",
            title=f"{len(no_desc)} of {len(ev.important_pages)} likely-important pages have no meta description",
            url=no_desc[0].url,
            observation=f"No <meta name=\"description\"> on: " +
                        ", ".join(p.url for p in no_desc[:5]),
            metrics={"pages_without_description": len(no_desc),
                     "important_pages": len(ev.important_pages)},
            affected_urls=[p.url for p in no_desc],
            impact=("A short authored summary gives retrieval systems a reliable "
                    "one-sentence description; without it, the summary is guessed "
                    "from body text."),
            action_summary="Add a concise, page-specific meta description to each listed page.",
            steps=["Write a 1-2 sentence description naming the page's subject and audience.",
                   "Keep descriptions unique per page.",
                   "Make sure the description agrees with the visible content."],
            reach=len(no_desc) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(no_desc),
        ))

    # canonical pointing somewhere else on important pages
    # A cross-canonical is normal and correct for duplicates, filtered views and
    # pagination, so it is only reported when it points at another host or at a
    # URL that did not serve content - the cases that actually lose the page.
    crawled_ok = {p.url for p in ev.pages if p.ok}
    broken_or_offsite = []
    for p in html_pages:
        if not p.canonical or p.importance < 0.5:
            continue
        if p.canonical.rstrip("/") == p.url.rstrip("/"):
            continue
        if not same_site(p.canonical, ev.target_url):
            broken_or_offsite.append((p, "points to a different host"))
        else:
            dead = next((q for q in ev.pages
                         if q.url == p.canonical and not q.ok), None)
            if dead is not None:
                broken_or_offsite.append(
                    (p, f"points to {p.canonical} which returned HTTP {dead.status}"))
    bad_canon = [p for p, _ in broken_or_offsite]
    if bad_canon:
        out.append(make_finding(
            check_id="canonical_conflict", category="discoverability",
            journey_stage="understand", dimension="discoverability",
            title=(f"{len(bad_canon)} likely-important page(s) declare a canonical URL "
                   "that is off-site or does not resolve"),
            url=bad_canon[0].url,
            observation="; ".join(
                f"{p.url} declares canonical {p.canonical}, which {why}"
                for p, why in broken_or_offsite[:5]),
            details=("Cross-canonicals to a live URL on the same site are normal for "
                     "duplicates and pagination and are not reported; only off-site "
                     "targets and targets that failed to serve content are."),
            metrics={"pages": len(bad_canon)},
            affected_urls=[p.url for p in bad_canon],
            impact=("A canonical pointing elsewhere tells retrieval systems to treat "
                    "another URL as the authority, so this page's own content may be "
                    "attributed to a different address or dropped."),
            action_summary="Point each canonical at a live URL on this site, or self-reference it.",
            steps=["For each listed page, check whether the canonical target really is the same content and is reachable.",
                   "Set a self-referencing canonical where the page is the primary version.",
                   "Keep cross-canonicals only for genuine duplicates that resolve."],
            benign_explanations=[
                "A syndicated page may legitimately canonicalise to the original "
                "publisher on another host.",
            ],
            reach=len(bad_canon) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(bad_canon),
        ))
    return out


# ---------------------------------------------------------------- EXTRACT ---

def _extract_stage(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    html_pages = ev.html_pages
    if not html_pages:
        return out

    invalid = [p for p in ev.pages if p.jsonld_invalid]
    if invalid:
        out.append(make_finding(
            check_id="invalid_structured_data", category="discoverability",
            journey_stage="extract", dimension="entity_clarity",
            title=f"{len(invalid)} page(s) contain a JSON-LD block that does not parse",
            url=invalid[0].url,
            observation="; ".join(
                f"{p.url}: {p.jsonld_invalid[0]}" for p in invalid[:5]),
            details=("The block is present in the HTML but is not valid JSON, so a "
                     "consumer must discard it entirely."),
            metrics={"pages_with_invalid_jsonld": len(invalid),
                     "pages_checked": len(ev.pages)},
            affected_urls=[p.url for p in invalid],
            impact=("Structured data that fails to parse provides no machine-readable "
                    "facts at all, so the effort of publishing it is wasted and the "
                    "page falls back to text interpretation."),
            action_summary="Fix the JSON syntax so each ld+json block parses, then validate the vocabulary.",
            steps=["Run each block through a JSON parser and correct the syntax error reported here.",
                   "Escape quotes and remove trailing commas in templated values.",
                   "Validate the corrected block against schema.org expectations for its @type."],
            reach=len(invalid) / max(len(ev.pages), 1), on_important_page=True,
            sample_size=len(ev.pages), affected=len(invalid),
        ))

    defective = [p for p in ev.pages if p.jsonld_defects]
    if defective:
        out.append(make_finding(
            check_id="incomplete_structured_data", category="discoverability",
            journey_stage="extract", dimension="entity_clarity",
            title=(f"{len(defective)} page(s) publish structured data that parses but "
                   "is missing expected properties or contains placeholders"),
            url=defective[0].url,
            observation="; ".join(
                f"{p.url}: {'; '.join(p.jsonld_defects[:3])}" for p in defective[:4]),
            details=("Checked the shape of syntactically valid JSON-LD: expected "
                     "properties for the declared @type, empty values, and unreplaced "
                     "template placeholders."),
            metrics={"pages_with_defects": len(defective),
                     "pages_checked": len(ev.html_pages),
                     "defects": {p.url: p.jsonld_defects for p in defective[:5]}},
            affected_urls=[p.url for p in defective],
            impact=("Structured data that lacks its identifying properties gives a "
                    "consumer nothing to attach the facts to, so the block is "
                    "published but cannot be used - and a placeholder value can put "
                    "an outright wrong fact into machine-readable form."),
            action_summary="Populate the expected properties for each declared type and remove template placeholders.",
            steps=["Fix the specific properties listed in this finding.",
                   "Replace any templating placeholder with the real value at render time.",
                   "Validate the corrected blocks against schema.org for their @type.",
                   "Add a build-time check so an empty required property fails CI."],
            benign_explanations=[
                "A property that genuinely does not apply to the entity is better "
                "omitted than filled with a placeholder; verify per property.",
            ],
            reach=len(defective) / max(len(ev.html_pages), 1), on_important_page=True,
            sample_size=len(ev.html_pages) or 1, affected=len(defective),
        ))

    # Organization / WebSite identity in structured data - site-level check.
    org_pages = [p for p in html_pages if _has_type(p, ORG_TYPES)]
    if not org_pages and len(html_pages) >= 3:
        out.append(make_finding(
            check_id="missing_organization_identity", category="discoverability",
            journey_stage="represent", dimension="entity_clarity",
            title="No Organization or WebSite structured data was found anywhere on the site",
            url=ev.target_url,
            observation=(
                f"0 of {len(html_pages)} crawled HTML pages contain JSON-LD or "
                "microdata of an Organization/LocalBusiness/WebSite type."),
            details=("Types observed across the site: " +
                     (", ".join(sorted({t for p in html_pages for t in p.jsonld_types}))
                      or "none")),
            metrics={"pages_with_org_schema": 0, "html_pages": len(html_pages),
                     "types_observed": sorted({t for p in html_pages
                                               for t in p.jsonld_types})},
            impact=("There is no explicit machine-readable statement of who the site "
                    "belongs to, so the brand's identity, official name and linked "
                    "profiles must be inferred from prose - a common cause of entity "
                    "ambiguity and misattribution."),
            action_summary=("Publish one Organization (or LocalBusiness) JSON-LD block "
                            "site-wide, plus a WebSite block on the homepage."),
            steps=[
                "Add an Organization node with name, url, logo and a description.",
                "Add sameAs links to the official profiles the organization controls.",
                "Include contact details (telephone / email / address) matching the visible contact page.",
                "Serve the block in the initial HTML on every page, or at least on the homepage and about page.",
            ],
            reach=1.0, on_important_page=True,
            sample_size=len(html_pages), affected=len(html_pages),
        ))

    # Product structured data - only when the site actually looks commercial.
    product_pages = [p for p in html_pages if p.role == "products"]
    if len(product_pages) >= 3:
        with_schema = [p for p in product_pages if _has_type(p, PRODUCT_TYPES)]
        missing = [p for p in product_pages if p not in with_schema]
        if len(missing) >= max(2, 0.5 * len(product_pages)):
            out.append(make_finding(
                check_id="missing_product_structured_data", category="discoverability",
                journey_stage="extract", dimension="entity_clarity",
                title=(f"{len(missing)} of {len(product_pages)} product-style pages "
                       "carry no Product structured data"),
                url=missing[0].url,
                observation=(f"{len(with_schema)} of {len(product_pages)} pages that look "
                             "like product pages expose Product/Offer structured data."),
                details="; ".join(f"{p.url} (types: {', '.join(p.jsonld_types) or 'none'})"
                                  for p in missing[:5]),
                metrics={"product_pages": len(product_pages),
                         "with_product_schema": len(with_schema),
                         "without_product_schema": len(missing)},
                affected_urls=[p.url for p in missing],
                impact=("Product attributes such as name, price and availability have "
                        "to be guessed from layout rather than read directly, which "
                        "makes extracted values less reliable."),
                action_summary="Add Product structured data with name, description, offers and availability.",
                steps=["Emit a Product node per product page in the initial HTML.",
                       "Include offers.price, offers.priceCurrency and offers.availability.",
                       "Keep the structured values identical to the values shown on the page."],
                reach=len(missing) / len(product_pages), on_important_page=True,
                sample_size=len(product_pages), affected=len(missing),
            ))

    # Facts locked in images: image-heavy page with almost no text.
    image_only = [p for p in html_pages
                  if p.importance >= 0.5 and p.images_total >= 5
                  and p.word_count < cfg.thin_content_words
                  and p.images_without_alt >= 0.6 * p.images_total]
    if image_only:
        out.append(make_finding(
            check_id="facts_in_images", category="discoverability",
            journey_stage="extract", dimension="content_accessibility",
            title=f"{len(image_only)} likely-important page(s) carry their information in images without text alternatives",
            url=image_only[0].url,
            observation="; ".join(
                f"{p.url} has {p.images_total} images ({p.images_without_alt} without "
                f"alt text) but only {p.word_count} words of visible text"
                for p in image_only[:5]),
            metrics={"pages": len(image_only)},
            affected_urls=[p.url for p in image_only],
            impact=("Information that exists only inside images cannot be read as text, "
                    "so those facts are effectively invisible to text-based extraction."),
            action_summary="Provide the information shown in the images as page text and add descriptive alt attributes.",
            steps=["Transcribe values shown in images (specs, prices, hours) into the page body.",
                   "Add meaningful alt text to informative images.",
                   "Keep decorative images with an empty alt attribute."],
            reach=len(image_only) / max(len(ev.important_pages) or 1, 1),
            on_important_page=True,
            sample_size=len(ev.important_pages) or 1, affected=len(image_only),
            conflicting_signals=not ev.render_evidence_available,
        ))
    return out


# -------------------------------------------------------------- REPRESENT ---

def _represent_stage(ev: SiteEvidence, cfg: AuditConfig) -> list[Finding]:
    out: list[Finding] = []
    socials = ev.facts_by_kind.get("social", [])
    org_schema_pages = [p for p in ev.html_pages if _has_type(p, ORG_TYPES)]
    # Only raised when the site *has* declared an Organization entity and left its
    # sameAs empty. A site that publishes no external profiles at all is simply a
    # site without them, which is not a defect.
    if org_schema_pages and not socials and len(ev.html_pages) >= 4:
        out.append(make_finding(
            check_id="no_corroborating_entity_links", category="discoverability",
            journey_stage="trust", dimension="entity_clarity",
            title="The site publishes no links to external profiles that could corroborate its identity",
            url=ev.target_url,
            observation=(
                f"{len(org_schema_pages)} page(s) declare an Organization/WebSite "
                f"entity, but no sameAs values and no links to recognised profile "
                f"hosts were found across {len(ev.html_pages)} crawled pages."),
            details=("Checked JSON-LD sameAs plus outbound links to widely used profile "
                     "and registry hosts."),
            metrics={"social_links_found": 0, "html_pages": len(ev.html_pages),
                     "pages_declaring_organization": len(org_schema_pages)},
            impact=("With no external references, the organization's identity rests on "
                    "the site's own claims alone, which gives automated systems nothing "
                    "to cross-check the brand against."),
            action_summary="Link the organization's official external profiles and mirror them in sameAs.",
            steps=["Link the profiles the organization actually controls from the footer or about page.",
                   "List the same URLs in the Organization JSON-LD sameAs array.",
                   "Keep the name used on those profiles consistent with the site."],
            benign_explanations=[
                "An organization that deliberately maintains no public external "
                "profiles has nothing to link, and this finding does not apply.",
            ],
            reach=0.4, on_important_page=False,
            sample_size=len(ev.html_pages), affected=1,
            direct_dom_evidence=True,
        ))
    return out
