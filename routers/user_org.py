"""
User-facing organization endpoints -- join, leave, status.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_auth
import database_org
import access_control

router = APIRouter(prefix="/me", tags=["user-org"])


class JoinOrgRequest(BaseModel):
    invite_code: str = Field(..., min_length=8, max_length=8, pattern=r"^[A-Z0-9]{8}$")


@router.post("/org/join")
async def join_org(req: JoinOrgRequest, user: dict = Depends(require_auth)):
    user_id = user.get("sub", "")

    # Check if already in an org
    existing = database_org.get_user_org(user_id)
    if existing:
        raise HTTPException(status_code=409, detail="Already in an organization. Leave first.")

    org = database_org.get_org_by_invite_code(req.invite_code)
    if not org:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    try:
        member = database_org.add_member(org["id"], user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "detail": "Joined organization",
        "org_id": org["id"],
        "org_name": org["name"],
        "joined_at": member["joined_at"],
    }


@router.post("/org/leave")
async def leave_org(user: dict = Depends(require_auth)):
    user_id = user.get("sub", "")
    org_info = database_org.get_user_org(user_id)
    if not org_info:
        raise HTTPException(status_code=404, detail="Not in any organization")

    database_org.remove_member(org_info["org_id"], user_id)
    return {"detail": "Left organization"}


@router.get("/org")
async def get_my_org(user: dict = Depends(require_auth)):
    user_id = user.get("sub", "")
    tier = access_control.get_user_tier(user_id)
    remaining = access_control.get_remaining_questions(user_id)
    limits = access_control.get_tier_limits(tier)
    org_info = database_org.get_user_org(user_id)

    # Strip invite_code from user-facing response (admin-only info)
    safe_org = None
    if org_info:
        safe_org = {k: v for k, v in org_info.items() if k != "invite_code"}

    return {
        "tier": tier,
        "remaining_questions": remaining,
        "limits": limits,
        "organization": safe_org,
    }
