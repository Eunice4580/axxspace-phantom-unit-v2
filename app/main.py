"""FastAPI application for the AXXSPACE Phantom Unit Compensation System."""
from __future__ import annotations
import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from app import crud, schemas
from app.auth import (
    create_admin_token, create_member_token, create_investor_token,
    require_admin, require_member, require_investor,
    verify_password, _signer, _ADMIN_SUBJECT
)
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
        is_approved=contributor.is_approved,
        total_units=0.0,
        total_value_eur=0.0,
    )

@app.delete("/api/contributors/{contributor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contributor(
    contributor_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> None:
    if not crud.delete_contributor(db, contributor_id):
        raise HTTPException(status_code=404, detail="Contributor not found.")

@app.put("/api/contributors/{contributor_id}", response_model=schemas.ContributorOut)
def update_contributor(
    contributor_id: int,
    payload: schemas.ContributorUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> schemas.ContributorOut:
    if payload.category not in ELIGIBILITY_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Category must be one of: {', '.join(ELIGIBILITY_CATEGORIES)}",
        )
    contributor = crud.update_contributor(db, contributor_id, payload.name, payload.email, payload.category)
    if contributor is None:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    total = crud.contributor_total_units(db, contributor.id)
    return schemas.ContributorOut(
        id=contributor.id,
        name=contributor.name,
        email=contributor.email,
        category=contributor.category,
        created_at=contributor.created_at,
        is_approved=contributor.is_approved,
        total_units=total,
        total_value_eur=total * EUR_PER_UNIT,
    )

# --- Pending approvals -------------------------------------------------------
@app.get("/api/contributors/pending", response_model=list[schemas.ContributorOut])
def list_pending(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> list[schemas.ContributorOut]:
    return crud.list_pending_contributors(db)

@app.post("/api/contributors/{contributor_id}/approve", response_model=schemas.ContributorOut)
def approve_contributor(
    contributor_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> schemas.ContributorOut:
    contributor = crud.approve_contributor(db, contributor_id)
    if contributor is None:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    total = crud.contributor_total_units(db, contributor.id)
    return schemas.ContributorOut(
        id=contributor.id,
        name=contributor.name,
        email=contributor.email,
        category=contributor.category,
        created_at=contributor.created_at,
        is_approved=contributor.is_approved,
        total_units=total,
        total_value_eur=total * EUR_PER_UNIT,
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
        entry = crud.award_units_with_notify(db, payload)
    except BusinessRuleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return crud._entry_to_out(entry)

@app.delete("/api/ledger/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ledger_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> None:
    if not crud.delete_ledger_entry_with_notify(db, entry_id):
        raise HTTPException(status_code=404, detail="Ledger entry not found.")

@app.put("/api/ledger/{entry_id}", response_model=schemas.LedgerEntryOut)
def update_ledger_entry(
    entry_id: int,
    payload: schemas.LedgerEntryUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> schemas.LedgerEntryOut:
    entry = db.get(crud.models.LedgerEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Ledger entry not found.")
    entry.task_description = payload.task_description
    entry.units_awarded = payload.units_awarded
    entry.approving_reviewer = payload.approving_reviewer
    entry.task_reference = payload.task_reference
    entry.remarks = payload.remarks
    db.commit()
    db.refresh(entry)
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
    # Cross-tab guard: if this email belongs to an investor, block with helpful message
    if crud.is_investor_email(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is an investor account. Please use the Investor tab to log in.",
        )
    contributor = crud.authenticate_member(db, payload.email, payload.password)
    if contributor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
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


@app.post("/api/contributors/{contributor_id}/reset-password", status_code=200)
def admin_reset_contributor_password(
    contributor_id: int,
    payload: schemas.ResetPasswordRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """Admin only: forcibly reset a contributor's password."""
    ok = crud.reset_contributor_password(db, contributor_id, payload.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    return {"ok": True, "message": "Password reset successfully."}


@app.post(\"/api/investors/{investor_id}/reset-password\", status_code=200)
def admin_reset_investor_password(
    investor_id: int,
    payload: schemas.ResetPasswordRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """Admin only: forcibly reset an investor's password."""
    ok = crud.reset_investor_password(db, investor_id, payload.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="Investor not found.")
    return {"ok": True, "message": "Investor password reset successfully."}


# --- Task Submissions --------------------------------------------------------

@app.post(
    "/api/members/submissions",
    response_model=schemas.TaskSubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
def member_submit_task(
    payload: schemas.TaskSubmissionCreate,
    db: Session = Depends(get_db),
    contributor_id: int = Depends(require_member),
) -> schemas.TaskSubmissionOut:
    """Authenticated member submits a completed task for admin review."""
    sub = crud.create_task_submission(db, contributor_id, payload)
    return crud._submission_to_out(sub)


@app.get("/api/members/submissions", response_model=list[schemas.TaskSubmissionOut])
def member_list_submissions(
    db: Session = Depends(get_db),
    contributor_id: int = Depends(require_member),
) -> list[schemas.TaskSubmissionOut]:
    """Return all submissions for the authenticated member."""
    return crud.list_member_submissions(db, contributor_id)


@app.get("/api/admin/submissions", response_model=list[schemas.TaskSubmissionOut])
def admin_list_submissions(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> list[schemas.TaskSubmissionOut]:
    """Admin: list all pending task submissions."""
    return crud.list_pending_submissions(db)


@app.post(
    "/api/admin/submissions/{submission_id}/award",
    response_model=schemas.LedgerEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def admin_award_submission(
    submission_id: int,
    payload: schemas.AwardSubmissionRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> schemas.LedgerEntryOut:
    """Admin awards units for a pending submission, creating a ledger entry."""
    try:
        entry = crud.award_submission(db, submission_id, payload)
    except crud.BusinessRuleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return crud._entry_to_out(entry)

# --- Investor auth & management -----------------------------------------------
@app.post("/api/investors", response_model=schemas.InvestorOut, status_code=201)
def create_investor(
    payload: schemas.InvestorCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> schemas.InvestorOut:
    try:
        investor = crud.create_investor(db, payload)
    except crud.BusinessRuleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return crud._investor_to_out(investor)


@app.get("/api/investors", response_model=list[schemas.InvestorOut])
def list_investors(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> list[schemas.InvestorOut]:
    return crud.list_investors(db)


@app.delete("/api/investors/{investor_id}", status_code=204)
def delete_investor(
    investor_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> None:
    if not crud.delete_investor(db, investor_id):
        raise HTTPException(status_code=404, detail="Investor not found.")


@app.post("/api/investors/login", response_model=schemas.InvestorTokenResponse)
def investor_login(
    payload: schemas.InvestorLoginRequest,
    db: Session = Depends(get_db),
) -> schemas.InvestorTokenResponse:
    # Cross-tab guard: if this email belongs to a member, block with helpful message
    if crud.is_member_email(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is a member account. Please use the Member tab to log in.",
        )
    investor = crud.authenticate_investor(db, payload.email, payload.password)
    if investor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    token = create_investor_token(investor.id)
    return schemas.InvestorTokenResponse(
        token=token, investor_id=investor.id, name=investor.name
    )


@app.get("/api/investors/me", response_model=schemas.InvestorProfileOut)
def investor_me(
    db: Session = Depends(get_db),
    investor_id: int = Depends(require_investor),
) -> schemas.InvestorProfileOut:
    profile = crud.get_investor_profile(db, investor_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Investor not found.")
    return profile

# --- Static frontend ---------------------------------------------------------
@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)

@app.get("/home")
def home_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "home.html")

@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")

@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")

@app.get("/chat")
def chat_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "chat.html")

@app.get("/member")
def member_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "member.html")

@app.get("/investor")
def investor_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "investor.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# Shared auth helper: admin token OR member token
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_caller(
    token_str: str,
) -> tuple[bool, int | None]:
    """
    Returns (is_admin, contributor_id).
    Raises HTTPException on invalid/expired token.
    """
    from itsdangerous import BadSignature, SignatureExpired
    from app.config import settings
    try:
        payload = _signer.unsign(token_str, max_age=settings.token_max_age_seconds).decode()
    except SignatureExpired:
        raise HTTPException(status_code=401, detail="Session expired.")
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid token.")
    if payload == _ADMIN_SUBJECT:
        return True, None
    if payload.startswith("member:"):
        return False, int(payload[7:])
    raise HTTPException(status_code=401, detail="Invalid token subject.")


# ─────────────────────────────────────────────────────────────────────────────
# Notifications — member
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/notifications", response_model=list[schemas.NotificationOut])
def member_notifications(
    db: Session = Depends(get_db),
    contributor_id: int = Depends(require_member),
) -> list[schemas.NotificationOut]:
    rows = crud.list_notifications(db, contributor_id)
    return [schemas.NotificationOut.model_validate(r) for r in rows]


@app.post("/api/notifications/{notification_id}/read", status_code=200)
def mark_member_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    contributor_id: int = Depends(require_member),
) -> dict:
    crud.mark_notification_read(db, notification_id, contributor_id)
    return {"ok": True}


@app.post("/api/notifications/read-all", status_code=200)
def mark_all_member_read(
    db: Session = Depends(get_db),
    contributor_id: int = Depends(require_member),
) -> dict:
    crud.mark_all_notifications_read(db, contributor_id)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Notifications — admin
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/admin/notifications", response_model=list[schemas.NotificationOut])
def admin_notifications(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> list[schemas.NotificationOut]:
    rows = crud.list_notifications(db, None)  # contributor_id=None → admin
    return [schemas.NotificationOut.model_validate(r) for r in rows]


@app.post("/api/admin/notifications/{notification_id}/read", status_code=200)
def mark_admin_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    n = db.get(crud.models.Notification, notification_id)
    if n and n.contributor_id is None:
        n.is_read = True
        db.commit()
    return {"ok": True}


@app.post("/api/admin/notifications/read-all", status_code=200)
def mark_all_admin_read(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    crud.mark_all_notifications_read(db, None)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Chat rooms & messages
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/chat/rooms", response_model=list[schemas.ChatRoomOut])
def list_chat_rooms(
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> list[schemas.ChatRoomOut]:
    is_admin, contributor_id = _resolve_caller(token)
    if is_admin:
        return crud.list_all_rooms(db)
    return crud.list_rooms_for_member(db, contributor_id)  # type: ignore[arg-type]


@app.post("/api/chat/rooms", response_model=schemas.ChatRoomOut, status_code=201)
def create_chat_room(
    payload: schemas.ChatRoomCreate,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> schemas.ChatRoomOut:
    is_admin, contributor_id = _resolve_caller(token)
    room = crud.create_chat_room(
        db,
        name=payload.name,
        creator_contributor_id=contributor_id,
        is_admin_room=is_admin,
        invitee_ids=payload.invitee_ids,
    )
    return crud._room_to_out(room)


@app.get("/api/chat/rooms/{room_id}/messages", response_model=list[schemas.ChatMessageOut])
def get_messages(
    room_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> list[schemas.ChatMessageOut]:
    is_admin, contributor_id = _resolve_caller(token)
    room = crud.get_room(db, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    if not is_admin and not crud.is_room_member(db, room_id, contributor_id):  # type: ignore
        raise HTTPException(status_code=403, detail="Not a member of this room.")
    return crud.list_messages(db, room_id)


@app.post(
    "/api/chat/rooms/{room_id}/messages",
    response_model=schemas.ChatMessageOut,
    status_code=201,
)
def send_message(
    room_id: int,
    payload: schemas.ChatMessageCreate,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> schemas.ChatMessageOut:
    is_admin, contributor_id = _resolve_caller(token)
    room = crud.get_room(db, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    if not is_admin and not crud.is_room_member(db, room_id, contributor_id):  # type: ignore
        raise HTTPException(status_code=403, detail="Not a member of this room.")
    if is_admin:
        sender_name = "Admin"
    else:
        c = crud.get_contributor(db, contributor_id)  # type: ignore
        sender_name = c.name if c else "Member"
    return crud.post_message(db, room_id, contributor_id, sender_name, payload.body)


@app.get("/api/contributors/for-chat", response_model=list[schemas.ContributorOut])
def contributors_for_chat(
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> list[schemas.ContributorOut]:
    """Return all contributors (used to populate invite picker)."""
    _resolve_caller(token)  # just validate token
    return crud.list_contributors(db)


# ─────────────────────────────────────────────────────────────────────────────
# SSE event streams (DB-polling, Render-safe, no new deps)
# ─────────────────────────────────────────────────────────────────────────────

async def _member_event_generator(
    token_str: str,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames: notifications + chat messages."""
    from app.database import SessionLocal
    try:
        is_admin, contributor_id = _resolve_caller(token_str)
    except HTTPException:
        yield "event: error\ndata: unauthorized\n\n"
        return

    last_notif_id = 0
    last_msg_id = 0

    # Bootstrap: find current max IDs so we only push *new* items
    with SessionLocal() as db:
        notifs = crud.list_notifications(db, None if is_admin else contributor_id)
        last_notif_id = notifs[0].id if notifs else 0
        if not is_admin:
            rooms = crud.list_rooms_for_member(db, contributor_id)  # type: ignore
            room_ids = [r.id for r in rooms]
        else:
            rooms = crud.list_all_rooms(db)
            room_ids = [r.id for r in rooms]
        last_msg_id = crud.get_latest_message_id(db, room_ids)

    yield "event: connected\ndata: ok\n\n"

    while True:
        await asyncio.sleep(2)  # poll every 2 seconds
        try:
            with SessionLocal() as db:
                # Check new notifications
                new_notifs = [
                    n for n in crud.list_notifications(db, None if is_admin else contributor_id)
                    if n.id > last_notif_id
                ]
                for n in reversed(new_notifs):
                    last_notif_id = max(last_notif_id, n.id)
                    data = json.dumps({
                        "id": n.id, "kind": n.kind, "title": n.title,
                        "body": n.body, "ref_id": n.ref_id,
                        "created_at": n.created_at.isoformat(),
                    })
                    yield f"event: notification\ndata: {data}\n\n"

                # Check new chat messages
                if not is_admin:
                    rooms = crud.list_rooms_for_member(db, contributor_id)  # type: ignore
                    room_ids = [r.id for r in rooms]
                else:
                    rooms = crud.list_all_rooms(db)
                    room_ids = [r.id for r in rooms]

                new_max = crud.get_latest_message_id(db, room_ids)
                if new_max > last_msg_id:
                    # Fetch only the new messages
                    from sqlalchemy import select
                    from app.models import ChatMessage
                    new_msgs = db.execute(
                        select(ChatMessage)
                        .where(ChatMessage.id > last_msg_id)
                        .where(ChatMessage.room_id.in_(room_ids))
                        .order_by(ChatMessage.sent_at)
                    ).scalars().all()
                    for m in new_msgs:
                        last_msg_id = max(last_msg_id, m.id)
                        data = json.dumps({
                            "id": m.id, "room_id": m.room_id,
                            "sender_id": m.sender_id, "sender_name": m.sender_name,
                            "body": m.body, "sent_at": m.sent_at.isoformat(),
                        })
                        yield f"event: chat_message\ndata: {data}\n\n"
        except Exception:
            # Swallow DB errors; client will reconnect
            await asyncio.sleep(5)


@app.get("/api/events")
async def member_sse(
    token: str = Query(...),
) -> StreamingResponse:
    """SSE stream for members and admin. Caller passes token as query param."""
    return StreamingResponse(
        _member_event_generator(token),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )