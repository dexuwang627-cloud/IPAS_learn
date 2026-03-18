"""
Supabase JWT verification middleware for FastAPI.
Validates the Bearer token from the Authorization header.
"""
import os
import jwt
from fastapi import HTTPException, Header
from typing import Optional

SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

# Fallback: also check email list for bootstrapping admin
_ADMIN_EMAILS = set(
    e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
)


def _decode_token(token: str) -> dict:
    """Decode and verify a Supabase JWT."""
    try:
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_auth(authorization: str = Header(..., alias="Authorization")) -> dict:
    """Dependency: require a valid Supabase JWT. Returns decoded user payload."""
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(status_code=500, detail="Auth not configured")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    return _decode_token(token)


async def optional_auth(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Optional[dict]:
    """Dependency: optionally decode JWT. Returns None if no header present."""
    if not authorization or not SUPABASE_JWT_SECRET:
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
    # Supabase email in JWT is verified by the auth server, not user-editable
    # (different from user_metadata which IS user-editable)
    email = user.get("email", "")
    return email in _ADMIN_EMAILS
