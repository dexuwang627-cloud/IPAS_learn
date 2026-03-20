"""
User-facing invite code endpoints -- redeem code, check pro status.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_auth
import database_invite
import access_control

router = APIRouter(prefix="/me", tags=["user-invite"])


class RedeemRequest(BaseModel):
    invite_code: str = Field(..., min_length=8, max_length=8, pattern=r"^[A-Z0-9]{8}$")


@router.post("/pro/redeem")
async def redeem_invite(req: RedeemRequest, user: dict = Depends(require_auth)):
    user_id = user.get("sub", "")
    try:
        result = database_invite.redeem_invite(req.invite_code, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "detail": "Pro activated",
        "activated_at": result["activated_at"],
        "expires_at": result["expires_at"],
    }


@router.get("/pro")
async def get_my_pro(user: dict = Depends(require_auth)):
    user_id = user.get("sub", "")
    tier = access_control.get_user_tier(user_id)
    remaining = access_control.get_remaining_questions(user_id)
    limits = access_control.get_tier_limits(tier)
    pro_info = database_invite.get_user_pro(user_id)

    return {
        "tier": tier,
        "remaining_questions": remaining,
        "limits": limits,
        "pro": {
            "expires_at": pro_info["expires_at"],
            "code": pro_info.get("code"),
        } if pro_info else None,
    }
