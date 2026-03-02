# app/routers/api.py
import uuid
from typing import Optional

from app.rate_limiter import product_limiter

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.job import Job
from app.services.credit_service import deduct_credits, get_balance
from app.exceptions import InsufficientCreditsError
from app.services.idempotency_service import (
    get_idempotency_record,
    save_idempotency_record,
)

router = APIRouter()

ANALYSE_COST = 25
SUMMARISE_COST = 10


class TextRequest(BaseModel):
    text: str = Field(..., min_length=10, max_length=2000)


async def get_redis_pool():
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        from app.config import settings
        return await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    except Exception:
        return None

# ─────────────────────────────────────────────
# POST /api/analyse
# ─────────────────────────────────────────────
@router.post("/analyse")
@product_limiter.limit("60/minute")
async def analyse_text(
    request: Request,
    body: TextRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # ── IDEMPOTENCY CHECK FIRST ──
    if idempotency_key:
        existing = await get_idempotency_record(
            key=idempotency_key,
            org_id=str(current_user.organisation_id),
            db=db,
        )
        if existing:
            return existing

    # STEP 1 — Deduct credits
    try:
        await deduct_credits(
            org_id=str(current_user.organisation_id),
            user_id=str(current_user.id),
            amount=ANALYSE_COST,
            reason="POST /api/analyse",
            db=db,
            idempotency_key=idempotency_key,
        )
    except InsufficientCreditsError:
        balance = await get_balance(str(current_user.organisation_id), db)
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "message": "Not enough credits to perform this action.",
                "balance": balance,
                "required": ANALYSE_COST,
                "request_id": request_id,
            },
        )

    # STEP 2 — Do the work
    words = body.text.split()
    word_count = len(words)
    unique_words = len(set(w.lower() for w in words))
    result = f"Analysis complete. Word count: {word_count}. Unique words: {unique_words}."

    remaining = await get_balance(str(current_user.organisation_id), db)

    response_body = {
        "result": result,
        "credits_remaining": remaining,
    }

    # ── SAVE IDEMPOTENCY RECORD ──
    if idempotency_key:
        await save_idempotency_record(
            key=idempotency_key,
            org_id=str(current_user.organisation_id),
            response_body=response_body,
            db=db,
        )

    return response_body


# ─────────────────────────────────────────────
# POST /api/summarise
# ─────────────────────────────────────────────
@router.post("/summarise")
@product_limiter.limit("60/minute")
async def summarise_text(
    request: Request,
    body: TextRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # ── IDEMPOTENCY CHECK FIRST ──
    if idempotency_key:
        existing = await get_idempotency_record(
            key=idempotency_key,
            org_id=str(current_user.organisation_id),
            db=db,
        )
        if existing:
            return existing

    # STEP 1 — Deduct credits
    try:
        await deduct_credits(
            org_id=str(current_user.organisation_id),
            user_id=str(current_user.id),
            amount=SUMMARISE_COST,
            reason="POST /api/summarise",
            db=db,
            idempotency_key=idempotency_key,
        )
    except InsufficientCreditsError:
        balance = await get_balance(str(current_user.organisation_id), db)
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "message": "Not enough credits to perform this action.",
                "balance": balance,
                "required": SUMMARISE_COST,
                "request_id": request_id,
            },
        )

    # STEP 2 — Create Job
    job = Job(
        id=uuid.uuid4(),
        organisation_id=current_user.organisation_id,
        user_id=current_user.id,
        status="pending",
    )
    db.add(job)
    await db.commit()

    # STEP 3 — Queue background job
    redis = await get_redis_pool()
    if redis:
        await redis.enqueue_job("process_summarise", str(job.id), body.text)
        await redis.close()
    else:
        job.status = "failed"
        job.error = "Queue unavailable. Please retry."
        await db.commit()

    response_body = {
        "job_id": str(job.id),
        "status": job.status,
        "message": "Job queued. Poll /api/jobs/{job_id} for result.",
    }

    # ── SAVE IDEMPOTENCY RECORD ──
    if idempotency_key:
        await save_idempotency_record(
            key=idempotency_key,
            org_id=str(current_user.organisation_id),
            response_body=response_body,
            db=db,
        )

    return response_body


# ─────────────────────────────────────────────
# GET /api/jobs/{job_id}
# ─────────────────────────────────────────────
@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "job_not_found",
                "message": f"Job {job_id} does not exist.",
                "request_id": request_id,
            },
        )

    if str(job.organisation_id) != str(current_user.organisation_id):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "forbidden",
                "message": "You do not have access to this job.",
                "request_id": request_id,
            },
        )

    return {
        "job_id": str(job.id),
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }