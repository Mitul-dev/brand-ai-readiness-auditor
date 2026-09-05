#!/usr/bin/env python3
"""Detect AI discoverability failures in a site evidence model.

    python analyze_discoverability.py evidence.json -o findings.json
"""
from __future__ import annotations

import sys

from _bootstrap import bootstrap

bootstrap()

from aira.analysis_cli import run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run("discoverability", sys.argv[1:]))
