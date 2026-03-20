"""
Central configuration -- single source of truth for all env vars.
"""
import os

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
ADMIN_EMAILS = set(
    e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
)
ENV = os.environ.get("ENV", "production")
IS_PRODUCTION = ENV == "production"


def get_public_config() -> dict:
    """Return only safe-to-expose values for the frontend."""
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_ANON_KEY,
        "api_version": "v1",
    }
