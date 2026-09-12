import pytest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
import json
import urllib.parse
from unittest.mock import patch
from aira.config import AuditConfig
import app as application

class TestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/good':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Hello World</h1></body></html>")
        elif self.path == '/301':
            self.send_response(301)
            self.send_header('Location', '/good')
            self.end_headers()
        elif self.path == '/302':
            self.send_response(302)
            self.send_header('Location', '/good')
            self.end_headers()
        elif self.path == '/ext':
            self.send_response(301)
            self.send_header('Location', 'http://example.com/')
            self.end_headers()
        elif self.path == '/timeout':
            time.sleep(12)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Too late")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass

@pytest.fixture(scope="module")
def test_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()

@pytest.fixture
def test_client():
    application.app.config["TESTING"] = True
    original_init = AuditConfig.__init__
    
    def mocked_init(self, *args, **kwargs):
        kwargs['allow_private_networks'] = True
        kwargs['total_crawl_budget_s'] = 5.0
        kwargs['render_budget_s'] = 5.0
        kwargs['request_timeout'] = 2.0
        original_init(self, *args, **kwargs)
        
    with patch.object(AuditConfig, '__init__', mocked_init):
        with application.app.test_client() as c:
            yield c

def test_flask_audit_successful_non_redirecting(test_client, test_server):
    resp = test_client.post("/", data={"url": f"{test_server}/good"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "The site homepage did not return a successful response" not in body
    
def test_flask_audit_301_to_200(test_client, test_server):
    resp = test_client.post("/", data={"url": f"{test_server}/301"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "The site homepage did not return a successful response" not in body
    assert "homepage_redirects_onsite" in body.lower() or "ok" in body.lower() or "score" in body.lower()
    
def test_flask_audit_302_to_200(test_client, test_server):
    resp = test_client.post("/", data={"url": f"{test_server}/302"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "The site homepage did not return a successful response" not in body
    
def test_flask_audit_external_redirect_refusal(test_client, test_server):
    resp = test_client.post("/", data={"url": f"{test_server}/ext"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "different domain" in body.lower()
    assert "The site homepage did not return a successful response" not in body

def test_flask_audit_timeout(test_client, test_server):
    resp = test_client.post("/", data={"url": f"{test_server}/timeout"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "The site homepage did not return a successful response" in body
    
def test_server_usable_after_timeout(test_client, test_server):
    # Verify the server remains usable after a timeout
    resp1 = test_client.post("/", data={"url": f"{test_server}/timeout"})
    assert resp1.status_code == 200
    resp2 = test_client.post("/", data={"url": f"{test_server}/good"})
    assert resp2.status_code == 200
    body = resp2.get_data(as_text=True)
    assert "The site homepage did not return a successful response" not in body
