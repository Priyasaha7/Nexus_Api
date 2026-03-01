# app/models/user.py
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    google_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(50), default="member")  # "admin" or "member"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organisation: Mapped["Organisation"] = relationship("Organisation", back_populates="users")
    credit_transactions: Mapped[list["CreditTransaction"]] = relationship("CreditTransaction", back_populates="user")