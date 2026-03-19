"""
Supabase JWT verification middleware for FastAPI.
Validates the Bearer token from the Authorization header.
Supports both HS256 (legacy) and ES256 (current) Supabase JWT signing.
"""
import logging
import os

import httpx
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Header
from typing import Optional

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

# Fallback: also check email list for bootstrapping admin
_ADMIN_EMAILS = set(
    e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
)

# JWKS client for ES256 verification (cached)
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> Optional[PyJWKClient]:
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def _decode_token(token: str) -> dict:
    """Decode and verify a Supabase JWT (ES256 or HS256)."""
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")
        if alg == "ES256":
            client = _get_jwks_client()
            if not client:
                raise HTTPException(status_code=500, detail="JWKS not configured")
            signing_key = client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
            )
        else:
            return jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT decode failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_auth(authorization: str = Header(..., alias="Authorization")) -> dict:
    """Dependency: require a valid Supabase JWT. Returns decoded user payload."""
    if not SUPABASE_JWT_SECRET and not SUPABASE_URL:
        raise HTTPException(status_code=500, detail="Auth not configured")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    return _decode_token(token)


async def optional_auth(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Optional[dict]:
    """Dependency: optionally decode JWT. Returns None if no header present."""
    if not authorization or (not SUPABASE_JWT_SECRET and not SUPABASE_URL):
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    try:
        return _decode_token(token)
    except HTTPException:
        return None


def is_admin(user: dict) -> bool:
    """Check if user has admin privileges.

    Primary: app_metadata.role == 'admin' (server-controlled, not user-editable).
    Fallback: email in ADMIN_EMAILS env var (for bootstrapping before app_metadata is set).
    """
    app_meta = user.get("app_metadata", {})
    if app_meta.get("role") == "admin":
        return True

    # Fallback for bootstrapping -- use verified email from JWT
    email = user.get("email", "")
    return email in _ADMIN_EMAILS
