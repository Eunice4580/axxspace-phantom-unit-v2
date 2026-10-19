"""API and business-rule tests for the AXXSPACE compensation system."""

from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use an isolated temp SQLite DB before importing the app modules.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["ADMIN_PASSWORD"] = "test-pass"
os.environ["SECRET_KEY"] = "test-secret"

from app import database  # noqa: E402
from app.config import settings  # noqa: E402

# Rebind the engine/session to the temp DB for the test run.
database.engine = create_engine(
    settings.database_url, connect_args={"check_same_thread": False}, future=True
)
database.SessionLocal = sessionmaker(
    bind=database.engine, autoflush=False, autocommit=False, future=True
)

# Create the schema on the temp engine (TestClient is not used as a context manager,
# so the lifespan/startup hook does not run automatically).
from app import models  # noqa: E402,F401
from app.main import app  # noqa: E402

database.Base.metadata.create_all(bind=database.engine)

client = TestClient(app)


def _auth_headers() -> dict[str, str]:
    res = client.post("/api/auth/login", json={"password": "test-pass"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_health_and_config():
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert cfg["total_pool_units"] == 1000.0
    assert cfg["eur_per_unit"] == 10.0
    assert "Core Team Member" in cfg["categories"]


def test_login_rejects_bad_password():
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401


def test_create_contributor_requires_auth():
    res = client.post("/api/contributors", json={"name": "X", "category": "Intern"})
    assert res.status_code == 401


def test_award_flow_and_pool_accounting():
    headers = _auth_headers()

    c = client.post(
        "/api/contributors",
        json={"name": "Alice", "email": "alice@gmail.com", "category": "Core Team Member"},
        headers=headers,
    )
    assert c.status_code == 201, c.text
    cid = c.json()["id"]

    award = client.post(
        "/api/ledger",
        json={
            "contributor_id": cid,
            "task_description": "Built the landing page",
            "task_reference": "TASK-001",
            "units_awarded": 0.5,
            "approving_reviewer": "COO",
            "remarks": "Great work",
        },
        headers=headers,
    )
    assert award.status_code == 201, award.text
    assert award.json()["units_awarded"] == 0.5
    assert award.json()["value_eur"] == 5.0  # 0.5 unit * €10

    stats = client.get("/api/stats").json()
    assert stats["allocated_units"] == 0.5
    assert stats["remaining_units"] == 999.5
    assert stats["allocated_value_eur"] == 5.0

    contributors = client.get("/api/contributors").json()
    alice = next(x for x in contributors if x["id"] == cid)
    assert alice["total_units"] == 0.5


def test_rejects_non_tenth_increment():
    headers = _auth_headers()
    cid = client.post(
        "/api/contributors", json={"name": "Bob", "email": "bob@gmail.com", "category": "Intern"}, headers=headers
    ).json()["id"]
    res = client.post(
        "/api/ledger",
        json={
            "contributor_id": cid,
            "task_description": "odd amount",
            "units_awarded": 0.15,
            "approving_reviewer": "CFO",
        },
        headers=headers,
    )
    assert res.status_code == 400
    assert "increments of 0.1" in res.json()["detail"]


def test_rejects_award_exceeding_pool():
    headers = _auth_headers()
    cid = client.post(
        "/api/contributors", json={"name": "Carol", "email": "carol@gmail.com", "category": "Volunteer"}, headers=headers
    ).json()["id"]
    res = client.post(
        "/api/ledger",
        json={
            "contributor_id": cid,
            "task_description": "too big",
            "units_awarded": 1001.0,
            "approving_reviewer": "COO",
        },
        headers=headers,
    )
    assert res.status_code == 400
    assert "exceeds the remaining pool" in res.json()["detail"]


def test_invalid_category_rejected():
    headers = _auth_headers()
    res = client.post(
        "/api/contributors", json={"name": "Dan", "category": "Wizard"}, headers=headers
    )
    assert res.status_code == 422


def test_growth_series_is_cumulative():
    headers = _auth_headers()
    cid = client.post(
        "/api/contributors",
        json={"name": "Eve", "email": "eve@gmail.com", "category": "Project Contributor"},
        headers=headers,
    ).json()["id"]
    for amount in (0.2, 0.3):
        client.post(
            "/api/ledger",
            json={
                "contributor_id": cid,
                "task_description": "task",
                "units_awarded": amount,
                "approving_reviewer": "COO",
            },
            headers=headers,
        )
    growth = client.get("/api/growth").json()
    assert growth["overall"], "overall series should not be empty"
    assert growth["overall"][-1]["cumulative_units"] >= 0.5
