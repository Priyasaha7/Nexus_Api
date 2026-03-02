# app/dependencies.py
import uuid
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt, JWTError, ExpiredSignatureError

from app.database import get_db
from app.models.user import User
from app.config import settings

security = HTTPBearer(auto_error=False)

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

     # ── handle missing token ──
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "missing_token",
                "message": "Authorization token is required.",
                "request_id": request_id,
            }
        )

    token = credentials.credentials

    # decode and validate JWT
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail={
                "error": "invalid_token",
                "message": "Token payload is invalid.",
                "request_id": request_id,
            })
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={
            "error": "token_expired",
            "message": "Your session has expired. Please log in again.",
            "request_id": request_id,
        })
    except JWTError:
        raise HTTPException(status_code=401, detail={
            "error": "invalid_token",
            "message": "Token is invalid or has been tampered with.",
            "request_id": request_id,
        })

    # check if user still exists in DB
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail={
            "error": "user_not_found",
            "message": "User no longer exists.",
            "request_id": request_id,
        })

    return user


# use for admin-only endpoints
async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail={
            "error": "forbidden",
            "message": "Admin access required.",
        })
    return current_user