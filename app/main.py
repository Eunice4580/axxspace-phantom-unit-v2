"""FastAPI application for the AXXSPACE Phantom Unit Compensation System."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app import crud, schemas
from app.auth import create_admin_token, create_member_token, require_admin, require_member, verify_password
from app.config import (
    ELIGIBILITY_CATEGORIES,
    EUR_PER_UNIT,
    TASK_TIERS,
    TOTAL_POOL_UNITS,
    settings,
)
from app.crud import BusinessRuleError
from app.database import get_db, init_db

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)


# --- Meta --------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


@app.get("/api/config")
def get_config() -> dict[str, object]:
    """Public, non-sensitive configuration used to drive the UI forms."""
    return {
        "total_pool_units": TOTAL_POOL_UNITS,
        "eur_per_unit": EUR_PER_UNIT,
        "categories": ELIGIBILITY_CATEGORIES,
        "task_tiers": TASK_TIERS,
    }


# --- Auth --------------------------------------------------------------------
@app.post("/api/auth/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest) -> schemas.TokenResponse:
    if not verify_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect admin password."
        )
    return schemas.TokenResponse(token=create_admin_token())


# --- Contributors ------------------------------------------------------------
@app.get("/api/contributors", response_model=list[schemas.ContributorOut])
def list_contributors(db: Session = Depends(get_db)) -> list[schemas.ContributorOut]:
    return crud.list_contributors(db)


@app.post(
    "/api/contributors",
    response_model=schemas.ContributorOut,
    status_code=status.HTTP_201_CREATED,
)
def create_contributor(
    payload: schemas.ContributorCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> schemas.ContributorOut:
    if payload.category not in ELIGIBILITY_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Category must be one of: {', '.join(ELIGIBILITY_CATEGORIES)}",
        )
    contributor = crud.create_contributor(db, payload)
    return schemas.ContributorOut(
        id=contributor.id,
        name=contributor.name,
        email=contributor.email,
        category=contributor.category,
        created_at=contributor.created_at,
        total_units=0.0,
        total_value_eur=0.0,
    )


# --- Ledger ------------------------------------------------------------------
@app.get("/api/ledger", response_model=list[schemas.LedgerEntryOut])
def list_ledger(db: Session = Depends(get_db)) -> list[schemas.LedgerEntryOut]:
    return crud.list_ledger(db)


@app.post(
    "/api/ledger",
    response_model=schemas.LedgerEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def award_units(
    payload: schemas.LedgerEntryCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> schemas.LedgerEntryOut:
    try:
        entry = crud.award_units(db, payload)
    except BusinessRuleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return crud._entry_to_out(entry)


# --- Dashboard ---------------------------------------------------------------
@app.get("/api/stats", response_model=schemas.PoolStats)
def stats(db: Session = Depends(get_db)) -> schemas.PoolStats:
    return crud.pool_stats(db)


@app.get("/api/growth", response_model=schemas.GrowthResponse)
def growth(db: Session = Depends(get_db)) -> schemas.GrowthResponse:
    return crud.growth(db)


# --- Member auth & profile --------------------------------------------------
@app.post("/api/members/register", response_model=schemas.MemberTokenResponse, status_code=201)
def member_register(
    payload: schemas.MemberRegisterRequest,
    db: Session = Depends(get_db),
) -> schemas.MemberTokenResponse:
    from app.config import ELIGIBILITY_CATEGORIES
    if payload.category not in ELIGIBILITY_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Category must be one of: {', '.join(ELIGIBILITY_CATEGORIES)}",
        )
    try:
        contributor = crud.register_member(db, payload)
    except crud.BusinessRuleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    token = create_member_token(contributor.id)
    return schemas.MemberTokenResponse(
        token=token, contributor_id=contributor.id, name=contributor.name
    )


@app.post("/api/members/login", response_model=schemas.MemberTokenResponse)
def member_login(
    payload: schemas.MemberLoginRequest,
    db: Session = Depends(get_db),
) -> schemas.MemberTokenResponse:
    contributor = crud.authenticate_member(db, payload.email, payload.password)
    if contributor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    token = create_member_token(contributor.id)
    return schemas.MemberTokenResponse(
        token=token, contributor_id=contributor.id, name=contributor.name
    )


@app.get("/api/members/me", response_model=schemas.MemberProfileOut)
def member_me(
    db: Session = Depends(get_db),
    contributor_id: int = Depends(require_member),
) -> schemas.MemberProfileOut:
    profile = crud.get_member_profile(db, contributor_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    return profile


# --- Static frontend ---------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/member")
def member_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "member.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
