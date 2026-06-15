"""Business logic: contributor management, unit awards and dashboard aggregation."""
from __future__ import annotations
from collections import defaultdict
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import EUR_PER_UNIT, TOTAL_POOL_UNITS, UNIT_INCREMENT
from app.auth import hash_password, verify_member_password

class BusinessRuleError(ValueError):
    """Raised when an operation would violate a compensation-plan rule."""

def _round_units(value: float) -> float:
    return round(value, 1)

def validate_units(units: float) -> float:
    if units <= 0:
        raise BusinessRuleError("Units awarded must be greater than zero.")
    tenths = units / UNIT_INCREMENT
    if abs(tenths - round(tenths)) > 1e-6:
        raise BusinessRuleError("Units must be in increments of 0.1 (e.g. 0.1, 0.5, 1.0).")
    return _round_units(units)

def total_allocated_units(db: Session) -> float:
    total = db.execute(
        select(func.coalesce(func.sum(models.LedgerEntry.units_awarded), 0.0))
    ).scalar_one()
    return _round_units(float(total))

def remaining_units(db: Session) -> float:
    return _round_units(TOTAL_POOL_UNITS - total_allocated_units(db))

# --- Contributors ------------------------------------------------------------
def create_contributor(db: Session, data: schemas.ContributorCreate) -> models.Contributor:
    contributor = models.Contributor(
        name=data.name.strip(),
        email=(data.email.strip() if data.email else None),
        category=data.category.strip(),
        password_hash=(hash_password(data.password) if data.password else None),
        is_approved=True,  # Admin-created contributors are always auto-approved
    )
    db.add(contributor)
    db.commit()
    db.refresh(contributor)
    return contributor

def get_contributor(db: Session, contributor_id: int) -> models.Contributor | None:
    return db.get(models.Contributor, contributor_id)

def contributor_total_units(db: Session, contributor_id: int) -> float:
    total = db.execute(
        select(func.coalesce(func.sum(models.LedgerEntry.units_awarded), 0.0)).where(
            models.LedgerEntry.contributor_id == contributor_id
        )
    ).scalar_one()
    return _round_units(float(total))

def list_contributors(db: Session) -> list[schemas.ContributorOut]:
    contributors = (
        db.execute(select(models.Contributor).order_by(models.Contributor.name)).scalars().all()
    )
    out: list[schemas.ContributorOut] = []
    for c in contributors:
        total = contributor_total_units(db, c.id)
        out.append(
            schemas.ContributorOut(
                id=c.id,
                name=c.name,
                email=c.email,
                category=c.category,
                created_at=c.created_at,
                is_approved=c.is_approved,
                total_units=total,
                total_value_eur=_round_units(total) * EUR_PER_UNIT,
            )
        )
    return out

def list_pending_contributors(db: Session) -> list[schemas.ContributorOut]:
    """Return contributors who have registered but not yet been approved."""
    contributors = (
        db.execute(
            select(models.Contributor)
            .where(models.Contributor.is_approved == False)
            .where(models.Contributor.password_hash != None)
            .order_by(models.Contributor.created_at.desc())
        ).scalars().all()
    )
    out: list[schemas.ContributorOut] = []
    for c in contributors:
        out.append(
            schemas.ContributorOut(
                id=c.id,
                name=c.name,
                email=c.email,
                category=c.category,
                created_at=c.created_at,
                is_approved=c.is_approved,
                total_units=0.0,
                total_value_eur=0.0,
            )
        )
    return out

def approve_contributor(db: Session, contributor_id: int) -> models.Contributor | None:
    contributor = get_contributor(db, contributor_id)
    if contributor is None:
        return None
    contributor.is_approved = True
    db.commit()
    db.refresh(contributor)
    return contributor

def delete_contributor(db: Session, contributor_id: int) -> bool:
    """Delete a contributor and all their ledger entries."""
    contributor = get_contributor(db, contributor_id)
    if contributor is None:
        return False
    db.delete(contributor)
    db.commit()
    return True

# --- Ledger / awards ---------------------------------------------------------
def award_units(db: Session, data: schemas.LedgerEntryCreate) -> models.LedgerEntry:
    units = validate_units(data.units_awarded)
    contributor = get_contributor(db, data.contributor_id)
    if contributor is None:
        raise BusinessRuleError("Contributor not found.")
    available = remaining_units(db)
    if units > available + 1e-9:
        raise BusinessRuleError(
            f"Award of {units:g} units exceeds the remaining pool of {available:g} units."
        )
    entry = models.LedgerEntry(
        contributor_id=contributor.id,
        task_description=data.task_description.strip(),
        task_reference=(data.task_reference.strip() if data.task_reference else None),
        units_awarded=units,
        approving_reviewer=data.approving_reviewer.strip(),
        remarks=(data.remarks.strip() if data.remarks else None),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

def _entry_to_out(entry: models.LedgerEntry) -> schemas.LedgerEntryOut:
    return schemas.LedgerEntryOut(
        id=entry.id,
        contributor_id=entry.contributor_id,
        contributor_name=entry.contributor.name,
        task_description=entry.task_description,
        task_reference=entry.task_reference,
        units_awarded=entry.units_awarded,
        value_eur=_round_units(entry.units_awarded) * EUR_PER_UNIT,
        approving_reviewer=entry.approving_reviewer,
        remarks=entry.remarks,
        date_awarded=entry.date_awarded,
    )

def delete_ledger_entry(db: Session, entry_id: int) -> bool:
    """Delete a single ledger entry by ID."""
    entry = db.get(models.LedgerEntry, entry_id)
    if entry is None:
        return False
    db.delete(entry)
    db.commit()
    return True

def list_ledger(db: Session) -> list[schemas.LedgerEntryOut]:
    entries = db.execute(
        select(models.LedgerEntry).order_by(models.LedgerEntry.date_awarded.desc())
    ).scalars().all()
    return [_entry_to_out(e) for e in entries]

# --- Dashboard aggregation ---------------------------------------------------
def pool_stats(db: Session) -> schemas.PoolStats:
    allocated = total_allocated_units(db)
    contributor_count = db.execute(select(func.count(models.Contributor.id))).scalar_one()
    award_count = db.execute(select(func.count(models.LedgerEntry.id))).scalar_one()
    return schemas.PoolStats(
        total_pool_units=TOTAL_POOL_UNITS,
        allocated_units=allocated,
        remaining_units=_round_units(TOTAL_POOL_UNITS - allocated),
        allocated_pct=_round_units(allocated / TOTAL_POOL_UNITS * 100) if TOTAL_POOL_UNITS else 0.0,
        eur_per_unit=EUR_PER_UNIT,
        total_pool_value_eur=TOTAL_POOL_UNITS * EUR_PER_UNIT,
        allocated_value_eur=_round_units(allocated) * EUR_PER_UNIT,
        contributor_count=int(contributor_count),
        award_count=int(award_count),
    )

def growth(db: Session) -> schemas.GrowthResponse:
    entries = db.execute(
        select(models.LedgerEntry).order_by(models.LedgerEntry.date_awarded)
    ).scalars().all()
    by_day: dict[str, float] = defaultdict(float)
    for e in entries:
        day = e.date_awarded.date().isoformat()
        by_day[day] += e.units_awarded
    overall: list[schemas.GrowthPoint] = []
    running = 0.0
    for day in sorted(by_day):
        running += by_day[day]
        overall.append(schemas.GrowthPoint(date=day, cumulative_units=_round_units(running)))
    per_contrib_days: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    names: dict[int, str] = {}
    for e in entries:
        names[e.contributor_id] = e.contributor.name
        day = e.date_awarded.date().isoformat()
        per_contrib_days[e.contributor_id][day] += e.units_awarded
    per_contributor: list[schemas.ContributorGrowth] = []
    for cid, days in per_contrib_days.items():
        pts: list[schemas.GrowthPoint] = []
        run = 0.0
        for day in sorted(days):
            run += days[day]
            pts.append(schemas.GrowthPoint(date=day, cumulative_units=_round_units(run)))
        per_contributor.append(
            schemas.ContributorGrowth(contributor_id=cid, name=names[cid], points=pts)
        )
    return schemas.GrowthResponse(overall=overall, per_contributor=per_contributor)

# --- Member self-service -----------------------------------------------------
def get_contributor_by_email(db: Session, email: str) -> models.Contributor | None:
    return db.execute(
        select(models.Contributor).where(models.Contributor.email == email)
    ).scalar_one_or_none()

def register_member(db: Session, data: schemas.MemberRegisterRequest) -> models.Contributor:
    existing = get_contributor_by_email(db, data.email)
    if existing is not None:
        if existing.password_hash is not None:
            raise BusinessRuleError("An account with that email already exists.")
        existing.name = data.name.strip()
        existing.category = data.category.strip()
        existing.password_hash = hash_password(data.password)
        existing.is_approved = True  # Auto-approved on registration
        db.commit()
        db.refresh(existing)
        return existing
    contributor = models.Contributor(
        name=data.name.strip(),
        email=data.email.strip(),
        category=data.category.strip(),
        password_hash=hash_password(data.password),
        is_approved=True,  # Auto-approved on registration
    )
    db.add(contributor)
    db.commit()
    db.refresh(contributor)
    return contributor

def authenticate_member(db: Session, email: str, password: str) -> models.Contributor | None:
    contributor = get_contributor_by_email(db, email)
    if contributor is None or contributor.password_hash is None:
        return None
    if not verify_member_password(password, contributor.password_hash):
        return None
    return contributor

def get_member_profile(db: Session, contributor_id: int) -> schemas.MemberProfileOut | None:
    contributor = get_contributor(db, contributor_id)
    if contributor is None:
        return None
    total = contributor_total_units(db, contributor_id)
    all_contributors = list_contributors(db)
    sorted_contributors = sorted(all_contributors, key=lambda c: c.total_units, reverse=True)
    rank = next(
        (i + 1 for i, c in enumerate(sorted_contributors) if c.id == contributor_id), 0
    )
    entries = db.execute(
        select(models.LedgerEntry)
        .where(models.LedgerEntry.contributor_id == contributor_id)
        .order_by(models.LedgerEntry.date_awarded.desc())
    ).scalars().all()
    ledger = [_entry_to_out(e) for e in entries]
    entries_asc = list(reversed(entries))
    by_day: dict[str, float] = defaultdict(float)
    for e in entries_asc:
        day = e.date_awarded.date().isoformat()
        by_day[day] += e.units_awarded
    growth_points: list[schemas.GrowthPoint] = []
    running = 0.0
    for day in sorted(by_day):
        running += by_day[day]
        growth_points.append(
            schemas.GrowthPoint(date=day, cumulative_units=_round_units(running))
        )
    return schemas.MemberProfileOut(
        id=contributor.id,
        name=contributor.name,
        email=contributor.email,
        category=contributor.category,
        created_at=contributor.created_at,
        total_units=total,
        total_value_eur=_round_units(total) * EUR_PER_UNIT,
        rank=rank,
        ledger=ledger,
        growth_points=growth_points,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────────

def create_notification(
    db: Session,
    *,
    contributor_id: int | None,   # None → admin notification
    kind: str,
    title: str,
    body: str,
    ref_id: int | None = None,
) -> models.Notification:
    n = models.Notification(
        contributor_id=contributor_id,
        kind=kind,
        title=title,
        body=body,
        ref_id=ref_id,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def list_notifications(
    db: Session, contributor_id: int | None
) -> list[models.Notification]:
    """Return notifications for a member (or admin when contributor_id is None)."""
    from sqlalchemy import select as _sel
    if contributor_id is None:
        stmt = (
            _sel(models.Notification)
            .where(models.Notification.contributor_id.is_(None))
            .order_by(models.Notification.created_at.desc())
            .limit(100)
        )
    else:
        stmt = (
            _sel(models.Notification)
            .where(models.Notification.contributor_id == contributor_id)
            .order_by(models.Notification.created_at.desc())
            .limit(100)
        )
    return list(db.execute(stmt).scalars().all())


def mark_notification_read(
    db: Session, notification_id: int, contributor_id: int | None
) -> bool:
    n = db.get(models.Notification, notification_id)
    if n is None or n.contributor_id != contributor_id:
        return False
    n.is_read = True
    db.commit()
    return True


def mark_all_notifications_read(db: Session, contributor_id: int | None) -> None:
    from sqlalchemy import update as _upd
    if contributor_id is None:
        stmt = (
            _upd(models.Notification)
            .where(models.Notification.contributor_id.is_(None))
            .values(is_read=True)
        )
    else:
        stmt = (
            _upd(models.Notification)
            .where(models.Notification.contributor_id == contributor_id)
            .values(is_read=True)
        )
    db.execute(stmt)
    db.commit()


def unread_notification_count(db: Session, contributor_id: int | None) -> int:
    from sqlalchemy import select as _sel
    if contributor_id is None:
        stmt = _sel(func.count(models.Notification.id)).where(
            models.Notification.contributor_id.is_(None),
            models.Notification.is_read == False,  # noqa: E712
        )
    else:
        stmt = _sel(func.count(models.Notification.id)).where(
            models.Notification.contributor_id == contributor_id,
            models.Notification.is_read == False,  # noqa: E712
        )
    return int(db.execute(stmt).scalar_one())


# ─────────────────────────────────────────────────────────────────────────────
# Chat rooms & messages
# ─────────────────────────────────────────────────────────────────────────────

def _room_to_out(room: models.ChatRoom) -> schemas.ChatRoomOut:
    return schemas.ChatRoomOut(
        id=room.id,
        name=room.name,
        created_by_id=room.created_by_id,
        is_admin_room=room.is_admin_room,
        created_at=room.created_at,
        member_ids=[m.contributor_id for m in room.members],
    )


def create_chat_room(
    db: Session,
    name: str,
    creator_contributor_id: int | None,   # None = admin
    is_admin_room: bool,
    invitee_ids: list[int],
) -> models.ChatRoom:
    """Create a room, add creator + invitees as members, and send invitations."""
    room = models.ChatRoom(
        name=name,
        created_by_id=creator_contributor_id,
        is_admin_room=is_admin_room,
    )
    db.add(room)
    db.flush()  # get room.id before commit

    # Collect unique member IDs: creator (if member) + invitees
    member_set: set[int] = set(invitee_ids)
    if creator_contributor_id is not None:
        member_set.add(creator_contributor_id)

    for cid in member_set:
        db.add(models.ChatRoomMember(room_id=room.id, contributor_id=cid))

    db.commit()
    db.refresh(room)

    # Determine creator display name
    if creator_contributor_id is not None:
        creator = get_contributor(db, creator_contributor_id)
        creator_name = creator.name if creator else "A member"
    else:
        creator_name = "Admin"

    # Notify invitees (exclude the creator)
    notify_ids = [i for i in member_set if i != creator_contributor_id]
    for cid in notify_ids:
        create_notification(
            db,
            contributor_id=cid,
            kind="chat_invite",
            title=f"You've been invited to \"{name}\"",
            body=f"{creator_name} invited you to join the chat room \"{name}\".",
            ref_id=room.id,
        )

    # Notify admin when a member creates a room
    if creator_contributor_id is not None:
        create_notification(
            db,
            contributor_id=None,   # admin notification
            kind="chat_invite",
            title=f"New chat room: \"{name}\"",
            body=f"{creator_name} created a new chat room and invited {len(notify_ids)} member(s).",
            ref_id=room.id,
        )

    return room


def list_rooms_for_member(db: Session, contributor_id: int) -> list[schemas.ChatRoomOut]:
    from sqlalchemy import select as _sel
    stmt = (
        _sel(models.ChatRoom)
        .join(models.ChatRoomMember, models.ChatRoomMember.room_id == models.ChatRoom.id)
        .where(models.ChatRoomMember.contributor_id == contributor_id)
        .order_by(models.ChatRoom.created_at.desc())
    )
    rooms = db.execute(stmt).scalars().all()
    return [_room_to_out(r) for r in rooms]


def list_all_rooms(db: Session) -> list[schemas.ChatRoomOut]:
    from sqlalchemy import select as _sel
    rooms = db.execute(
        _sel(models.ChatRoom).order_by(models.ChatRoom.created_at.desc())
    ).scalars().all()
    return [_room_to_out(r) for r in rooms]


def get_room(db: Session, room_id: int) -> models.ChatRoom | None:
    return db.get(models.ChatRoom, room_id)


def is_room_member(db: Session, room_id: int, contributor_id: int) -> bool:
    from sqlalchemy import select as _sel
    row = db.execute(
        _sel(models.ChatRoomMember).where(
            models.ChatRoomMember.room_id == room_id,
            models.ChatRoomMember.contributor_id == contributor_id,
        )
    ).scalar_one_or_none()
    return row is not None


def post_message(
    db: Session,
    room_id: int,
    sender_id: int | None,
    sender_name: str,
    body: str,
) -> schemas.ChatMessageOut:
    msg = models.ChatMessage(
        room_id=room_id,
        sender_id=sender_id,
        sender_name=sender_name,
        body=body,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return schemas.ChatMessageOut(
        id=msg.id,
        room_id=msg.room_id,
        sender_id=msg.sender_id,
        sender_name=msg.sender_name,
        body=msg.body,
        sent_at=msg.sent_at,
    )


def list_messages(db: Session, room_id: int) -> list[schemas.ChatMessageOut]:
    from sqlalchemy import select as _sel
    msgs = db.execute(
        _sel(models.ChatMessage)
        .where(models.ChatMessage.room_id == room_id)
        .order_by(models.ChatMessage.sent_at)
    ).scalars().all()
    return [
        schemas.ChatMessageOut(
            id=m.id,
            room_id=m.room_id,
            sender_id=m.sender_id,
            sender_name=m.sender_name,
            body=m.body,
            sent_at=m.sent_at,
        )
        for m in msgs
    ]


def get_latest_message_id(db: Session, room_ids: list[int]) -> int:
    """Return the highest message id across the given rooms (0 if none)."""
    if not room_ids:
        return 0
    from sqlalchemy import select as _sel
    result = db.execute(
        _sel(func.coalesce(func.max(models.ChatMessage.id), 0)).where(
            models.ChatMessage.room_id.in_(room_ids)
        )
    ).scalar_one()
    return int(result)


# ─────────────────────────────────────────────────────────────────────────────
# Patched award_units & delete_ledger_entry (emit notifications)
# ─────────────────────────────────────────────────────────────────────────────

def award_units_with_notify(
    db: Session, data: schemas.LedgerEntryCreate
) -> models.LedgerEntry:
    """award_units that also fires a notification to the recipient member."""
    entry = award_units(db, data)
    contributor = get_contributor(db, data.contributor_id)
    if contributor:
        create_notification(
            db,
            contributor_id=contributor.id,
            kind="units_awarded",
            title=f"+{entry.units_awarded:g} units awarded",
            body=(
                f"You received {entry.units_awarded:g} units for: "
                f"{entry.task_description[:120]}"
                f"{' …' if len(entry.task_description) > 120 else ''}."
            ),
        )
    return entry


def delete_ledger_entry_with_notify(db: Session, entry_id: int) -> bool:
    """delete_ledger_entry that fires a notification to the affected member."""
    entry = db.get(models.LedgerEntry, entry_id)
    if entry is None:
        return False
    contributor_id = entry.contributor_id
    units = entry.units_awarded
    task = entry.task_description
    ok = delete_ledger_entry(db, entry_id)
    if ok:
        create_notification(
            db,
            contributor_id=contributor_id,
            kind="ledger_deleted",
            title=f"Ledger entry removed (−{units:g} units)",
            body=(
                f"An admin removed a ledger entry of {units:g} units for: "
                f"{task[:120]}{' …' if len(task) > 120 else ''}."
            ),
        )
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Investor management
# ─────────────────────────────────────────────────────────────────────────────

SHARE_PRICE_KES: float = 50.0


def _investor_to_out(investor: models.Investor) -> schemas.InvestorOut:
    return schemas.InvestorOut(
        id=investor.id,
        name=investor.name,
        email=investor.email,
        phone=investor.phone,
        shares=investor.shares,
        share_price_kes=SHARE_PRICE_KES,
        total_value_kes=investor.shares * SHARE_PRICE_KES,
        created_at=investor.created_at,
    )


def create_investor(db: Session, data: schemas.InvestorCreate) -> models.Investor:
    """Create a new investor account (admin only)."""
    existing = db.execute(
        select(models.Investor).where(models.Investor.email == data.email.strip().lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise BusinessRuleError("An investor with that email already exists.")
    investor = models.Investor(
        name=data.name.strip(),
        email=data.email.strip().lower(),
        phone=data.phone.strip() if data.phone else None,
        shares=data.shares,
        password_hash=hash_password(data.password),
    )
    db.add(investor)
    db.commit()
    db.refresh(investor)
    return investor


def list_investors(db: Session) -> list[schemas.InvestorOut]:
    investors = db.execute(
        select(models.Investor).order_by(models.Investor.shares.desc(), models.Investor.name)
    ).scalars().all()
    return [_investor_to_out(i) for i in investors]


def delete_investor(db: Session, investor_id: int) -> bool:
    investor = db.get(models.Investor, investor_id)
    if investor is None:
        return False
    db.delete(investor)
    db.commit()
    return True


def authenticate_investor(
    db: Session, email: str, password: str
) -> models.Investor | None:
    """Verify investor credentials. Returns None on any failure."""
    investor = db.execute(
        select(models.Investor).where(models.Investor.email == email.strip().lower())
    ).scalar_one_or_none()
    if investor is None:
        return None
    if not verify_member_password(password, investor.password_hash):
        return None
    return investor


def is_member_email(db: Session, email: str) -> bool:
    """Return True if this email belongs to a contributor (member), not an investor."""
    return get_contributor_by_email(db, email.strip().lower()) is not None


def is_investor_email(db: Session, email: str) -> bool:
    """Return True if this email belongs to an investor."""
    return db.execute(
        select(models.Investor).where(models.Investor.email == email.strip().lower())
    ).scalar_one_or_none() is not None


def get_investor_profile(db: Session, investor_id: int) -> schemas.InvestorProfileOut | None:
    investor = db.get(models.Investor, investor_id)
    if investor is None:
        return None
    all_investors = list_investors(db)
    sorted_investors = sorted(all_investors, key=lambda i: i.shares, reverse=True)
    rank = next((i + 1 for i, inv in enumerate(sorted_investors) if inv.id == investor_id), 1)
    total_shares = sum(i.shares for i in all_investors)
    portfolio_pct = round((investor.shares / total_shares * 100) if total_shares else 0.0, 2)
    return schemas.InvestorProfileOut(
        id=investor.id,
        name=investor.name,
        email=investor.email,
        phone=investor.phone,
        shares=investor.shares,
        share_price_kes=SHARE_PRICE_KES,
        total_value_kes=investor.shares * SHARE_PRICE_KES,
        created_at=investor.created_at,
        rank=rank,
        total_investors=len(all_investors),
        portfolio_pct=portfolio_pct,
    )