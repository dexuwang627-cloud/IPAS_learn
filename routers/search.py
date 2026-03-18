"""Search endpoint for questions."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import is_admin, optional_auth
from database import search_questions

router = APIRouter(tags=["Search"])


@router.get("/questions/search")
async def search(
    q: str = Query(..., min_length=2, max_length=100, description="Search term"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    bank_id: Optional[str] = Query(None),
    user: Optional[dict] = Depends(optional_auth),
):
    """Search questions by content, options, and explanations."""
    results, total = search_questions(query=q, limit=limit, offset=offset, bank_id=bank_id)

    if not user or not is_admin(user):
        results = [
            {k: v for k, v in r.items() if k not in {"answer", "explanation"}}
            for r in results
        ]

    return {"questions": results, "total": total, "query": q}
