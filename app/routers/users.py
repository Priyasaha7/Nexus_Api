# app/routers/users.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.organisation import Organisation

router = APIRouter()

@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # fetch org details too
    result = await db.execute(
        select(Organisation).where(Organisation.id == current_user.organisation_id)
    )
    org = result.scalar_one_or_none()

    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role,
        "organisation": {
            "id": str(org.id) if org else None,
            "name": org.name if org else None,
            "slug": org.slug if org else None,
        },
    }