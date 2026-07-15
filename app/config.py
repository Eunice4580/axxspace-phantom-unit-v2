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

    # ── Email (Gmail SMTP) ────────────────────────────────────────────────────
    # Set these in your .env / Render environment variables to enable email
    # notifications. Use a Gmail "App Password" (not your normal password):
    #   https://support.google.com/accounts/answer/185833
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465          # 465 = SSL (works on Render); 587 = STARTTLS
    smtp_use_ssl: bool = True     # True → SMTP_SSL (port 465); False → SMTP + STARTTLS (port 587)
    smtp_user: str = ""          # e.g. yourapp@gmail.com
    smtp_password: str = ""      # 16-character Gmail App Password
    # Optional: customise the "From" display name shown to recipients.
    email_from: str = ""         # e.g. "AXXSPACE <noreply@yourdomain.com>"


settings = Settings()
