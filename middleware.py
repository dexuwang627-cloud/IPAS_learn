"""
Security middleware: headers + rate limiting.
"""
import asyncio
import time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://*.supabase.co; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' https://*.supabase.co; "
            "img-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        return response


def _get_real_ip(request: Request) -> str:
    """Extract real client IP, respecting reverse proxy headers."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory rate limiter per IP with async lock."""

    def __init__(self, app, default_rpm: int = 60, strict_paths: dict | None = None):
        super().__init__(app)
        self.default_rpm = default_rpm
        self.strict_paths = strict_paths or {}
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Strip /v1 so rate limits apply to both /api/ and /api/v1/ routes."""
        if path.startswith("/api/v1/"):
            return "/api/" + path[8:]
        return path

    def _get_limit(self, path: str) -> int:
        normalized = self._normalize_path(path)
        for prefix, limit in self.strict_paths.items():
            if normalized.startswith(prefix):
                return limit
        return self.default_rpm

    def _is_rate_limited(self, key: str, limit: int) -> bool:
        now = time.time()
        window_start = now - 60
        self._buckets[key] = [t for t in self._buckets[key] if t > window_start]
        if len(self._buckets[key]) >= limit:
            return True
        self._buckets[key].append(now)
        return False

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/static") or request.url.path == "/":
            return await call_next(request)

        client_ip = _get_real_ip(request)
        limit = self._get_limit(request.url.path)
        bucket_key = f"{client_ip}:{request.url.path}"

        async with self._lock:
            if self._is_rate_limited(bucket_key, limit):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please slow down."},
                )

        return await call_next(request)
