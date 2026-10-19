"""Business logic: contributor management, unit awards and dashboard aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import EUR_PER_UNIT, TOTAL_POOL_UNITS, UNIT_INCREMENT
from app.auth import hash_password, verify_member_password


class BusinessRuleError(ValueError):
    """Raised when an operation would violate a compensation-plan rule."""


def _round_units(value: float) -> float:
    """Round to one decimal place to avoid binary float drift on 0.1 multiples."""
    return round(value, 1)


def validate_units(units: float) -> float:
    """Ensure an award is positive and a clean multiple of 0.1 (spec section 2.2).

    The increment is checked on the *raw* value (before any rounding) so that values like
    0.15 are rejected rather than silently snapped to 0.1/0.2.
    """
    if units <= 0:
        raise BusinessRuleError("Units awarded must be greater than zero.")
    # A valid value is a whole number of tenths, e.g. 0.1 -> 1, 1.5 -> 15.
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
    if data.email:
        existing = get_contributor_by_email(db, data.email.strip(), data.role)
        if existing is not None:
            raise BusinessRuleError(
                f"A {data.role} account with that email already exists."
            )
    contributor = models.Contributor(
        name=data.name.strip(),
        email=(data.email.strip() if data.email else None),
        role=data.role,
        category=data.category.strip(),
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
                role=c.role,
                category=c.category,
                created_at=c.created_at,
                total_units=total,
                total_value_eur=_round_units(total) * EUR_PER_UNIT,
            )
        )
    return out


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
    db.flush()  # get entry.id before committing

    # Auto-resolve any pending submission from this contributor so it doesn't
    # stay stuck in the queue after units are awarded via the direct form.
    pending = db.execute(
        select(models.TaskSubmission).where(
            models.TaskSubmission.contributor_id == contributor.id,
            models.TaskSubmission.status == "pending",
        )
    ).scalars().first()
    if pending is not None:
        pending.status = "awarded"
        pending.admin_note = "Awarded via direct Award Units form."
        pending.ledger_entry_id = entry.id
        pending.resolved_at = _utcnow()

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
    """Build cumulative-unit time series for the whole pool and per contributor.

    Each award contributes a step on the day it was made; values accumulate over time so
    the dashboard can plot the growth of all accounts.
    """
    entries = db.execute(
        select(models.LedgerEntry).order_by(models.LedgerEntry.date_awarded)
    ).scalars().all()

    # Overall cumulative series keyed by calendar day.
    by_day: dict[str, float] = defaultdict(float)
    for e in entries:
        day = e.date_awarded.date().isoformat()
        by_day[day] += e.units_awarded

    overall: list[schemas.GrowthPoint] = []
    running = 0.0
    for day in sorted(by_day):
        running += by_day[day]
        overall.append(schemas.GrowthPoint(date=day, cumulative_units=_round_units(running)))

    # Per-contributor cumulative series.
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
def get_contributor_by_email(db: Session, email: str, role: str) -> models.Contributor | None:
    """Return the contributor matching *email* and *role*, or None.

    Because the same email may exist under different roles (member / investor),
    the lookup must always filter on both columns.
    """
    return db.execute(
        select(models.Contributor).where(
            models.Contributor.email == email,
            models.Contributor.role == role,
        )
    ).scalar_one_or_none()


def register_member(db: Session, data: schemas.MemberRegisterRequest) -> models.Contributor:
    """Create a new contributor with a hashed password (self-registration).

    The lookup is scoped to *data.role* so the same email can independently
    register as a 'member' and as an 'investor' — they become two separate
    contributor records, each with its own password and unit balance.
    """
    existing = get_contributor_by_email(db, data.email, data.role)
    if existing is not None:
        if existing.password_hash is not None:
            raise BusinessRuleError(
                f"A {data.role} account with that email already exists."
            )
        # Admin-created contributor (no password yet) claims their account.
        existing.name = data.name.strip()
        existing.category = data.category.strip()
        existing.password_hash = hash_password(data.password)
        db.commit()
        db.refresh(existing)
        return existing

    contributor = models.Contributor(
        name=data.name.strip(),
        email=data.email.strip(),
        role=data.role,
        category=data.category.strip(),
        password_hash=hash_password(data.password),
    )
    db.add(contributor)
    db.commit()
    db.refresh(contributor)
    return contributor


def authenticate_member(db: Session, email: str, password: str, role: str) -> models.Contributor | None:
    """Return the contributor if email + password + role all match, else None.

    A valid investor login will NOT match a member-only account and vice-versa,
    even if the email and password are identical.
    """
    contributor = get_contributor_by_email(db, email, role)
    if contributor is None or contributor.password_hash is None:
        return None
    if not verify_member_password(password, contributor.password_hash):
        return None
    return contributor


def get_member_profile(db: Session, contributor_id: int) -> schemas.MemberProfileOut | None:
    """Return a full personal dashboard profile for one contributor."""
    contributor = get_contributor(db, contributor_id)
    if contributor is None:
        return None

    total = contributor_total_units(db, contributor_id)

    # Rank = position in descending units leaderboard (1 = most units)
    all_contributors = list_contributors(db)
    sorted_contributors = sorted(all_contributors, key=lambda c: c.total_units, reverse=True)
    rank = next(
        (i + 1 for i, c in enumerate(sorted_contributors) if c.id == contributor_id), 0
    )

    # Personal ledger
    entries = db.execute(
        select(models.LedgerEntry)
        .where(models.LedgerEntry.contributor_id == contributor_id)
        .order_by(models.LedgerEntry.date_awarded.desc())
    ).scalars().all()
    ledger = [_entry_to_out(e) for e in entries]

    # Personal growth time series (ascending order)
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
        role=contributor.role,
        category=contributor.category,
        created_at=contributor.created_at,
        total_units=total,
        total_value_eur=_round_units(total) * EUR_PER_UNIT,
        rank=rank,
        ledger=ledger,
        growth_points=growth_points,
    )


# --- Task Submissions --------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _submission_to_out(s: models.TaskSubmission) -> schemas.TaskSubmissionOut:
    return schemas.TaskSubmissionOut(
        id=s.id,
        contributor_id=s.contributor_id,
        contributor_name=s.contributor.name,
        task_description=s.task_description,
        task_reference=s.task_reference,
        remarks=s.remarks,
        status=s.status,
        admin_note=s.admin_note,
        ledger_entry_id=s.ledger_entry_id,
        submitted_at=s.submitted_at,
        resolved_at=s.resolved_at,
    )


def create_submission(
    db: Session, contributor_id: int, data: schemas.TaskSubmissionCreate
) -> models.TaskSubmission:
    """Member submits a task for admin review."""
    sub = models.TaskSubmission(
        contributor_id=contributor_id,
        task_description=data.task_description.strip(),
        task_reference=(data.task_reference.strip() if data.task_reference else None),
        remarks=(data.remarks.strip() if data.remarks else None),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def list_submissions(
    db: Session,
    status: str | None = None,
    contributor_id: int | None = None,
) -> list[schemas.TaskSubmissionOut]:
    """List submissions filtered by status and/or contributor. None = all."""
    q = select(models.TaskSubmission).order_by(models.TaskSubmission.submitted_at.desc())
    if status:
        q = q.where(models.TaskSubmission.status == status)
    if contributor_id is not None:
        q = q.where(models.TaskSubmission.contributor_id == contributor_id)
    rows = db.execute(q).scalars().all()
    return [_submission_to_out(s) for s in rows]


def resolve_submission(
    db: Session,
    submission_id: int,
    data: schemas.SubmissionResolveRequest,
) -> models.TaskSubmission:
    """Admin resolves a submission: award, done, or cancel.

    * ``award``  — units_awarded + approving_reviewer required; creates a ledger entry.
    * ``done``   — marks complete without awarding units; admin_note required.
    * ``cancel`` — rejects/cancels the submission; admin_note required.
    """
    sub = db.get(models.TaskSubmission, submission_id)
    if sub is None:
        raise BusinessRuleError("Submission not found.")
    if sub.status != "pending":
        raise BusinessRuleError(f"Submission is already {sub.status}.")

    now = _utcnow()

    if data.action == "award":
        if not data.units_awarded or not data.approving_reviewer:
            raise BusinessRuleError(
                "units_awarded and approving_reviewer are required to award."
            )
        units = validate_units(data.units_awarded)
        available = remaining_units(db)
        if units > available + 1e-9:
            raise BusinessRuleError(
                f"Award of {units:g} units exceeds the remaining pool of {available:g} units."
            )
        entry = models.LedgerEntry(
            contributor_id=sub.contributor_id,
            task_description=sub.task_description,
            task_reference=sub.task_reference,
            units_awarded=units,
            approving_reviewer=data.approving_reviewer.strip(),
            remarks=data.admin_note,
        )
        db.add(entry)
        db.flush()
        sub.status = "awarded"
        sub.ledger_entry_id = entry.id

    elif data.action == "done":
        sub.status = "done"

    elif data.action == "cancel":
        sub.status = "cancelled"

    sub.admin_note = (data.admin_note.strip() if data.admin_note else None)
    sub.resolved_at = now
    db.commit()
    db.refresh(sub)
    return sub
