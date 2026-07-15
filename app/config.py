"""Application configuration and the fixed business rules of the compensation plan.

The constants in this module encode the AXXSPACE Phantom Unit Compensation System v1.0
specification (the Contribution Unit Pool, the unit reference value and the task tiers).
They are intentionally defined in one place so the rules stay consistent across the API,
the validation logic and the dashboard.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Contribution Unit Pool (spec section 2) ---------------------------------
# Total pool of Contribution Units maintained until bought back by AXXSPACE.
TOTAL_POOL_UNITS: float = 1000.0

# Units are divisible into ten equal parts: 0.1, 0.2, ... 1.0 (spec section 2.2).
UNIT_INCREMENT: float = 0.1

# --- Unit reference value (spec section 3) -----------------------------------
# 0.1 Contribution Unit = EUR 1, therefore 1.0 Unit = EUR 10.
EUR_PER_UNIT: float = 10.0

# --- Eligibility categories (spec section 4) ---------------------------------
ELIGIBILITY_CATEGORIES: list[str] = [
    "Core Team Member",
    "Department Leader",
    "Intern",
    "Volunteer",
    "Project Contributor",
    "Strategic Partner",
    "Other",
]

# --- Task-based reward tiers (spec section 5) ---------------------------------
# Suggested allocation ranges shown to admins when awarding units.
TASK_TIERS: list[dict[str, object]] = [
    {"name": "Minor Task", "min": 0.1, "max": 0.2},
    {"name": "Standard Task", "min": 0.3, "max": 0.5},
    {"name": "Major Task", "min": 0.6, "max": 0.8},
    {"name": "Strategic Task", "min": 0.9, "max": 1.0},
]


class Settings(BaseSettings):
    """Runtime settings sourced from environment variables (or a .env file).

    ADMIN_PASSWORD and SECRET_KEY should always be overridden in production. The defaults
    exist only so the app runs out of the box for local development and testing.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AXXSPACE Phantom Unit Compensation System"
    app_version: str = "1.0"

    # Database URL. Defaults to a local SQLite file; point this at the business
    # Postgres/MySQL database to integrate with the main website.
    database_url: str = "sqlite:///./axxspace.db"

    @field_validator("database_url", mode="before")
    @classmethod
    def strip_database_url(cls, v: str) -> str:
        """Strip accidental whitespace/newlines that Render's UI can add on paste."""
        return str(v).strip()

    # Admin authentication.
    admin_password: str = "axxspace-admin"
    secret_key: str = "dev-secret-change-me"
    # Issued admin tokens are valid for this many seconds.
    token_max_age_seconds: int = 60 * 60 * 8  # 8 hours

    # ── Email (Brevo API) ─────────────────────────────────────────────────────
    # Brevo (formerly Sendinblue) sends via HTTPS — works on Render free tier.
    # Sign up free at https://brevo.com → SMTP & API → API Keys → Create API Key
    # Then set BREVO_API_KEY in your Render environment variables.
    # Free tier: 300 emails/day, sends to ANY email, no domain required.
    brevo_api_key: str = ""         # e.g. xkeysib-xxxxxxxxx
    email_from_name: str = "AXXSPACE"
    email_from_address: str = "phantomunitsaxxspace@gmail.com"


settings = Settings()
