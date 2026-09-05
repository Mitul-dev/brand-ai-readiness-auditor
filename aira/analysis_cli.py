"""Shared entry logic for the three analysis skills.

Each analysis skill owns a small script that names its own module and its own
output; they share this runner rather than each shipping a copy of the same file.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable

from .audits import discoverability, engagement, freshness
from .config import AuditConfig
from .evidence import SiteEvidence
from .findings import Finding

MODULES: dict[str, Callable[[SiteEvidence, AuditConfig], list[Finding]]] = {
    "discoverability": discoverability.audit,
    "freshness": freshness.audit,
    "engagement": engagement.audit,
}

ID_PREFIX = {"discoverability": "D", "freshness": "T", "engagement": "E"}


def run(module: str, argv: list[str] | None = None) -> int:
    """Run one analysis module over a saved evidence file."""
    ap = argparse.ArgumentParser(
        prog=f"{module}-audit",
        description=f"Run the {module} analysis over an evidence JSON file.")
    ap.add_argument("evidence", help="evidence JSON path, or '-' for stdin")
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args(argv)

    raw = sys.stdin.read() if args.evidence == "-" else \
        open(args.evidence, encoding="utf-8").read()
    try:
        evidence = SiteEvidence.from_dict(json.loads(raw))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"not a valid evidence file: {exc}", file=sys.stderr)
        return 2

    findings = MODULES[module](evidence, AuditConfig())
    for i, f in enumerate(findings, start=1):
        f.id = f"{ID_PREFIX[module]}-{i:03d}"
    payload = json.dumps([f.to_dict() for f in findings], indent=2,
                         ensure_ascii=False)
    if args.output == "-":
        print(payload)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"{module}: {len(findings)} finding(s) -> {args.output}",
              file=sys.stderr)
    return 0
