# app/routers/auth.py
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from jose import jwt

from app.database import get_db
from app.models.organisation import Organisation
from app.models.user import User
from app.config import settings

router = APIRouter()

config = Config(environ={
    "GOOGLE_CLIENT_ID": settings.GOOGLE_CLIENT_ID,
    "GOOGLE_CLIENT_SECRET": settings.GOOGLE_CLIENT_SECRET,
})

oauth = OAuth(config)
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def create_jwt(user_id: str, org_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)



async def get_or_create_org(email: str, db: AsyncSession):
    domain = email.split("@")[1]
    slug = domain.replace(".", "-")

    result = await db.execute(
        select(Organisation).where(Organisation.slug == slug)
    )
    org = result.scalar_one_or_none()

    if not org:
        org = Organisation(
            id=uuid.uuid4(),
            name=domain,
            slug=slug,
        )
        db.add(org)
        await db.flush()

    return org


# ── GET /auth/google ── 
@router.get("/google")
async def login_with_google(request: Request):
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)


# ── GET /auth/callback ── 
@router.get("/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        raise HTTPException(status_code=401, detail="Google authentication failed")

    user_info = token.get("userinfo")
    if not user_info:
        raise HTTPException(status_code=401, detail="Could not get user info from Google")

    email = user_info.get("email")
    name = user_info.get("name", email)
    google_id = user_info.get("sub")  

    if not email:
        raise HTTPException(status_code=401, detail="Email not provided by Google")

    org = await get_or_create_org(email, db)

    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user:
        existing_users = await db.execute(
            select(User).where(User.organisation_id == org.id)
        )
        is_first_user = existing_users.scalar_one_or_none() is None
        role = "admin" if is_first_user else "member"

        user = User(
            id=uuid.uuid4(),
            email=email,
            name=name,
            google_id=google_id,
            organisation_id=org.id,
            role=role,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    # create JWT
    jwt_token = create_jwt(str(user.id), str(user.organisation_id), user.role)

    return JSONResponse({
        "access_token": jwt_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "organisation_id": str(user.organisation_id),
        }
    })