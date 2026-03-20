"""Tests for middleware module."""
import pytest
from middleware import SecurityHeadersMiddleware, RateLimitMiddleware, _get_real_ip
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from unittest.mock import MagicMock


async def _ok(request):
    return PlainTextResponse("ok")


def _app_with_middleware(**kwargs):
    app = Starlette(routes=[
        Route("/api/test", _ok),
        Route("/api/quiz/pdf", _ok),
        Route("/static/file.js", _ok),
        Route("/", _ok),
    ])
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, **kwargs)
    return app


def test_security_headers_present():
    app = _app_with_middleware(default_rpm=100)
    client = TestClient(app)
    res = client.get("/api/test")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "strict-origin" in res.headers["Referrer-Policy"]
    assert "Content-Security-Policy" in res.headers


def test_csp_allows_supabase():
    app = _app_with_middleware(default_rpm=100)
    client = TestClient(app)
    res = client.get("/api/test")
    csp = res.headers["Content-Security-Policy"]
    assert "supabase.co" in csp
    assert "cdn.jsdelivr.net" in csp


def test_rate_limit_under_threshold():
    app = _app_with_middleware(default_rpm=10)
    client = TestClient(app)
    for _ in range(5):
        res = client.get("/api/test")
        assert res.status_code == 200


def test_rate_limit_over_threshold():
    app = _app_with_middleware(default_rpm=3)
    client = TestClient(app)
    for _ in range(3):
        client.get("/api/test")
    res = client.get("/api/test")
    assert res.status_code == 429


def test_rate_limit_strict_path():
    app = _app_with_middleware(default_rpm=100, strict_paths={"/api/quiz/pdf": 2})
    client = TestClient(app)
    client.get("/api/quiz/pdf")
    client.get("/api/quiz/pdf")
    res = client.get("/api/quiz/pdf")
    assert res.status_code == 429


def test_rate_limit_static_bypassed():
    app = _app_with_middleware(default_rpm=1)
    client = TestClient(app)
    client.get("/api/test")  # use up the limit
    client.get("/api/test")  # should be 429
    res = client.get("/static/file.js")
    assert res.status_code == 200


def test_rate_limit_root_bypassed():
    app = _app_with_middleware(default_rpm=1)
    client = TestClient(app)
    client.get("/api/test")
    client.get("/api/test")
    res = client.get("/")
    assert res.status_code == 200


def test_normalize_path_strips_v1():
    """Rate limits should apply to both /api/ and /api/v1/ paths."""
    mw = RateLimitMiddleware(None, default_rpm=60)
    assert mw._normalize_path("/api/v1/quiz/pdf") == "/api/quiz/pdf"
    assert mw._normalize_path("/api/quiz/pdf") == "/api/quiz/pdf"
    assert mw._normalize_path("/static/file.js") == "/static/file.js"


def test_get_real_ip_from_forwarded():
    request = MagicMock()
    request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
    assert _get_real_ip(request) == "1.2.3.4"


def test_get_real_ip_from_real_ip():
    request = MagicMock()
    request.headers = {"X-Real-IP": "9.8.7.6"}
    assert _get_real_ip(request) == "9.8.7.6"


def test_get_real_ip_from_client():
    request = MagicMock()
    request.headers = {}
    request.client.host = "127.0.0.1"
    assert _get_real_ip(request) == "127.0.0.1"
