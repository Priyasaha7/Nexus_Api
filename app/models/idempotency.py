# app/models/idempotency.py
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    organisation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)  # stored as JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)