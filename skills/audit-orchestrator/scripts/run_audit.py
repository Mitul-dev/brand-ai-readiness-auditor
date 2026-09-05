#!/usr/bin/env python3
"""Entrypoint script: run the complete audit and emit the final report.

    python run_audit.py https://example.com -o report.json --summary

Composes the crawl/evidence stage and the three analysis modules, normalizes and
deduplicates their findings, computes severity, confidence, priority and the AI
readiness score, then validates the report against the required schema.
"""
from __future__ import annotations

import sys

from _bootstrap import bootstrap

bootstrap()

from aira.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
