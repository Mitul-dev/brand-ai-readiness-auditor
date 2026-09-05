---
name: engagement-audit
description: Analyses whether a visitor who lands on the site can tell where they are, what is offered and what to do next - homepage orientation, page self-identification, presence of a consistent navigation region, calls to action on key pages, and interior pages that link back to almost nothing. Uses structural evidence rather than visual judgement. Use after crawl-render-audit has produced an evidence file.
---

# Engagement Audit

Scoped to the challenge question - can an arriving visitor orient themselves,
understand the offering, and continue - not to general visual UX.

## Inputs

An evidence JSON file produced by `crawl-render-audit`.

## Output

Findings in the internal finding contract with `category: "engagement"` and the
`engagement` scoring dimension. `journey_stage` is null: the discoverability
journey does not apply to on-site engagement.

## Instructions

```bash
python skills/engagement-audit/scripts/analyze_engagement.py \
    evidence.json -o engagement_findings.json
```

## Checks

| Area | Check | Measured from |
|---|---|---|
| Orientation | homepage does not state what the site is or offers | title text, H1 presence and length, opening body text, meta description |
| Clarity | an important page does not identify itself to a direct arrival | generic or missing title combined with no H1 |
| Navigation | no navigation region on most pages | `nav` landmark or `role="navigation"` presence, homepage internal link count |
| Next step | important page with no call to action and almost no internal links | action wording on links and buttons, outgoing internal link count |
| Context retention | interior page that links back to almost nothing | outgoing internal links versus word count |

At least two independent orientation signals must fail before the homepage
finding is raised, so one stylistic choice alone never triggers it.

## Constraints

- No aesthetic judgements: nothing is reported as "bad UX" without a structural
  measurement behind it.
- Detection is structural, so a visually styled menu that uses neither a `nav`
  landmark nor internal links is still reported - state this in the evidence.
- Small sites (fewer than four pages) are exempt from the navigation and
  context-retention checks.

## Agent reasoning

Wording-based checks are English heuristics and are disabled when the site declares another language; only structural signals are used there. Record that in the finding's metrics so the reader knows what was and was not assessed.

## Evidence expectations

Quote the measurement: "0 of 5 crawled pages contain a `nav` element",
"the page title is 'Home', which does not name the brand or what the site is for".

## Failure handling

If the homepage was not retrieved, the orientation check yields nothing rather
than assuming a problem.
