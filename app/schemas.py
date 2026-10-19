"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --- Auth --------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"


# --- Contributors ------------------------------------------------------------
class ContributorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    role: str = Field(default="member", pattern="^(member|investor)$")


class ContributorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None
    role: str
    category: str
    created_at: datetime
    total_units: float = 0.0
    total_value_eur: float = 0.0


# --- Ledger ------------------------------------------------------------------
class LedgerEntryCreate(BaseModel):
    contributor_id: int
    task_description: str = Field(..., min_length=1)
    units_awarded: float = Field(..., gt=0)
    approving_reviewer: str = Field(..., min_length=1, max_length=200)
    task_reference: str | None = Field(default=None, max_length=100)
    remarks: str | None = None


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contributor_id: int
    contributor_name: str
    task_description: str
    task_reference: str | None
    units_awarded: float
    value_eur: float
    approving_reviewer: str
    remarks: str | None
    date_awarded: datetime


# --- Stats / dashboard -------------------------------------------------------
class PoolStats(BaseModel):
    total_pool_units: float
    allocated_units: float
    remaining_units: float
    allocated_pct: float
    eur_per_unit: float
    total_pool_value_eur: float
    allocated_value_eur: float
    contributor_count: int
    award_count: int


class GrowthPoint(BaseModel):
    date: str
    cumulative_units: float


class ContributorGrowth(BaseModel):
    contributor_id: int
    name: str
    points: list[GrowthPoint]


class GrowthResponse(BaseModel):
    overall: list[GrowthPoint]
    per_contributor: list[ContributorGrowth]


# --- Member Auth -------------------------------------------------------------
class MemberRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=200)
    password: str = Field(..., min_length=6)
    category: str = Field(..., min_length=1, max_length=100)
    role: str = Field(default="member", pattern="^(member|investor)$")


class MemberLoginRequest(BaseModel):
    email: str
    password: str
    role: str = Field(default="member", pattern="^(member|investor)$")


class MemberTokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    contributor_id: int
    name: str


class MemberProfileOut(BaseModel):
    id: int
    name: str
    email: str | None
    role: str
    category: str
    created_at: datetime
    total_units: float
    total_value_eur: float
    rank: int
    ledger: list[LedgerEntryOut]
    growth_points: list[GrowthPoint]


# --- Task Submissions ---------------------------------------------------------
class TaskSubmissionCreate(BaseModel):
    """Sent by a member when they submit a task for review."""
    task_description: str = Field(..., min_length=1)
    task_reference: str | None = Field(default=None, max_length=100)
    remarks: str | None = None


class SubmissionResolveRequest(BaseModel):
    """Sent by the admin to award, reject, or mark a submission as done."""
    action: str = Field(..., pattern="^(award|done|cancel)$")
    admin_note: str | None = None
    # Required only when action='award'
    units_awarded: float | None = None
    approving_reviewer: str | None = None


class TaskSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contributor_id: int
    contributor_name: str
    task_description: str
    task_reference: str | None
    remarks: str | None
    status: str
    admin_note: str | None
    ledger_entry_id: int | None
    submitted_at: datetime
    resolved_at: datetime | None
