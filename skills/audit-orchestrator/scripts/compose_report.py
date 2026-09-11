#!/usr/bin/env python3
"""Compose a final report from an evidence file and one or more findings files.

    python compose_report.py --evidence evidence.json \
        --findings d.json f.json e.json -o report.json

Use this when the analysis skills were run separately. The composition is
deterministic: normalize -> deduplicate/merge -> priority -> score -> validate.
"""
from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import bootstrap

bootstrap()

from aira.evidence import SiteEvidence  # noqa: E402
from aira.findings import Evidence, Finding, dedupe, finalize  # noqa: E402
from aira.reasoning import ReasoningEngine  # noqa: E402
from aira.report import build_report, validate_report  # noqa: E402
from aira.scoring import compute_score  # noqa: E402


def load_findings(paths: list[str]) -> list[Finding]:
    out: list[Finding] = []
    field_names = set(Finding.__dataclass_fields__.keys())
    for path in paths:
        for item in json.loads(open(path, encoding="utf-8").read()):
            item = dict(item)
            item["evidence"] = Evidence(**item["evidence"])
            filtered = {k: v for k, v in item.items() if k in field_names}
            out.append(Finding(**filtered))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--findings", nargs="+", required=True)
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args(argv)

    evidence = SiteEvidence.from_dict(
        json.loads(open(args.evidence, encoding="utf-8").read()))
    findings = finalize(dedupe(load_findings(args.findings)))
    score = compute_score(findings, evidence)

    strategic_reasoning = None
    try:
        engine = ReasoningEngine()
        findings, strategic_reasoning = engine.process(evidence, findings)
    except Exception as exc:
        print(f"warning: reasoning stage skipped ({exc})", file=sys.stderr)

    report = build_report(evidence, findings, score, strategic_reasoning=strategic_reasoning)
    problems = validate_report(report)
    if problems:
        print("report failed schema validation: " + "; ".join(problems),
              file=sys.stderr)
        return 1
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output == "-":
        print(payload)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"report -> {args.output} ({len(findings)} finding(s))", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
