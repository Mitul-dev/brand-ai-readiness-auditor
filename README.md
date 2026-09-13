<div align="center">

# 🔍 brand-ai-readiness-audit

**An Agent Skill Marketplace that audits any website for AI discoverability and on-site engagement — evidence-backed, deterministic, and read-only.**

*Adobe University Hackathon 2026 — Round 3: Agent Skill Marketplace*

![Tests](https://img.shields.io/badge/tests-198%2F198%20passing-brightgreen?style=flat-square)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)
![Spec](https://img.shields.io/badge/spec-agentskills.io-blueviolet?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-informational?style=flat-square)

</div>

---

## What this is

Pointed at a website URL, this marketplace returns one structured JSON audit report covering two failure surfaces: why a brand is missing, ignored or misquoted by AI assistants (**discoverability**), and why visitors who arrive don't stay (**engagement**). Every finding is evidence-backed — a number actually measured from the site, not a guess — with severity, confidence, and a prioritized fix.

```
Stage:    EXTRACT
Problem:  Substantial page content is absent from the initial HTML.
Evidence: Initial HTML contains 12 words; rendered DOM contains 210
          (94% added by JavaScript).
Impact:   Non-rendering clients see a fraction of the page — facts may
          never be extracted.
```

Code measures, the agent explains: severity, confidence, priority and the AI Readiness Score are all computed by deterministic functions over measured inputs — no LLM determines those numbers.

---

##  Architecture

```
                  ┌─────────────────────────┐
                  │ audit-orchestrator      │  ← the ONE entrypoint
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ 1. DATA COLLECTION      │  safe bounded crawl + rendering
                  │    crawl-render-audit   │
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ 2. OBJECTIVE EVIDENCE   │  compact, measured, JSON
                  │    pages · links · DOM  │
                  │    facts · render ratio │
                  └───────────┬─────────────┘
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
   discoverability-   freshness-        engagement-
       audit          corroboration        audit
             └────────────────┼────────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ 3. AGENT REASONING      │  skills/reasoning
                  │    root causes · impact │  cross-finding synthesis
                  │    phased roadmap       │
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ 4. FINDINGS             │  dedupe · severity · confidence
                  │                         │  reach · priority · grounded
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ 5. RECOMMENDATIONS      │  final report · actionable fixes
                  │    AI Readiness Score   │  phased implementation roadmap
                  └─────────────────────────┘
```


audit-orchestrator is the **only** entrypoint. It is the sole skill that receives the audit request and the sole one that emits the final report; every other skill is a pure function it calls and composes.

---

## Skills

| Skill | Entrypoint | What it does |
|---|---|---|
| audit-orchestrator | **yes** | Validates the URL, runs the full pipeline, dedupes findings, computes priority + readiness score, coordinates reasoning, validates the report schema. |
| crawl-render-audit | no | Safe read-only crawl + evidence engine (raw HTML vs. rendered DOM, robots.txt, sitemap, structured data). Measures only. |
| discoverability-audit | no | Discover / access / understand / extract / represent checks — why AI assistants can't find or trust the site. |
| freshness-corroboration | no | Entity naming consistency, contact-fact consistency, freshness risk. |
| engagement-audit | no | Orientation, page identity, navigation, next step, context retention. |
| reasoning | no | Cross-finding root-cause synthesis, AI-agent impact, phased remediation roadmap. |

By default, only crawl-render-audit accesses the audited website by default; the rest operate as pure functions over its evidence file, so each is independently testable and replaceable. Optional LLM reasoning can call a configured external LLM endpoint.

## What it detects

| Category | Example checks |
|---|---|
| Discoverability | site/page unreachable · robots.txt blocks · **named AI crawlers (GPTBot, ClaudeBot...) disallowed** · JS-dependent content · broken/missing sitemap |
| Content quality | missing H1 · thin pages · invalid or incomplete JSON-LD · facts locked in images |
| Trust | entity name conflicts · structured data vs. visible content mismatch · missing sameAs · freshness risk |
| Engagement | unclear homepage purpose · no navigation · no next step · orphaned pages |

Bold items are AI-specific mechanisms that go beyond a conventional SEO-only audit.

---

### Repository layout

```
brand-ai-readiness-audit/
├── marketplace.json          # manifest, exactly one entrypoint
├── README.md
├── requirements.txt
├── aira/                     # the engine the skills wrap
│   ├── config.py             # every bound and threshold, in one place
│   ├── urls.py                # normalization, validation, SSRF guard
│   ├── crawler.py             # bounded read-only crawler, robots, sitemap
│   ├── render.py              # optional headless rendering (measurement only)
│   ├── parsing.py             # HTML → observations (pure functions)
│   ├── importance.py          # important-page detection
│   ├── facts.py                # fact extraction + normalization
│   ├── evidence.py             # the evidence engine
│   ├── audits/                 # discoverability · freshness · engagement
│   ├── findings.py              # contract, severity, confidence, priority, dedupe
│   ├── scoring.py                # AI readiness score
│   ├── report.py                 # report assembly + schema validation
│   ├── orchestrator.py           # the deterministic composition
│   ├── viewer.py                  # optional single-file HTML report
│   └── cli.py
├── skills/                    # SKILL.md + scripts per skill
├── tests/                     # fixtures + pytest suite
└── demo/                      # example report (JSON + HTML)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Python 3.11+
pip install -r requirements.txt
python -m playwright install chromium               # optional — Playwright itself
                                                     # is a required dependency; this
                                                     # installs the browser for rendering
```

## Usage

```bash
python skills/audit-orchestrator/scripts/run_audit.py https://example.com -o report.json --summary
```

Validate the marketplace itself: `python skills/audit-orchestrator/scripts/validate_marketplace.py`

### Report shape (required fields always present; rest is additive)

```json
{
  "site": "example.com",
  "audited_at": "2026-09-05T06:12:44+00:00",
  "summary": { "total_findings": 7, "critical": 0, "high": 3, "medium": 3, "low": 1 },
  "findings": [{
    "id": "F-001", "severity": "high",
    "title": "Substantial page content is absent from the initial HTML...",
    "evidence": "...75% of visible text is added by JavaScript.",
    "suggested_action": { "summary": "Serve primary content in the initial HTML.", "priority": "high" }
  }]
}
```

`id`, `title`, `severity`, `evidence`, `suggested_action` are the four handout-required fields on every finding.

---

## Scoring & false-positive control

Severity is set per check mechanism (critical only for failures that block retrieval outright); confidence reflects evidence quality; priority combines impact × reach × confidence × fixability. Precision is prioritized over finding count — the system deliberately does **not** flag: legal-vs-trading name variants, JS usage itself (only missing-content ratio), absent optional features, an old date as proof of staleness, or declined cross-domain redirects as outages. `tests/test_false_positives.py` requires the healthy fixture to produce **zero** findings.

## Testing

```bash
pytest -q     # 198 tests covering controlled fixtures for known defects,
              # false positives, and generalization
```

## Safety

Read-only (GET/HEAD only, no auth, no writes) · respects robots.txt · SSRF guard on every URL · bounded page count/depth/timeouts · fails safe on errors — always returns a valid report.

## Known limitations

Rendering is sampled (highest-importance pages only, not exhaustive); corroboration is on-site only, not cross-referenced against external registries; multilingual coverage is partial (English heuristics disabled elsewhere); bot-protected sites surface as a single access finding rather than a full audit.

---

## License

MIT.
