"""Command-line entrypoint: ``python -m aira.cli <url>``."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import AuditConfig

# slots dataclasses do not expose defaults as class attributes
_DEFAULTS = AuditConfig()
from .orchestrator import AuditError, run_audit


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aira",
        description="Read-only AI discoverability and on-site engagement audit.",
    )
    p.add_argument("url", help="website URL or domain to audit")
    p.add_argument("-o", "--output", help="write the JSON report to this path")
    p.add_argument("--max-pages", type=int, default=_DEFAULTS.max_pages)
    p.add_argument("--max-depth", type=int, default=_DEFAULTS.max_depth)
    p.add_argument("--concurrency", type=int, default=_DEFAULTS.concurrency)
    p.add_argument("--timeout", type=float, default=_DEFAULTS.request_timeout)
    p.add_argument("--no-render", action="store_true",
                   help="skip headless rendering (raw-HTML checks only)")
    p.add_argument("--max-rendered", type=int, default=_DEFAULTS.max_rendered_pages)
    p.add_argument("--ignore-robots", action="store_true",
                   help=argparse.SUPPRESS)  # for auditing a site you own
    p.add_argument("--allow-private", action="store_true",
                   help="permit private/loopback targets (local fixtures only)")
    p.add_argument("--include-evidence", action="store_true",
                   help="embed the full evidence model in the report")
    p.add_argument("--summary", action="store_true",
                   help="print a human-readable summary instead of JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def config_from_args(args: argparse.Namespace) -> AuditConfig:
    return AuditConfig(
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        concurrency=args.concurrency,
        request_timeout=args.timeout,
        render=not args.no_render,
        max_rendered_pages=args.max_rendered,
        respect_robots=not args.ignore_robots,
        allow_private_networks=args.allow_private,
    )


def print_summary(report: dict) -> None:
    s = report["summary"]
    ai = report["ai_readiness"]
    print(f"\nAI READINESS: {ai['overall']}/100   ({report['site']})")
    for label, value in ai["dimensions"].items():
        shown = "n/a" if value is None else f"{value:>3}"
        print(f"  {label:<24}{shown}")
    print(f"\nFindings: {s['total_findings']}  "
          f"(critical {s['critical']}, high {s['high']}, "
          f"medium {s['medium']}, low {s.get('low', 0)})")
    print(f"Pages crawled: {s['pages_crawled']}  rendered: {s['pages_rendered']}  "
          f"runtime: {s['runtime_seconds']}s\n")
    for f in report["findings"]:
        print(f"[{f['severity'].upper():<8}] {f['id']}  {f['title']}")
        print(f"           stage={f['journey_stage'] or '-'}  "
              f"priority={f['suggested_action']['priority']}  "
              f"confidence={f['confidence']}")
        print(f"           evidence: {f['evidence'][:200]}")
        print(f"           fix: {f['suggested_action']['summary']}\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        report = run_audit(args.url, config_from_args(args),
                           include_evidence_model=args.include_evidence)
    except AuditError as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"report written to {args.output}", file=sys.stderr)
    if args.summary:
        print_summary(report)
    elif not args.output:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
