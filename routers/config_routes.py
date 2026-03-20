"""
Public configuration endpoint -- serves frontend-safe config.
"""
from fastapi import APIRouter
from config import get_public_config

router = APIRouter(tags=["Configuration"])


@router.get("/config")
async def public_config():
    """Return public configuration (Supabase URL, anon key)."""
    return get_public_config()
