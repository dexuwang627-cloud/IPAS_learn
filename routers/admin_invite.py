"""
Admin invite code management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from auth import require_auth, is_admin
import database_invite

router = APIRouter(prefix="/invite", tags=["admin-invite"])


def _require_admin(user: dict = Depends(require_auth)) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class CreateInviteRequest(BaseModel):
    duration_days: int = Field(..., ge=1, le=3650)
    max_uses: int = Field(1, ge=1, le=10000)
    label: Optional[str] = Field(None, max_length=200)


@router.post("")
async def create_invite(req: CreateInviteRequest, user: dict = Depends(_require_admin)):
    user_id = user.get("sub", "")
    invite = database_invite.create_invite(
        duration_days=req.duration_days,
        max_uses=req.max_uses,
        created_by=user_id,
        label=req.label,
    )
    return invite


@router.get("")
async def list_invites(_user: dict = Depends(_require_admin)):
    return database_invite.list_invites()


# Static path MUST be before /{invite_id} to avoid route conflict
@router.get("/pro-users")
async def list_pro_users(_user: dict = Depends(_require_admin)):
    return database_invite.list_pro_users()


@router.get("/{invite_id}")
async def get_invite(invite_id: int, _user: dict = Depends(_require_admin)):
    invites = database_invite.list_invites()
    match = [i for i in invites if i["id"] == invite_id]
    if not match:
        raise HTTPException(status_code=404, detail="Invite not found")
    return match[0]


@router.delete("/{invite_id}")
async def deactivate_invite(invite_id: int, _user: dict = Depends(_require_admin)):
    result = database_invite.deactivate_invite(invite_id)
    if not result:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"detail": "Invite deactivated"}


@router.get("/{invite_id}/redemptions")
async def list_redemptions(invite_id: int, _user: dict = Depends(_require_admin)):
    redemptions = database_invite.get_redemptions(invite_id)
    return {"invite_id": invite_id, "redemptions": redemptions}
