"""ORM models for contributors and the contribution ledger (spec section 7)."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Contributor(Base):
    __tablename__ = "contributors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ledger_entries: Mapped[list[LedgerEntry]] = relationship(
        back_populates="contributor",
        cascade="all, delete-orphan",
        order_by="LedgerEntry.date_awarded",
    )

class LedgerEntry(Base):
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


# ── Chat & Notifications ──────────────────────────────────────────────────────

class ChatRoom(Base):
    """A named group conversation room."""
    __tablename__ = "chat_rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # NULL means room was created by admin
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributors.id", ondelete="SET NULL"), nullable=True
    )
    is_admin_room: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    members: Mapped[list["ChatRoomMember"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="room", cascade="all, delete-orphan",
        order_by="ChatMessage.sent_at",
    )


class ChatRoomMember(Base):
    """Junction: which contributors are in each room."""
    __tablename__ = "chat_room_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contributor_id: Mapped[int] = mapped_column(
        ForeignKey("contributors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    room: Mapped[ChatRoom] = relationship(back_populates="members")
    contributor: Mapped[Contributor] = relationship()


class ChatMessage(Base):
    """A single message inside a chat room."""
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL sender_id = message from admin
    sender_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributors.id", ondelete="SET NULL"), nullable=True
    )
    sender_name: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    room: Mapped[ChatRoom] = relationship(back_populates="messages")


class Notification(Base):
    """In-app notification for a member (or admin when contributor_id IS NULL)."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL = notification for admin; an int = notification for that contributor
    contributor_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributors.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    # kinds: chat_invite | units_awarded | ledger_deleted | chat_message
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # e.g. room_id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


# ── Task Submissions ──────────────────────────────────────────────────────────

class TaskSubmission(Base):
    """A task submitted by a member for admin review and unit award."""
    __tablename__ = "task_submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contributor_id: Mapped[int] = mapped_column(
        ForeignKey("contributors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_title: Mapped[str] = mapped_column(String(300), nullable=False)
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    # status: "pending" | "awarded"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # Filled in by admin after award
    units_awarded: Mapped[float | None] = mapped_column(Float, nullable=True)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    contributor: Mapped[Contributor] = relationship()


# ── Investors ─────────────────────────────────────────────────────────────────

SHARE_PRICE_KES: float = 50.0  # 1 share = KES 50


class Investor(Base):
    """An investor account created by the admin."""
    __tablename__ = "investors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)