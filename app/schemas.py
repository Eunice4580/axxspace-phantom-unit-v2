"""Pydantic request/response schemas."""
from __future__ import annotations
from datetime import datetime
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- Auth --------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str

class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"

# --- Contributors ------------------------------------------------------------
class ContributorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=200, description="Must be a valid Gmail address (e.g. user@gmail.com)")
    category: str = Field(..., min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=6)  # admin sets initial password

    @field_validator("email")
    @classmethod
    def validate_gmail(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"[a-zA-Z0-9._%+\-]+@gmail\.com", v):
            raise ValueError("Email must be a valid Gmail address (e.g. user@gmail.com).")
        return v

class ContributorUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)

class ContributorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str | None
    category: str
    created_at: datetime
    is_approved: bool = False
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

class LedgerEntryUpdate(BaseModel):
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

class MemberLoginRequest(BaseModel):
    email: str
    password: str


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)

class MemberTokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    contributor_id: int
    name: str

class MemberProfileOut(BaseModel):
    id: int
    name: str
    email: str | None
    category: str
    created_at: datetime
    total_units: float
    total_value_eur: float
    rank: int
    ledger: list[LedgerEntryOut]
    growth_points: list[GrowthPoint]


# --- Chat --------------------------------------------------------------------

class ChatRoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    invitee_ids: list[int] = Field(default_factory=list)  # contributor IDs to invite


class ChatRoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    created_by_id: int | None
    is_admin_room: bool
    created_at: datetime
    member_ids: list[int] = []


class ChatMessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    room_id: int
    sender_id: int | None
    sender_name: str
    body: str
    sent_at: datetime


# --- Notifications -----------------------------------------------------------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    title: str
    body: str
    is_read: bool
    ref_id: int | None
    created_at: datetime


# --- Investor ----------------------------------------------------------------

class InvestorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    shares: float = Field(..., gt=0, description="Number of shares purchased")
    password: str = Field(..., min_length=6)


class InvestorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    phone: str | None
    shares: float
    share_price_kes: float = 50.0
    total_value_kes: float
    created_at: datetime


class InvestorLoginRequest(BaseModel):
    email: str
    password: str


class InvestorTokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    investor_id: int
    name: str


class InvestorSharePoint(BaseModel):
    date: str
    value_kes: float
    shares: float


class InvestorProfileOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None
    shares: float
    share_price_kes: float
    total_value_kes: float
    created_at: datetime
    # computed fields
    rank: int            # rank among investors by shares
    total_investors: int
    portfolio_pct: float  # what % of total investor shares this investor holds


# --- Task Submissions --------------------------------------------------------

class TaskSubmissionCreate(BaseModel):
    task_title: str = Field(..., min_length=1, max_length=300)
    task_description: str = Field(..., min_length=1)


class TaskSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contributor_id: int
    contributor_name: str
    task_title: str
    task_description: str
    status: str
    units_awarded: float | None
    awarded_at: datetime | None
    submitted_at: datetime


class AwardSubmissionRequest(BaseModel):
    units_awarded: float = Field(..., gt=0)
    approving_reviewer: str = Field(..., min_length=1, max_length=200)
    task_reference: str | None = Field(default=None, max_length=100)
    remarks: str | None = None