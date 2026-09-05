# Demo

`example_report.json` and `example_report.html` are the output of auditing the
`multi_problem` test fixture, which contains several deliberate defects at once.

Regenerate them from any audit:

```bash
python -m aira.cli https://example.com -o report.json
python skills/audit-orchestrator/scripts/render_report.py report.json -o report.html
```

The HTML viewer is a single self-contained file: no build step, no external
assets, no network calls. Click a finding to expand its problem, evidence,
metrics, impact, recommended fix, priority and confidence.
