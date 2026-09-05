"""Optional read-only integration test against one accessible public website.

Skipped by default so the suite stays hermetic and offline. Enable with:

    AIRA_INTEGRATION=1 AIRA_INTEGRATION_URL=https://pypi.org pytest tests/test_integration_public.py -q

The project must never depend on the specific site used here.
"""
from __future__ import annotations

import os
import time

import pytest

from conftest import make_config

from aira.orchestrator import run_audit
from aira.report import assert_valid

pytestmark = pytest.mark.skipif(
    os.environ.get("AIRA_INTEGRATION") != "1",
    reason="set AIRA_INTEGRATION=1 to run the public-site integration test",
)

TARGET = os.environ.get("AIRA_INTEGRATION_URL", "https://pypi.org")


def test_public_site_audit_is_valid_and_bounded():
    started = time.perf_counter()
    report = run_audit(TARGET, make_config(
        allow_private_networks=False, max_pages=15, max_depth=2,
        render=True, max_rendered_pages=4, delay_between_requests_s=0.2))
    runtime = time.perf_counter() - started

    assert_valid(report)
    assert runtime < 300, "a typical audit must finish well inside five minutes"
    assert report["summary"]["pages_crawled"] >= 3, "the crawler should reach real pages"
    assert report["site_context"]["home_status"] == 200

    for f in report["findings"]:
        assert f["technical_details"]["metrics"], f"{f['id']} lacks metrics"
        assert any(ch.isdigit() for ch in f["evidence"]), \
            f"{f['id']} evidence must quote a measured value"
        for url in f["affected_urls"]:
            assert url.startswith("http")

    score = report["ai_readiness"]["overall"]
    assert 0 <= score <= 100
