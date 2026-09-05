#!/usr/bin/env python3
"""Render a JSON report as a single self-contained HTML page (optional demo).

    python render_report.py report.json -o report.html
"""
from __future__ import annotations

import argparse
import json

from _bootstrap import bootstrap

ROOT = bootstrap()

from aira.viewer import render_html  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report")
    ap.add_argument("-o", "--output", default="report.html")
    args = ap.parse_args(argv)
    report = json.loads(open(args.report, encoding="utf-8").read())
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(render_html(report))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
