---
name: discoverability-audit
description: Analyses a site evidence model for AI discoverability problems across the discover, access, understand, extract and represent stages - robots and HTTP failures, sitemap gaps, pages that are deep or unlinked, noindex directives, content that exists only after JavaScript rendering, thin or image-only content, missing or invalid structured data, missing Organization identity and canonical conflicts. Use after crawl-render-audit has produced an evidence file.
---

# Discoverability Audit

Interprets measured evidence against the AI discoverability journey:

`DISCOVER -> ACCESS -> UNDERSTAND -> EXTRACT -> TRUST -> REPRESENT`

Each finding names the stage that broke.

## Inputs

An evidence JSON file produced by `crawl-render-audit`.

## Output

A JSON list of findings using the internal finding contract: `check_id`,
`category`, `journey_stage`, `title`, `severity`, `confidence`,
`confidence_reason`, `evidence` (`url`, `observation`, `details`, `metrics`,
`affected_urls`), `impact`, `suggested_action` (`summary`, `steps`), `reach`,
`dimension`.

## Instructions

```bash
python skills/discoverability-audit/scripts/analyze_discoverability.py \
    evidence.json -o discoverability_findings.json
```

## Checks and what each one measures

| Stage | Check | Measured from |
|---|---|---|
| discover | site unreachable, site-wide robots disallow, important page disallowed, HTTP errors, missing sitemap, redirect chains | HTTP status, robots.txt rules, sitemap responses, redirect history |
| access | noindex on important pages, JavaScript-dependent content, important pages 3+ hops deep, important pages with no inbound internal links | meta robots, raw-vs-rendered word counts, crawl depth, link graph |
| understand | thin important pages, missing H1, missing meta description, canonical pointing elsewhere | visible word counts, heading and meta presence |
| extract | invalid JSON-LD, missing Organization/WebSite identity, product pages without Product schema, information carried only in images | JSON parse results, schema types per page, image/alt/word ratios |
| trust / represent | no external profile links to corroborate identity | `sameAs` values and outbound profile links |

## Constraints

- A check runs only when its precondition is observable. Sites with no products,
  no blog and no structured data requirement produce no findings for those checks.
- Missing optional information is not a problem in itself.
- Reported severity comes from the deterministic severity table; do not restate it.
- Reach (share of relevant pages affected) is always recorded so the orchestrator
  can compute priority.

## Agent reasoning

Report the stage that broke and the measurement that proves it. Where a check can misfire, populate `benign_explanations` so the orchestrator's agent layer can verify the finding before presenting it.

## Evidence expectations

Observations must contain the measured value:
"0 of 18 crawled pages contain applicable Organization/WebSite structured data",
"raw 320 words -> rendered 1280 words (75% added by JavaScript)".
Statements such as "the site has poor discoverability" are not acceptable.

## Failure handling

A missing field in the evidence model means "not observed" and the check is
skipped, never guessed.
