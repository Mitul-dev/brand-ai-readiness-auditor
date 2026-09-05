"""Test harness: serves each fixture site from a local threaded HTTP server."""
from __future__ import annotations

import functools
import http.server
import socket
import sys
import threading
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"

from aira.config import AuditConfig  # noqa: E402
from aira.orchestrator import run_audit_with_evidence  # noqa: E402


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static handler that substitutes the live host into fixture files.

    A fixture may also ship a ``_headers.json`` mapping request paths to extra
    response headers, so header-level behaviour (X-Robots-Tag, for example) can
    be exercised without a real server.
    """

    def end_headers(self) -> None:
        extra = self._extra_headers()
        for key, value in extra.items():
            self.send_header(key, value)
        super().end_headers()

    def _extra_headers(self) -> dict:
        import json as _json
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        cfg = Path(self.directory) / "_headers.json"
        if not cfg.exists():
            return {}
        try:
            return _json.loads(cfg.read_text(encoding="utf-8")).get(path, {})
        except Exception:
            return {}

    def log_message(self, *args) -> None:  # silence the test output
        pass

    def _host(self) -> str:
        return self.headers.get("Host", "localhost")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/robots.txt", "/sitemap.xml"):
            file = Path(self.directory) / path.lstrip("/")
            if not file.exists():
                self.send_error(404)
                return
            body = file.read_text(encoding="utf-8").replace("SITEHOST", self._host())
            data = body.encode("utf-8")
            ctype = "text/plain" if path.endswith(".txt") else "application/xml"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()


class FixtureServer:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        handler = functools.partial(_Handler, directory=str(directory))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


def make_config(**overrides) -> AuditConfig:
    base = dict(
        max_pages=15, max_depth=4, concurrency=4, request_timeout=8.0,
        delay_between_requests_s=0.0, allow_private_networks=True,
        render=False, total_crawl_budget_s=60.0,
    )
    base.update(overrides)
    return AuditConfig(**base)


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    if not (FIXTURES / "good_site" / "index.html").exists():
        import subprocess
        subprocess.run([sys.executable, str(FIXTURES / "build_fixtures.py")],
                       check=True)
    return FIXTURES


@pytest.fixture
def serve(fixtures_root):
    """Return a callable: serve(<fixture name>) -> base URL (server auto-closed)."""
    servers: list[FixtureServer] = []

    def _serve(name: str) -> str:
        srv = FixtureServer(fixtures_root / name)
        srv.__enter__()
        servers.append(srv)
        return srv.url

    yield _serve
    for s in servers:
        s.__exit__(None, None, None)


@pytest.fixture
def audit(serve):
    """Run a full audit against a named fixture site."""
    def _audit(name: str, **cfg):
        url = serve(name)
        report, evidence, findings = run_audit_with_evidence(url, make_config(**cfg))
        return report, evidence, findings
    return _audit


# --- assertion helpers shared by the test modules -------------------------

def check_ids(findings) -> set[str]:
    return {f.check_id for f in findings}


def find_check(findings, check_id):
    return next((f for f in findings if f.check_id == check_id), None)
