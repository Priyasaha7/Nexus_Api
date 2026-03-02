# app/services/credit_service.py
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.models.credit_transaction import CreditTransaction
from app.exceptions import InsufficientCreditsError


# ── get current balance for an org ──
async def get_balance(org_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0))
        .where(CreditTransaction.organisation_id == org_id)
    )
    return result.scalar()


# ── get last 10 transactions for an org ──
async def get_recent_transactions(org_id: str, db: AsyncSession) -> list:
    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.organisation_id == org_id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(10)
    )
    return result.scalars().all()


# ── add credits (admin only) ──
async def grant_credits(
    org_id: str,
    user_id: str,
    amount: int,
    reason: str,
    db: AsyncSession,
) -> CreditTransaction:
    transaction = CreditTransaction(
        id=uuid.uuid4(),
        organisation_id=org_id,
        user_id=user_id,
        amount=amount,       # positive = adding credits
        reason=reason,
    )
    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)
    return transaction


async def deduct_credits(
    org_id: str,
    user_id: str,
    amount: int,
    reason: str,
    db: AsyncSession,
    idempotency_key: str | None = None,
) -> CreditTransaction:

    # check idempotency first
    if idempotency_key:
        existing = await db.execute(
            select(CreditTransaction)
            .where(CreditTransaction.idempotency_key == idempotency_key)
        )
        existing_tx = existing.scalar_one_or_none()
        if existing_tx:
            return existing_tx

    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.organisation_id == org_id)
        .with_for_update()
    )
    transactions = result.scalars().all()
    current_balance = sum(tx.amount for tx in transactions)

    # check balance
    if current_balance < amount:
        raise InsufficientCreditsError(balance=current_balance, required=amount)

    # create deduction row
    transaction = CreditTransaction(
        id=uuid.uuid4(),
        organisation_id=org_id,
        user_id=user_id,
        amount=-amount,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    db.add(transaction)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.execute(
            select(CreditTransaction)
            .where(CreditTransaction.idempotency_key == idempotency_key)
        )
        return existing.scalar_one()

    await db.refresh(transaction)
    return transaction