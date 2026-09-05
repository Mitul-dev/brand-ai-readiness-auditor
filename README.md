# brand-ai-readiness-audit

An Agent Skill Marketplace that takes a website URL and returns an
evidence-backed audit of **AI discoverability** and **on-site engagement**, with
severity, suggested fixes and priority for every finding.

Built for the **Adobe University Hackathon 2026 — Agent Skill Marketplace.**

---

## What problem this solves

Brands can be invisible, stale, misrepresented or poorly experienced in AI
applications even when their websites work well for traditional search.

This marketplace evaluates a website directly and provides evidence-backed
findings across AI discoverability, information quality and on-site engagement.

The product concept is an **AI Website Readiness Auditor**, organised around an
**AI discoverability journey**:

```
DISCOVER → ACCESS → UNDERSTAND → EXTRACT → TRUST → REPRESENT
```

Every discoverability finding names the stage that broke, and backs that claim
with a number that was actually observed.

```
Stage:    EXTRACT
Problem:  Substantial page content is absent from the initial HTML.
Evidence: On /products/flow-meter the initial HTML contains 12 words of visible
          text while the rendered DOM contains 210 (94% added by JavaScript).
Impact:   Clients that do not execute JavaScript see a fraction of the page, so
          product facts may not be extracted at all.
```

---

## Design principle

```
DETERMINISTIC DATA COLLECTION → OBJECTIVE EVIDENCE → AGENT REASONING
        → FINDING → RECOMMENDATION
```

Code measures; the agent explains. Severity, confidence, reach and priority are
computed by deterministic functions from measured inputs — no language model
picks those numbers. The agent layer interprets, contextualises and presents.

The anti-pattern this deliberately avoids is `page → LLM → "what's wrong?"`,
which produces confident, unverifiable, site-specific guesses.

---

## Architecture

```
                  ┌─────────────────────────┐
                  │ audit-orchestrator      │  ← the ONE entrypoint
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ crawl-render-audit      │  safe bounded crawl + rendering
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ EVIDENCE ENGINE         │  compact, measured, JSON
                  │ pages · links · schema  │
                  │ rendering · facts       │
                  └───────────┬─────────────┘
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
   discoverability-   freshness-        engagement-
       audit          corroboration        audit
             └────────────────┼────────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ FINDING ENGINE          │  dedupe · severity · confidence
                  │                         │  reach · priority
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ FINAL REPORT (validated)│  score · findings · fixes
                  └─────────────────────────┘
```

### Skills

| Skill | Entrypoint | Responsibility |
|---|---|---|
| `audit-orchestrator` | **yes** | Validates the URL, runs the pipeline, normalizes and deduplicates findings, computes priority and the readiness score, validates the report schema. |
| `crawl-render-audit` | no | Safe read-only crawl and the evidence engine. Measures only; never judges. |
| `discoverability-audit` | no | Discover / access / understand / extract / represent checks. |
| `freshness-corroboration` | no | Entity naming consistency, contact-fact consistency, freshness risk. |
| `engagement-audit` | no | Orientation, page identity, navigation, next step, context retention. |

The split is functional, not cosmetic: the crawl skill is the only one that
touches the network, and the three analysis skills are pure functions over an
evidence file, so any of them can be run, tested or replaced independently.

### Check inventory

| Stage | Checks |
|---|---|
| DISCOVER | site unreachable · site-wide robots disallow · **named AI/answer-engine crawlers disallowed** · important page disallowed · HTTP 404/410/5xx · missing sitemap · **sitemap entries that fail** · **important pages absent from the sitemap** · redirect chains |
| ACCESS | `noindex` meta tag · **`noindex` X-Robots-Tag header** · JavaScript-dependent content · important pages 3+ hops deep · important pages with no inbound internal links |
| UNDERSTAND | thin important pages · missing H1 · no authored summary anywhere · off-site or unresolvable canonical |
| EXTRACT | JSON-LD that does not parse · **JSON-LD that parses but is missing expected properties or holds placeholders** · missing Organization/WebSite identity · product pages without Product schema · information carried only in images |
| TRUST | entity naming conflict · contact facts contradicting structured data · **structured-data name contradicting the visible H1** · freshness risk · Organization declared without `sameAs` |
| ENGAGEMENT | homepage does not state the offering · page does not identify itself · no navigation region · no next step · interior pages that strand the visitor |

Checks in **bold** are the ones a generic SEO scanner does not perform; they are
the AI-specific mechanisms this audit exists to find.

### Repository layout

```
brand-ai-readiness-audit/
├── marketplace.json          # manifest, exactly one entrypoint
├── README.md
├── requirements.txt
├── aira/                     # the engine the skills wrap
│   ├── config.py             # every bound and threshold, in one place
│   ├── urls.py               # normalization, validation, SSRF guard
│   ├── crawler.py            # bounded read-only crawler, robots, sitemap
│   ├── render.py             # optional headless rendering (measurement only)
│   ├── parsing.py            # HTML → observations (pure functions)
│   ├── importance.py         # important-page detection
│   ├── facts.py              # fact extraction + normalization
│   ├── evidence.py           # the evidence engine
│   ├── audits/               # discoverability · freshness · engagement
│   ├── findings.py           # contract, severity, confidence, priority, dedupe
│   ├── scoring.py            # AI readiness score
│   ├── report.py             # report assembly + schema validation
│   ├── orchestrator.py       # the deterministic composition
│   ├── viewer.py             # optional single-file HTML report
│   └── cli.py
├── skills/                   # SKILL.md + scripts per skill
├── tests/                    # fixtures + pytest suite
└── demo/                     # example report (JSON + HTML)
```

---

## Installation

```bash
python -m venv .venv && source .venv/bin/activate     # Python 3.11+
pip install -r requirements.txt
python -m playwright install chromium                 # optional, see below
```

**Playwright is optional.** It powers the raw-HTML versus rendered-DOM
comparison. Without it the audit runs normally and the rendering-dependent
checks report as *not applicable* (recorded in `site_context.notes`) rather than
guessing.

---

## Usage

Full audit through the entrypoint skill:

```bash
python skills/audit-orchestrator/scripts/run_audit.py https://example.com \
    -o report.json --summary
```

Equivalently, via the module:

```bash
python -m aira.cli https://example.com -o report.json --summary
```

Useful flags: `--max-pages`, `--max-depth`, `--concurrency`, `--timeout`,
`--no-render`, `--max-rendered`, `--include-evidence`.

Stage by stage (re-analyse without re-crawling):

```bash
python skills/crawl-render-audit/scripts/collect_evidence.py https://example.com -o evidence.json
python skills/discoverability-audit/scripts/analyze_discoverability.py evidence.json -o d.json
python skills/freshness-corroboration/scripts/analyze_freshness.py evidence.json -o f.json
python skills/engagement-audit/scripts/analyze_engagement.py evidence.json -o e.json
python skills/audit-orchestrator/scripts/compose_report.py --evidence evidence.json --findings d.json f.json e.json -o report.json
```

Validate the marketplace itself (offline, no network):

```bash
python skills/audit-orchestrator/scripts/validate_marketplace.py
```

Optional HTML view of a report:

```bash
python skills/audit-orchestrator/scripts/render_report.py report.json -o report.html
```

### Example input

```
https://example.com
```

### Example output (abridged)

```json
{
  "site": "example.com",
  "audited_at": "2026-09-05T06:12:44+00:00",
  "summary": {
    "total_findings": 7, "critical": 0, "high": 3, "medium": 3, "low": 1,
    "ai_readiness_score": 68, "pages_crawled": 18, "pages_rendered": 8
  },
  "ai_readiness": {
    "overall": 68,
    "dimensions": {
      "Discoverability": 82, "Content Accessibility": 61, "Entity Clarity": 55,
      "Fact Consistency": 88, "Freshness": null, "Engagement": 74
    }
  },
  "findings": [
    {
      "id": "F-001",
      "title": "Substantial page content is absent from the initial HTML and appears only after JavaScript execution",
      "severity": "high",
      "evidence": "On https://example.com/products/laptop the initial HTML contains 320 words of visible text while the rendered DOM contains 1280 (75% of the visible text is added by JavaScript).",
      "suggested_action": {
        "summary": "Serve the primary content of these pages in the initial HTML response.",
        "priority": "high",
        "steps": ["…"]
      },
      "category": "discoverability",
      "journey_stage": "extract",
      "confidence": 0.94,
      "confidence_reason": "deterministic rule on measured values; direct DOM/HTTP observation; consistent across 14/16 pages",
      "priority_score": 0.61,
      "priority_reason": "impact 0.80 (severity high) x reach 0.88 x confidence 0.94 x fixability 0.35",
      "affected_urls": ["…"],
      "technical_details": { "metrics": { "js_dependent_pages": 14, "rendered_pages": 16 } }
    }
  ]
}
```

The four fields the handout requires on every finding — `id`, `title`,
`severity`, `evidence`, `suggested_action` — are always present; everything else
is additive.

## Web Dashboard

The project includes a lightweight local web dashboard for running audits
through a browser.

Start the dashboard:

```bash
python app.py
```

---

## How findings are scored

**Severity** comes from a base level per check (its failure *mechanism*),
adjusted by reach and by whether important pages are affected. `critical` is
reserved for failures that stop retrieval of the site outright (unreachable
site, site-wide robots disallow), so a widespread but non-blocking issue can
never outrank a blocking one.

**Confidence** is built from evidence quality — deterministic rule, direct DOM or
HTTP observation, sample size, consistency across pages, corroborating sources,
presence of conflicting signals — and every finding carries a
`confidence_reason` naming the contributors.

**Priority** is explainable, never arbitrary:

```
priority_score = impact × (0.35 + 0.65 × reach) × confidence × (0.55 + 0.45 × fixability)
```

`impact` from severity, `reach` from the share of relevant pages affected,
`fixability` from how cheap the recommended change typically is. Every finding
carries the arithmetic in `priority_reason`.

**AI Readiness Score** (an implementation enhancement, not a handout
requirement): each dimension starts at 100 and loses
`severity_penalty × (0.4 + 0.6 × reach) × confidence` per finding; the overall
score is the weighted mean of the *applicable* dimensions. A dimension that
could not be judged is reported as `null`, not as 0 or 100.

---

## False-positive control

Precision matters more than finding count. The system deliberately does **not**
report:

- legal versus trading names (`Northwind Instruments Ltd` / `Northwind
  Instruments` / `Northwind`) — names are normalized and abbreviation-matched
  before comparison;
- JavaScript itself — only content that is *missing from the initial HTML* and
  above a measured ratio threshold;
- absent optional features — no products, no blog, no pricing page is not a
  finding, and the check simply does not run;
- an old date as proof of staleness — it is reported as a *potential freshness
  risk* with reduced confidence;
- structured data on pages where it is not applicable;
- navigation-heavy hub pages as "thin content";
- every missing meta description or H1 — these are only raised when they affect a
  meaningful share of the important pages;
- a directory-form redirect as a "redirect chain";
- a same-site cross-canonical — only off-site canonicals and canonicals that fail
  to resolve are reported;
- a missing meta description when the page supplies an `og:description`;
- an absent `sameAs` on a site that never declared an Organization entity;
- a contact or legal page as "thin content" — those are short by design;
- English wording heuristics on a site published in another language.

Every check that can misfire also ships `possible_benign_explanations` in the
report, naming the conditions under which the finding should be dismissed. The
agent layer is required to verify those before presenting the finding — this is
the one place where reasoning, not code, makes the call.

`tests/test_false_positives.py` enforces this: the healthy fixture must produce
**zero** findings, with and without rendering.

---

## Testing

```bash
pytest -q                       # 99 tests
python tests/fixtures/build_fixtures.py   # regenerate the fixture sites
```

Sixteen controlled fixture sites are served from a local HTTP server, each with a
known defect and a known expected finding:

| Fixture | Expected |
|---|---|
| `good_site` | **no findings** (precision control) |
| `benign_variants` | **no findings** — legal vs trading name must not conflict |
| `robots_blocked` | `robots_blocks_site`, critical, discover |
| `js_only` | `js_dependent_content`, extract, with raw/rendered word counts |
| `missing_structured_data` | `missing_organization_identity` + `missing_product_structured_data` |
| `invalid_structured_data` | `invalid_structured_data` with the parser error |
| `stale_content` | `freshness_risk`, medium/low, confidence ≤ 0.85 |
| `entity_ambiguity` | `entity_name_conflict` + `contact_fact_conflict` |
| `poor_navigation` | `weak_navigation` + `important_page_orphaned` |
| `poor_context` | `home_purpose_unclear` + `context_loss_orphan` |
| `multi_problem` | four checks simultaneously, both categories, score < 80 |
| `ai_crawler_blocked` | `ai_crawler_blocked`, high — GPTBot/ClaudeBot/Google-Extended disallowed while `*` is allowed |
| `incomplete_structured_data` | `incomplete_structured_data` + `structured_visible_mismatch` |
| `header_noindex` | `noindex_header_on_important_page` from the X-Robots-Tag response header |
| `stale_sitemap` | `sitemap_broken_urls` + `sitemap_missing_important_pages` |
| `non_english` | **no findings** — a healthy German site (generalization control) |

Tests assert the evidence — the check that fired, the journey stage, the metric
values, the severity band, the presence of mechanism-sound fix steps — not just
that some finding exists.

---

## Safety model

- **Read-only.** GET requests only. No form submission, no authentication, no
  state-changing request, no write of any kind to the audited site.
- **robots.txt is honoured.** A site-wide disallow stops the crawl and is
  reported as the finding.
- **SSRF guard.** Every target and every discovered URL is resolved and refused
  if it maps to a private, loopback, link-local, multicast or reserved address.
  Non-`http(s)` schemes and URLs carrying credentials are refused. The local test
  harness opts in explicitly via `allow_private_networks`.
- **Redirects are followed by hand.** Automatic redirect following would send the
  crawler wherever a server points it, including at a private address — an open
  redirect turns straight into SSRF. Every hop is therefore re-checked against
  the address guard, the robots rules and the same-site rule, with a hop limit
  and loop detection.
- **Bodies are streamed.** Responses are read in chunks and abandoned at the byte
  cap, so an oversized or endless response can never be buffered whole.
- **The browser is sandboxed too.** Downloads are cancelled, non-`http(s)`
  sub-requests are aborted, and the rendering stage has its own wall-clock budget
  so it cannot push the audit past the five-minute requirement.
- **Bounded.** Page count, link depth, response size, concurrency, per-request
  timeout, rendering count, rendering timeout and a total crawl wall-clock
  budget — all in `aira/config.py`.
- **Polite.** A small inter-request delay, a capped connection pool and an
  identifying user agent.
- **No infinite recursion.** URLs are normalized before de-duplication and every
  URL is fetched at most once; redirect chains are recorded, not followed in a
  loop.
- **Fails safe.** Timeouts, TLS errors, malformed HTML, oversized bodies and a
  crashing analysis module are all contained; the audit still returns a valid
  report.

---

## Performance

- Typical audit (20 pages, 8 rendered): well under the 5-minute budget; the
  bundled fixture suite of 11 sites runs end to end in under a minute.
- Package is a few hundred kilobytes — far below the 50 MB limit.
- No pretrained model weights, no model downloads.
- Dependencies: `httpx`, `beautifulsoup4`, `lxml`, and optionally `playwright`.
  No LangChain, LangGraph, CrewAI or any agent framework.
- One browser instance is reused for the whole run; rendering is capped and only
  the highest-importance pages are rendered.

---

## Requirements and implementation choices

### The check that matters most

`robots.txt` is routinely used to allow general search crawling while
disallowing the agents that AI assistants and answer engines actually use
(`GPTBot`, `ClaudeBot`, `Google-Extended`, `PerplexityBot`, `CCBot` and
others). That is the single most direct mechanism by which a brand becomes
invisible to AI applications, and it is invisible to a generic SEO tool, which
only asks "may *I* crawl this?". The audit parses robots.txt into per-user-agent
groups and reports named agents that are blocked — while acknowledging, in the
finding itself, that such a block is often a deliberate content-licensing
decision rather than a defect.

**Requirements:** a single Agent Skill
Marketplace package; `marketplace.json`; one or more Agent Skills; **exactly one**
entrypoint skill; a valid `SKILL.md` per skill; `README.md` at the root; the
report schema (`site`, `audited_at`, `summary` with `total_findings`/`critical`/
`high`/`medium`, and `findings` with `id`, `title`, `severity`, `evidence`,
`suggested_action`); recommend-only and read-only operation; respect for
robots.txt; no destructive, authenticated or rate-abusive behaviour; portable
skills; no external service required to resolve the manifest; ZIP ≤ 50 MB;
typical audit under 5 minutes; no pretrained model weights. The handout also
names the failure modes to look for — crawlability, JavaScript/rendering gaps,
missing or invalid structured data, facts locked in non-text, stale facts,
uncorroborated facts, entity ambiguity — and, for engagement, weak on-site
orientation and lack of context retention.

**Our implementation choices** (not handout requirements): the AI discoverability
journey model; the specific check set and its thresholds; the four-level severity
definitions and the rule that only blocking failures may be `critical`; the
confidence model; the priority formula; the AI Readiness Score and its
dimensions and weights; the importance heuristic and page-role vocabulary; the
name-normalization rules; the evidence-model schema; the additive report fields;
the optional HTML viewer.

The requirements do not specify a complete checklist, so the additional checks
above are implementation choices designed to provide mechanism-sound evidence.

---

## Known limitations

- **Depth is crawl-relative.** "Four hops from the homepage" means four hops
  *within the crawled subset*; a tighter budget can overstate depth. The finding
  states the budget used.
- **Rendering is a sample.** Only the highest-importance pages are rendered
  (default 8), so the JavaScript-dependency ratio is measured on a subset.
- **Registrable-host matching is simplified.** A leading `www.` is stripped; no
  public-suffix list is bundled, so some multi-label ccTLD sites are treated as
  same-site more loosely than a full PSL would.
- **Corroboration is on-site only.** The system compares the site against itself
  and against the profiles it links to. It does not query external registries,
  and it never asserts that a fact is false — only that statements disagree.
- **Freshness is a signal, not a fact.** An undated page is not judged; an old
  date is a risk, not proof.
- **Fact extraction is conservative.** Prices, addresses and opening hours are
  read from structured data and contact-page text; free-prose facts elsewhere are
  not mined, which favours precision over recall.
- **Multilingual coverage is partial.** Page-role slugs cover English plus common
  German, French, Spanish, Italian, Portuguese and Dutch forms; other languages
  fall back to structural signals. Wording-based engagement checks are disabled
  outside English rather than guessing, so a non-English site is audited more
  conservatively.
- **Bot-protected sites.** Sites that block non-browser clients will surface as a
  single access finding rather than a content audit — correctly, since that is
  what an automated retrieval client would also experience.

---

## License

MIT.
