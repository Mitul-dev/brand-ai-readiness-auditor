---
name: audit-orchestrator
description: Entrypoint skill. Audits a website URL for AI discoverability and on-site engagement problems by running the crawl, evidence, discoverability, freshness and engagement skills, then composing one evidence-backed audit report with severity, confidence, suggested fixes and priority. Use when the user gives a website URL or domain and asks for an audit, an AI-readiness check, or why a brand may be invisible, stale, misrepresented or poorly experienced in AI applications.
---

# Audit Orchestrator

The single entrypoint of the `brand-ai-readiness-audit` marketplace. It receives a
website URL and returns one structured audit report.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `url` | yes | Website URL or bare domain. `https://` is assumed if no scheme is given. |
| `max_pages` | no | Crawl budget, default 20. |
| `max_depth` | no | Link depth, default 3. |
| `render` | no | Headless rendering for the raw-vs-rendered comparison, default on. |

## Output

A JSON report containing at least `site`, `audited_at`, `summary`
(`total_findings`, `critical`, `high`, `medium`) and `findings`, where each
finding has `id`, `title`, `severity`, `evidence` and `suggested_action`.
Additional fields (`category`, `journey_stage`, `confidence`,
`confidence_reason`, `impact`, `priority_score`, `affected_urls`,
`technical_details`, `ai_readiness`) are added on top and never replace the
required ones.

## Instructions

1. Validate the URL. Refuse anything that is not `http`/`https`, carries
   credentials, or resolves to a private, loopback or link-local address.
2. Run the whole pipeline in one command:

   ```bash
   python skills/audit-orchestrator/scripts/run_audit.py <url> -o report.json --summary
   ```

   This calls `crawl-render-audit` for evidence, then `discoverability-audit`,
   `freshness-corroboration` and `engagement-audit`, then normalizes,
   deduplicates and scores their findings.
3. To run the stages separately (for debugging, or to re-analyse without
   re-crawling), use `compose_report.py`:

   ```bash
   python skills/crawl-render-audit/scripts/collect_evidence.py <url> -o evidence.json
   python skills/discoverability-audit/scripts/analyze_discoverability.py evidence.json -o d.json
   python skills/freshness-corroboration/scripts/analyze_freshness.py evidence.json -o f.json
   python skills/engagement-audit/scripts/analyze_engagement.py evidence.json -o e.json
   python skills/audit-orchestrator/scripts/compose_report.py --evidence evidence.json --findings d.json f.json e.json -o report.json
   ```
4. Validate the marketplace itself with
   `python skills/audit-orchestrator/scripts/validate_marketplace.py` (offline).
5. Present the report: lead with the AI readiness score and its dimensions, then
   the findings in priority order. For each finding state what was observed,
   where, how it was measured, why it matters and what to change.

## Agent reasoning: what you decide, and what you must not

The pipeline decides *whether* a finding is raised and *how severe* it is. Your
job is the layer the code cannot do:

1. **Verify before presenting.** Every finding carries
   `possible_benign_explanations` - the conditions under which it would be a
   false positive. Check each one against the evidence and the site's apparent
   purpose. If a benign explanation clearly holds, present the finding as
   "confirm this is intentional" rather than as a defect, and say why.
2. **Contextualise.** Explain what the measurement means for *this* kind of site.
   Missing Product structured data matters differently to a shop and to a
   consultancy.
3. **Sequence.** Findings arrive in priority order, but some fixes unblock
   others (allowing an AI crawler before improving the content it will read).
   Say so.
4. **Stay inside the evidence.** Do not invent findings, do not restate a number
   the evidence does not contain, and do not overwrite `severity`, `confidence`
   or `priority` - they are computed, reproducible and auditable.

## Constraints

- Read-only. GET requests only; never submit a form, authenticate, or send data.
- `robots.txt` is honoured. A site-wide disallow ends the crawl and is itself
  reported as the finding.
- Crawling is bounded by page count, depth, per-request timeout, concurrency and
  a total wall-clock budget.
- Severity, confidence and priority are computed by code from measured values.
  Do not overwrite them with your own numbers.
- Never state a finding the report does not contain, and never restate a number
  the evidence does not carry.

## Evidence expectations

Every finding already carries `technical_details.metrics`. When explaining a
finding, quote those numbers (`0 of 18 pages`, `raw 12 words -> rendered 210
words`) rather than paraphrasing them as "poor" or "weak".

## Failure handling

- Unreachable host: a `critical` finding is returned; the report is still valid.
- Rendering unavailable (no browser binary): rendering-dependent checks are
  skipped and noted in `site_context.notes`; they are not reported as problems.
- A crashing analysis module is skipped, noted, and the remaining modules still
  produce a report.
