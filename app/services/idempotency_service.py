# app/services/idempotency_service.py
import json
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.idempotency import IdempotencyRecord


def _make_key(key: str, org_id: str) -> str:
    """Prefix key with org_id so different orgs can use same key names"""
    return f"{org_id}:{key}"


async def get_idempotency_record(
    key: str,
    org_id: str,
    db: AsyncSession,
) -> dict | None:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    stored_key = _make_key(key, org_id)  # ← use prefixed key

    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == stored_key,
            IdempotencyRecord.organisation_id == org_id,
            IdempotencyRecord.created_at > cutoff,
        )
    )
    record = result.scalar_one_or_none()
    if record:
        return json.loads(record.response_body)
    return None


async def save_idempotency_record(
    key: str,
    org_id: str,
    response_body: dict,
    db: AsyncSession,
) -> None:
    stored_key = _make_key(key, org_id)  

    record = IdempotencyRecord(
        idempotency_key=stored_key,
        organisation_id=org_id,
        response_body=json.dumps(response_body),
    )
    db.add(record)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()