"""Business logic: contributor management, unit awards and dashboard aggregation."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import EUR_PER_UNIT, TOTAL_POOL_UNITS, UNIT_INCREMENT


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
    contributor = models.Contributor(
        name=data.name.strip(),
        email=(data.email.strip() if data.email else None),
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
