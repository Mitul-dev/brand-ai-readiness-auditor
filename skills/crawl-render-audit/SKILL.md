---
name: crawl-render-audit
description: Safely crawls a website read-only and converts it into a compact structured evidence model - HTTP status, redirects, robots.txt, sitemap, headings, metadata, canonical URLs, internal and external links, JSON-LD and microdata, raw-HTML versus rendered-DOM comparison, page importance and extracted business facts. Use when a website URL must be measured before any audit reasoning happens.
---

# Crawl and Render Audit

Deterministic data acquisition. This skill measures; it never judges.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `url` | yes | Website URL or bare domain. |
| `--max-pages` | no | Default 20. |
| `--max-depth` | no | Default 3. |
| `--concurrency` | no | Default 4. |
| `--timeout` | no | Per-request seconds, default 12. |
| `--no-render` | no | Skip headless rendering. |
| `--max-rendered` | no | Rendering budget, default 8 pages. |

## Output

An evidence JSON document:

```json
{
  "site": "example.com",
  "site_level": { "robots_present": true, "sitemap_present": true, "counts": {} },
  "facts_by_kind": { "organization_name": [], "phone": [], "email": [], "social": [] },
  "pages": [
    {
      "url": "/products/laptop",
      "role": "products",
      "importance": 0.78,
      "status": 200, "robots_allowed": true, "redirect_count": 0,
      "depth": 2, "incoming_internal_links": 3, "outgoing_internal_links": 14,
      "title": "...", "h1": ["..."], "word_count": 842,
      "jsonld_types": ["Product"], "jsonld_invalid": [],
      "rendering": { "raw_words": 320, "rendered_words": 1280,
                     "added_word_ratio": 0.75, "js_dependent": true },
      "dates_found": ["2026-02-14"], "facts": []
    }
  ]
}
```

## Instructions

```bash
python skills/crawl-render-audit/scripts/collect_evidence.py <url> -o evidence.json
```

Pass the resulting file to the analysis skills. Do not re-crawl a site that
already has an evidence file for the current run.

## Constraints

- GET only. No form submission, no authentication, no state-changing request.
- `robots.txt` is fetched first and every URL is checked against it.
- Requests to private, loopback, link-local, multicast or reserved addresses are
  refused unless the caller explicitly opts in for local test fixtures.
- Hard caps: page count, link depth, response size, concurrency, per-request
  timeout and a total crawl wall-clock budget.
- URLs are normalized (scheme, host case, default port, trailing slash, tracking
  parameters) before de-duplication, so the same page is fetched once.
- One browser instance is reused for the whole run and only the highest-value
  pages are rendered.

## Evidence expectations

Record what was observed, including absence: a missing sitemap is
`sitemap_present: false`, not an error. Never invent a value that was not read
from the response.

## Failure handling

Per-page failures (timeout, TLS error, malformed HTML, oversized body) are
recorded on that page as `error` / `truncated` and the crawl continues. A failure
to fetch `robots.txt` is treated as "no restrictions stated" and noted.
