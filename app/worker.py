# app/worker.py
from datetime import datetime, timedelta

from sqlalchemy import select
from arq.connections import RedisSettings
from arq import cron

from app.database import AsyncSessionLocal
from app.models.job import Job
from app.config import settings


# ─────────────────────────────────────────────
# Redis Configuration (from settings.REDIS_URL)
# ─────────────────────────────────────────────

def get_redis_settings():
    """
    Parse REDIS_URL from settings.
    Example: redis://localhost:6379
    """
    url = settings.REDIS_URL.replace("redis://", "")
    parts = url.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 6379
    return RedisSettings(host=host, port=port)


# ─────────────────────────────────────────────
# Background Job: Summarise
# ─────────────────────────────────────────────

async def process_summarise(ctx, job_id: str, text: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            return

        job.status = "running"
        job.updated_at = datetime.utcnow()
        await db.commit()

        try:
            words = text.split()
            word_count = len(words)
            summary_words = words[:20]
            summary = " ".join(summary_words)

            if word_count > 20:
                summary += "..."

            job.status = "completed"
            job.result = f"Summary ({word_count} words): {summary}"
            job.updated_at = datetime.utcnow()

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.updated_at = datetime.utcnow()

        await db.commit()


# ─────────────────────────────────────────────
# Scheduled Cleanup: Mark Stale Jobs
# ─────────────────────────────────────────────

async def mark_stale_jobs(ctx):
    """
    Runs every 60 seconds.
    Marks jobs stuck for more than 5 minutes as failed.
    """

    cutoff = datetime.utcnow() - timedelta(minutes=5)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Job).where(
                Job.status.in_(["pending", "running"]),
                Job.created_at < cutoff,
            )
        )

        stale_jobs = result.scalars().all()

        for job in stale_jobs:
            job.status = "failed"
            job.error = (
                "Job timed out after 5 minutes. "
                "Credits were not refunded automatically — contact support."
            )
            job.updated_at = datetime.utcnow()

        if stale_jobs:
            await db.commit()


# ─────────────────────────────────────────────
# Worker Settings
# ─────────────────────────────────────────────

class WorkerSettings:
    functions = [process_summarise, mark_stale_jobs]
    redis_settings = get_redis_settings()

    cron_jobs = [
        cron(mark_stale_jobs, second=0),
    ]