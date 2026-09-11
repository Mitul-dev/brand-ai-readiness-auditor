---
name: reasoning
description: Interprets and synthesizes deterministic audit evidence and findings. Produces grounded root-cause analysis, explains autonomous AI agent impact, maps cross-finding dependencies, and constructs a prioritized 3-phase strategic remediation roadmap without altering deterministic scores or severities.
---

# Agent Reasoning Skill

Translates objective crawl evidence into grounded explanations, root cause analysis, AI agent impacts, and a phased strategic remediation roadmap.

Aligns with the core architecture:
`DETERMINISTIC DATA COLLECTION -> OBJECTIVE EVIDENCE -> AGENT REASONING -> FINDING -> RECOMMENDATION`

## Inputs

1. An evidence JSON file produced by `crawl-render-audit`.
2. A findings JSON file containing findings from `discoverability-audit`, `engagement-audit`, and `freshness-corroboration`.

## Output

A JSON array of enriched findings containing additive reasoning fields:
- `root_cause_analysis`: Mechanical diagnosis grounded in measured crawl metrics.
- `ai_agent_impact`: Explanation of how autonomous AI systems and search copilots fail.
- `remediation_phase`: Recommended phase in the 3-phase roadmap.
- `estimated_effort`: Engineering effort estimation (`low`, `medium`, `high`).
- `cross_finding_dependencies`: Correlated findings sharing underlying root causes.

Optionally, an executive strategy JSON file containing:
- `executive_summary`: Cross-cutting analysis of site readiness.
- `primary_bottleneck_stage`: Stage with greatest friction in the AI discoverability journey.
- `strategic_themes`: Architectural patterns diagnosed across findings.
- `remediation_roadmap`: Phased 30/60-day action plan.

## Instructions

```bash
python skills/reasoning/scripts/reason_about_findings.py \
    --evidence evidence.json \
    --findings findings.json \
    -o enriched_findings.json \
    --strategy-output roadmap.json
```

## Constraints

- Operates strictly downstream of deterministic evidence collection and scoring.
- Never mutates or overrides deterministic scores, confidence levels, or severity rankings.
- All cited URLs, metrics, and facts must be grounded in the provided `evidence.json`. No external site pages or hallucinated statistics are permitted.
- Operates out of the box with zero required API keys using the deterministic reasoning provider.

## Failure handling

If a reasoning provider (such as an optional LLM endpoint) fails, times out, or returns ungrounded facts, the system automatically falls back to deterministic heuristic reasoning without disrupting the audit pipeline.
