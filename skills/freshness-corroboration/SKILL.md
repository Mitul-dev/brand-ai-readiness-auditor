---
name: freshness-corroboration
description: Checks whether the facts a site states about itself agree with each other and whether anything signals recency - organization and brand naming across JSON-LD, titles, footers and Open Graph, contact details in structured data versus visible pages, and publication or modification dates. Reports contradictions and freshness risk without claiming a fact is false. Use after crawl-render-audit has produced an evidence file.
---

# Freshness and Corroboration

Answers two questions from measured evidence: *does the site contradict itself*,
and *does anything indicate the information is current*.

## Inputs

An evidence JSON file produced by `crawl-render-audit`.

## Output

Findings in the internal finding contract, in the `entity_clarity`,
`fact_consistency` and `freshness` scoring dimensions.

## Instructions

```bash
python skills/freshness-corroboration/scripts/analyze_freshness.py \
    evidence.json -o freshness_findings.json
```

## Checks

1. **Entity naming consistency.** Organization names collected from JSON-LD
   (`name`, `legalName`), `og:site_name`, page-title suffixes and footer
   copyright lines are normalized and clustered. More than one cluster is a
   naming conflict.
2. **Contact fact consistency.** A phone number or email address declared in
   structured data that appears nowhere on the visible pages is a contradiction
   between the machine-readable and human-readable versions of the same fact.
3. **Freshness risk.** Dates from `time` elements, article metadata and JSON-LD
   `datePublished` / `dateModified`. Reported only as a *risk*.

## Constraints - false-positive control

Normalize before comparing. Do not report:

- legal form differences (`Ltd`, `Pvt Ltd`, `Inc`, `GmbH`);
- an abbreviation or prefix of the same name (`Northwind Tech` vs
  `Northwind Technologies`);
- punctuation, casing or ampersand differences;
- a single weak observation, such as one page-title suffix, as an identity conflict;
- several contact methods that legitimately coexist (sales, support, regional);
- an old date on its own as proof that content is out of date.

Language must match the strength of the evidence: "potential freshness risk",
not "this content is stale". Confidence is reduced when the evidence is indirect.

## Agent reasoning

Never claim a fact is false - only that statements disagree. Populate `benign_explanations` (multi-brand sites, departmental contact details, deliberately undated reference content) so the finding can be dismissed on informed grounds.

## Evidence expectations

Show the variants and their sources side by side, for example:
`'Northwind Instruments' (jsonld); 'Vertex Labs UK' (footer)`, together with the
similarity threshold used.

## Failure handling

Fewer than two observations of a fact means there is nothing to compare and the
check yields nothing. Fewer than three dated pages means freshness is not
assessed and the dimension is reported as not applicable.
