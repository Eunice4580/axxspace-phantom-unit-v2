# AXXSPACE Phantom Unit Compensation System v1.0

A full-stack web application implementing the **AXXSPACE Phantom Unit Compensation System** —
a structured system for recognising and rewarding contributors with **Contribution Units**, with
a graphical dashboard that shows the growth of all accounts over time.

> Contribution Units are a recognition & reward mechanism only. They do **not** represent shares,
> equity, voting rights, board membership or legal ownership of AXXSPACE (spec §9).

## Features

- **Admin console** (`/admin`): password-protected. Create contributor accounts and award units.
- **Contribution Unit Pool**: fixed pool of **1,000 units** with live allocated / remaining tracking.
- **Unit reference value**: `0.1 unit = €1`, `1.0 unit = €10` → full pool reference value **€10,000** (spec §3).
- **Fractional units**: awards must be in **0.1 increments** (0.1 … 1.0), enforced server-side (spec §2.2).
- **Eligibility categories**: Core Team Member, Department Leader, Intern, Volunteer, Project
  Contributor, Strategic Partner, Other (spec §4).
- **Task tiers** as award hints: Minor (0.1–0.2), Standard (0.3–0.5), Major (0.6–0.8), Strategic (0.9–1.0) (spec §5).
- **Contribution Ledger** (spec §7): contributor, task description, task reference #, units awarded,
  date awarded, total units held, approving reviewer, remarks.
- **Public growth dashboard** (`/`): cumulative pool growth, per-account growth and current holdings,
  plus the full ledger.
- **Clean REST API + SQLite** by default — switch `DATABASE_URL` to your business Postgres/MySQL to integrate.

## Tech stack

- **Backend**: FastAPI, SQLAlchemy 2.0, Pydantic v2
- **Frontend**: static HTML/CSS/JS with [Chart.js](https://www.chartjs.org/) (no build step)
- **Database**: SQLite by default (any SQLAlchemy-supported DB via `DATABASE_URL`)

## Quick start

```bash
# 1. Install (uses uv; pip works too)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 2. (optional) seed demo data so the charts have content
python -m scripts.seed

# 3. Run
uvicorn app.main:app --reload --port 8000
```

Then open:
- Dashboard: http://localhost:8000/
- Admin: http://localhost:8000/admin (default password `axxspace-admin` — change via `ADMIN_PASSWORD`)

## Configuration

Copy `.env.example` to `.env` and override:

| Variable         | Default                  | Purpose                                              |
|------------------|--------------------------|------------------------------------------------------|
| `DATABASE_URL`   | `sqlite:///./axxspace.db`| Database connection (point at the business DB here). |
| `ADMIN_PASSWORD` | `axxspace-admin`         | Admin login password.                                |
| `SECRET_KEY`     | `dev-secret-change-me`   | Signs admin session tokens.                          |

### Connecting the main website database

The app talks to its database only through SQLAlchemy, so integrating with the main business
database is a configuration change, not a code change:

```bash
# Postgres
DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname
# MySQL
DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname
```

Install the matching driver (`psycopg[binary]` or `pymysql`) and the tables are created automatically
on startup. The REST API (`/api/...`) can then be consumed by the main website's frontend.

## API

| Method | Path                 | Auth  | Description                          |
|--------|----------------------|-------|--------------------------------------|
| POST   | `/api/auth/login`    | —     | Exchange admin password for a token. |
| GET    | `/api/config`        | —     | Pool size, unit value, categories, tiers. |
| GET    | `/api/contributors`  | —     | List accounts with total units held. |
| POST   | `/api/contributors`  | admin | Create a contributor account.        |
| GET    | `/api/ledger`        | —     | Full contribution ledger.            |
| POST   | `/api/ledger`        | admin | Award units (validated against pool).|
| GET    | `/api/stats`         | —     | Pool / value summary.                |
| GET    | `/api/growth`        | —     | Cumulative growth time series.       |

## Tests & linting

```bash
pytest           # run the test suite
ruff check .     # lint
```
# redeploy
