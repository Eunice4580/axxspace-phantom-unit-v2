"""ORM models for contributors and the contribution ledger (spec section 7)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contributor(Base):
    """An individual account that can accumulate Contribution Units."""

    __tablename__ = "contributors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    ledger_entries: Mapped[list[LedgerEntry]] = relationship(
        back_populates="contributor",
        cascade="all, delete-orphan",
        order_by="LedgerEntry.date_awarded",
    )


class LedgerEntry(Base):
    """A single award of Contribution Units — one row of the official ledger.

    The ledger captures every field required by spec section 7: contributor, task
    description, task reference number, units awarded, date awarded, approving reviewer
    and remarks. (Total Units Held is derived by summing a contributor's entries.)
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contributor_id: Mapped[int] = mapped_column(
        ForeignKey("contributors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    task_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    units_awarded: Mapped[float] = mapped_column(Float, nullable=False)
    approving_reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_awarded: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    contributor: Mapped[Contributor] = relationship(back_populates="ledger_entries")
