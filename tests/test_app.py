"""Flask dashboard: safety, isolation and deployment behaviour."""
from __future__ import annotations

import json
import re

import pytest

import app as application


@pytest.fixture
def client():
    application.app.config["TESTING"] = True
    with application.app.test_client() as c:
        yield c


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<!doctype html>" in resp.data.lower()


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_empty_submission_is_handled(client):
    resp = client.post("/", data={"url": ""})
    assert resp.status_code == 200
    assert b"Please enter a website URL" in resp.data


@pytest.mark.parametrize("target", [
    "http://127.0.0.1:8000/", "http://localhost/admin",
    "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd",
    "http://[::1]/", "ftp://example.com/",
])
def test_dashboard_refuses_unsafe_targets(client, target):
    """SSRF protection must hold through the web form, not only the CLI."""
    resp = client.post("/", data={"url": target})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lower()
    assert any(marker in body for marker in
               ("unsafe", "refusing", "not a valid hostname", "scheme not allowed",
                "invalid")), "an unsafe target must be refused with an explanation"


def test_user_input_is_escaped_not_executed(client):
    """The submitted URL is reflected into the page; it must be escaped."""
    resp = client.post("/", data={"url": '"><script>alert(1)</script>'})
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body or "&#34;" in body


def test_downloads_require_a_token(client):
    assert client.get("/download/json/does-not-exist").status_code == 404
    assert client.get("/download/html/does-not-exist").status_code == 404


def test_report_download_is_scoped_to_one_run(client):
    """One visitor's report must not be served to another visitor."""
    first = application._store_report({"site": "first.example", "findings": []})
    second = application._store_report({"site": "second.example", "findings": []})
    assert first != second

    payload = json.loads(client.get(f"/download/json/{first}").get_data())
    assert payload["site"] == "first.example"
    payload = json.loads(client.get(f"/download/json/{second}").get_data())
    assert payload["site"] == "second.example"


def test_html_download_is_rendered_in_memory(tmp_path, monkeypatch):
    """Nothing is written to the working directory, so a read-only FS is fine."""
    monkeypatch.chdir(tmp_path)
    token = application._store_report({
        "site": "example.com", "audited_at": "now",
        "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0,
                    "low": 0, "pages_crawled": 1, "pages_rendered": 0,
                    "runtime_seconds": 0.1},
        "ai_readiness": {"overall": 90, "dimensions": {}, "explanation": {}},
        "findings": [],
    })
    with application.app.test_client() as c:
        resp = c.get(f"/download/html/{token}")
    assert resp.status_code == 200
    assert b"<!doctype html>" in resp.data.lower()
    assert list(tmp_path.iterdir()) == [], "no files should be written on download"


def test_report_cache_is_bounded():
    tokens = [application._store_report({"n": i})
              for i in range(application.MAX_CACHED_REPORTS + 5)]
    assert len(application._REPORTS) <= application.MAX_CACHED_REPORTS
    assert application._load_report(tokens[-1]) is not None
    assert application._load_report(tokens[0]) is None, "oldest entries are evicted"


def test_download_token_is_unguessable():
    token = application._store_report({"x": 1})
    assert len(token) >= 20
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", token)


def test_production_entrypoint_binds_all_interfaces_and_reads_port():
    """gunicorn app:app must find a module-level WSGI callable."""
    assert callable(application.app)
    source = open(application.__file__, encoding="utf-8").read()
    assert 'host="0.0.0.0"' in source
    assert 'os.environ.get("PORT"' in source
    assert "debug=False" in source
    assert "debug=True" not in source
