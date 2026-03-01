# app/routers/credits.py
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models.user import User
from app.services.credit_service import (
    get_balance,
    get_recent_transactions,
    grant_credits,
)

router = APIRouter()


class GrantCreditsRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Must be positive")
    reason: str = Field(..., min_length=1)


# ── GET /credits/balance ──
@router.get("/balance")
async def get_credit_balance(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    balance = await get_balance(str(current_user.organisation_id), db)
    transactions = await get_recent_transactions(str(current_user.organisation_id), db)

    return {
        "organisation_id": str(current_user.organisation_id),
        "balance": balance,
        "recent_transactions": [
            {
                "id": str(tx.id),
                "amount": tx.amount,
                "reason": tx.reason,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in transactions
        ],
    }


# ── POST /credits/grant (admin only) ──
@router.post("/grant")
async def grant_credits_endpoint(
    request: Request,
    body: GrantCreditsRequest,
    current_user: User = Depends(require_admin),  
    db: AsyncSession = Depends(get_db),
):
    transaction = await grant_credits(
        org_id=str(current_user.organisation_id),
        user_id=str(current_user.id),
        amount=body.amount,
        reason=body.reason,
        db=db,
    )

    new_balance = await get_balance(str(current_user.organisation_id), db)

    return {
        "message": "Credits granted successfully",
        "transaction_id": str(transaction.id),
        "amount_added": body.amount,
        "new_balance": new_balance,
    }