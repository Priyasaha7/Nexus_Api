# app/services/idempotency_service.py
import json
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select          # ← remove 'delete' from here
from app.models.idempotency import IdempotencyRecord


async def get_idempotency_record(
    key: str,
    org_id: str,
    db: AsyncSession,
) -> dict | None:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == key,
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
    record = IdempotencyRecord(
        idempotency_key=key,
        organisation_id=org_id,
        response_body=json.dumps(response_body),
    )
    db.add(record)
    await db.commit()