#!/usr/bin/env python3
"""Crawl a site read-only and write the structured evidence model as JSON.

    python collect_evidence.py https://example.com -o evidence.json

The output is the contract every audit skill consumes. Nothing here interprets
the data; it only measures it.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from _bootstrap import bootstrap

bootstrap()

from aira.config import AuditConfig  # noqa: E402

# slots dataclasses do not expose defaults as class attributes
_DEFAULTS = AuditConfig()
from aira.crawler import crawl_site  # noqa: E402
from aira.evidence import build_evidence  # noqa: E402
from aira.urls import UnsafeUrlError, validate_target  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url")
    ap.add_argument("-o", "--output", default="-")
    ap.add_argument("--max-pages", type=int, default=_DEFAULTS.max_pages)
    ap.add_argument("--max-depth", type=int, default=_DEFAULTS.max_depth)
    ap.add_argument("--concurrency", type=int, default=_DEFAULTS.concurrency)
    ap.add_argument("--timeout", type=float, default=_DEFAULTS.request_timeout)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--max-rendered", type=int, default=_DEFAULTS.max_rendered_pages)
    ap.add_argument("--allow-private", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    cfg = AuditConfig(
        max_pages=args.max_pages, max_depth=args.max_depth,
        concurrency=args.concurrency, request_timeout=args.timeout,
        render=not args.no_render, max_rendered_pages=args.max_rendered,
        allow_private_networks=args.allow_private,
    )
    try:
        target = validate_target(args.url, cfg)
    except UnsafeUrlError as exc:
        print(f"refusing to crawl: {exc}", file=sys.stderr)
        return 2
    evidence = build_evidence(crawl_site(target, cfg), cfg)
    payload = json.dumps(evidence.to_dict(), indent=2, ensure_ascii=False)
    if args.output == "-":
        print(payload)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"evidence for {target.url}: {len(evidence.pages)} page(s) -> "
              f"{args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
