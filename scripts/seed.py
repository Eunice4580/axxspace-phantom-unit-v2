"""Seed the database with sample contributors and awards for demo/testing.

Usage:
    python -m scripts.seed

Awards are spread across several past dates so the growth charts show a real trend.
Running it multiple times will add more sample data.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app import models
from app.crud import validate_units
from app.database import SessionLocal, init_db

SAMPLE = [
    ("Amani Okoth", "amani@axxspace.io", "Core Team Member"),
    ("Lucia Moreau", "lucia@axxspace.io", "Department Leader"),
    ("Ben Carter", "ben@axxspace.io", "Project Contributor"),
    ("Priya Nair", "priya@axxspace.io", "Intern"),
    ("Tom Reyes", "tom@axxspace.io", "Volunteer"),
]

TASKS = [
    ("Implemented onboarding flow", "TASK-101", 0.5, "Standard Task"),
    ("Fixed payment bug", "TASK-102", 0.2, "Minor Task"),
    ("Led Q2 product launch", "TASK-103", 0.9, "Strategic Task"),
    ("Designed new dashboard", "TASK-104", 0.6, "Major Task"),
    ("Wrote API documentation", "TASK-105", 0.3, "Standard Task"),
    ("Triaged support tickets", "TASK-106", 0.1, "Minor Task"),
    ("Closed enterprise partnership", "TASK-107", 1.0, "Strategic Task"),
]


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        contributors = []
        for name, email, category in SAMPLE:
            c = models.Contributor(name=name, email=email, category=category)
            db.add(c)
            contributors.append(c)
        db.commit()
        for c in contributors:
            db.refresh(c)

        now = datetime.now(timezone.utc)
        for i in range(18):
            c = random.choice(contributors)
            desc, ref, units, _tier = random.choice(TASKS)
            day = now - timedelta(days=random.randint(0, 60))
            db.add(
                models.LedgerEntry(
                    contributor_id=c.id,
                    task_description=desc,
                    task_reference=f"{ref}-{i:02d}",
                    units_awarded=validate_units(units),
                    approving_reviewer=random.choice(["COO", "CFO", "Team Lead"]),
                    remarks=random.choice(["Verified", "Excellent", "Approved", None]),
                    date_awarded=day,
                )
            )
        db.commit()
        print("Seeded sample contributors and awards.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
