#!/usr/bin/env python3
"""Reason about audit findings and evidence to produce grounded enrichments and a strategic roadmap.

Usage:
    python skills/reasoning/scripts/reason_about_findings.py \
        --evidence evidence.json --findings findings.json -o enriched_findings.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from aira.evidence import SiteEvidence  # noqa: E402
from aira.findings import Evidence, Finding  # noqa: E402
from aira.reasoning import ReasoningEngine  # noqa: E402


def load_findings(path: str) -> list[Finding]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    findings: list[Finding] = []
    for item in raw:
        data = dict(item)
        data["evidence"] = Evidence(**data["evidence"])
        # Only pass recognized fields to Finding
        field_names = set(Finding.__dataclass_fields__.keys())
        filtered_data = {k: v for k, v in data.items() if k in field_names}
        findings.append(Finding(**filtered_data))
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", required=True, help="Path to SiteEvidence JSON")
    ap.add_argument("--findings", required=True, help="Path to findings JSON")
    ap.add_argument("-o", "--output", default="-", help="Output path for enriched findings")
    ap.add_argument("--strategy-output", help="Optional path to output strategic roadmap JSON")
    args = ap.parse_args(argv)

    evidence = SiteEvidence.from_dict(
        json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    )
    findings = load_findings(args.findings)

    engine = ReasoningEngine()
    enriched_findings, strategy = engine.process(evidence, findings)

    findings_payload = [f.to_dict() for f in enriched_findings]
    # Include additive reasoning fields in dictionary
    for orig, f_dict in zip(enriched_findings, findings_payload):
        f_dict["reasoning"] = orig.reasoning
        f_dict["enhanced_by_reasoning"] = orig.enhanced_by_reasoning

    out_text = json.dumps(findings_payload, indent=2, ensure_ascii=False)
    if args.output == "-":
        print(out_text)
    else:
        Path(args.output).write_text(out_text, encoding="utf-8")
        print(f"Enriched {len(enriched_findings)} findings -> {args.output}", file=sys.stderr)

    if args.strategy_output:
        strategy_text = json.dumps(strategy, indent=2, ensure_ascii=False)
        Path(args.strategy_output).write_text(strategy_text, encoding="utf-8")
        print(f"Strategic roadmap -> {args.strategy_output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
