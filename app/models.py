"""ORM models for contributors and the contribution ledger (spec section 7)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contributor(Base):
    """An individual account that can accumulate Contribution Units.

    A person may hold two separate accounts under the same email address — one
    with role='member' and one with role='investor'. The composite unique
    constraint on (email, role) enforces that each (email, role) pair is unique
    while still permitting the same email across different roles.
    """

    __tablename__ = "contributors"
    __table_args__ = (
        UniqueConstraint("email", "role", name="uq_contributor_email_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
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


class TaskSubmission(Base):
    """A task submitted by a member for admin review and unit award.

    Lifecycle: pending → awarded | rejected | done

    * ``awarded``  — admin awarded units through the Submissions queue OR
                     through the direct Award Units form (auto-resolved).
    * ``rejected`` — admin declined the submission with an explanation.
    * ``done``     — admin marked it complete with a note (no units awarded).

    ``admin_note`` is sent back to the member as feedback in all terminal states.
    ``ledger_entry_id`` is set when the submission is resolved via an award.
    """

    __tablename__ = "task_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contributor_id: Mapped[int] = mapped_column(
        ForeignKey("contributors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    task_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Status: pending | awarded | rejected | done
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ledger_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_entries.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contributor: Mapped[Contributor] = relationship("Contributor")
    ledger_entry: Mapped[LedgerEntry | None] = relationship("LedgerEntry")
