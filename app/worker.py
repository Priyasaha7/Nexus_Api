# app/worker.py
from datetime import datetime
from sqlalchemy import select
from arq.connections import RedisSettings
from app.database import AsyncSessionLocal
from app.models.job import Job


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


class WorkerSettings:
    functions = [process_summarise]
    redis_settings = RedisSettings(host="localhost", port=6379)