"""
Admin organization management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_auth, is_admin
import database_org

router = APIRouter(prefix="/org", tags=["admin-org"])


def _require_admin(user: dict = Depends(require_auth)) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    seat_limit: int = Field(..., ge=1, le=1000)


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    seat_limit: int | None = Field(None, ge=1, le=1000)
    is_active: bool | None = None


@router.post("")
async def create_org(req: CreateOrgRequest, user: dict = Depends(_require_admin)):
    user_id = user.get("sub", "")
    org = database_org.create_org(req.name, req.seat_limit, created_by=user_id)
    return org


@router.get("")
async def list_orgs(_user: dict = Depends(_require_admin)):
    return database_org.list_orgs()


@router.get("/{org_id}")
async def get_org(org_id: int, _user: dict = Depends(_require_admin)):
    org = database_org.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.patch("/{org_id}")
async def update_org(org_id: int, req: UpdateOrgRequest, _user: dict = Depends(_require_admin)):
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = database_org.update_org(org_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Organization not found")
    return result


@router.delete("/{org_id}")
async def deactivate_org(org_id: int, _user: dict = Depends(_require_admin)):
    result = database_org.update_org(org_id, is_active=False)
    if not result:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"detail": "Organization deactivated"}


@router.get("/{org_id}/members")
async def list_members(org_id: int, _user: dict = Depends(_require_admin)):
    org = database_org.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    members = database_org.list_members(org_id)
    return {
        "org_id": org_id,
        "seat_limit": org["seat_limit"],
        "used_seats": len(members),
        "members": members,
    }


@router.delete("/{org_id}/members/{user_id}")
async def remove_member(org_id: int, user_id: str, _user: dict = Depends(_require_admin)):
    removed = database_org.remove_member(org_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"detail": "Member removed"}
