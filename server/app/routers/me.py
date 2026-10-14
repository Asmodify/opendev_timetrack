import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import (correction_out, csv_response, date_range, entry_out, entry_rows, iso, office_out,
                      project_out, to_utc_naive, user_out)
from ..config import settings
from ..db import get_db
from ..models import LOCATIONS, Correction, Device, OfficeLocation, PairingCode, Project, TimeEntry, User, utcnow
from ..security import current_user, hash_token
from ..tracking import (audit, client_ip, close_entry, entries_between, local_day_bounds, local_today,
                        location_for, open_entry, start_entry, week_start, worked_seconds)

router = APIRouter(prefix="/api/me", tags=["me"])


class ConsentIn(BaseModel):
    accept: bool


class ClockIn(BaseModel):
    note: str = Field("", max_length=300)
    project_id: int | None = None


class EntryPatch(BaseModel):
    project_id: int | None = None
    clear_project: bool = False
    note: str | None = Field(None, max_length=300)
    confirmed: bool | None = None


class ConfirmDayIn(BaseModel):
    date: date


class PhoneIn(BaseModel):
    device_name: str = Field(min_length=1, max_length=128)
    platform: str = Field("", max_length=64)


class CorrectionIn(BaseModel):
    kind: str = Field(pattern="^(add|edit|delete)$")
    entry_id: int | None = None
    start: str | None = None
    end: str | None = None
    break_minutes: int = Field(0, ge=0, le=600)
    location: str | None = None
    reason: str = Field(min_length=3, max_length=500)


@router.get("")
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry = open_entry(db, user.id)
    return {
        "user": user_out(user),
        "company": settings.company_name,
        "timezone": str(settings.timezone),
        "consent_version": settings.consent_version,
        "idle_timeout_minutes": settings.idle_timeout_minutes,
        "here": location_for(client_ip(request)),
        "running": entry_out(entry) if entry else None,
    }


@router.post("/consent")
def consent(body: ConsentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.accept:
        user.consent_version, user.consent_at = settings.consent_version, utcnow()
        audit(db, user, "consent_given", user, version=settings.consent_version)
    else:
        user.consent_version, user.consent_at = None, None
        entry = open_entry(db, user.id)
        if entry and entry.source == "agent":
            close_entry(entry)
        audit(db, user, "consent_withdrawn", user)
    db.commit()
    return user_out(user)


@router.post("/clock-in")
def clock_in(body: ClockIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry = open_entry(db, user.id)
    if entry:
        if entry.source == "agent":
            # Take over from the desktop helper so the session doesn't end when the computer goes idle.
            close_entry(entry)
        else:
            raise HTTPException(409, "You're already clocked in.")
    entry = start_entry(db, user, location_for(client_ip(request)), "web", note=body.note.strip(),
                        project_id=_project_id(db, body.project_id))
    db.commit()
    return entry_out(entry)


@router.post("/clock-out")
def clock_out(user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry = open_entry(db, user.id)
    if not entry:
        raise HTTPException(409, "You're not clocked in.")
    close_entry(entry)
    db.commit()
    return entry_out(entry)


def _project_id(db: Session, project_id: int | None) -> int | None:
    if project_id is None:
        return None
    p = db.get(Project, project_id)
    if not p or not p.active:
        raise HTTPException(400, "That project is not available.")
    return p.id


@router.get("/projects")
def projects(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [project_out(p) for p in db.scalars(select(Project).where(Project.active.is_(True)).order_by(Project.name))]


@router.get("/offices")
def offices(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [office_out(o) for o in db.scalars(select(OfficeLocation).where(OfficeLocation.active.is_(True)))]


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Workers can tag, annotate and confirm their own entries. Changing times goes through a correction."""
    e = db.get(TimeEntry, entry_id)
    if not e or e.user_id != user.id:
        raise HTTPException(404, "That entry was not found.")
    if body.clear_project:
        e.project_id = None
    elif body.project_id is not None:
        e.project_id = _project_id(db, body.project_id)
    if body.note is not None:
        e.note = body.note.strip()
    if body.confirmed is not None:
        if body.confirmed and e.end is None:
            raise HTTPException(400, "Clock out before confirming this session.")
        e.confirmed = body.confirmed
    db.commit()
    return entry_out(e)


@router.post("/confirm-day")
def confirm_day(body: ConfirmDayIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a, b = local_day_bounds(body.date)
    rows = [e for e in entries_between(db, [user.id], a, b) if e.end is not None and not e.confirmed]
    for e in rows:
        e.confirmed = True
    db.commit()
    return {"confirmed": len(rows)}


@router.post("/phone")
def register_phone(body: PhoneIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The phone app calls this right after sign-in and keeps the returned token instead of a short session."""
    token = secrets.token_urlsafe(32)
    d = Device(user_id=user.id, name=body.device_name.strip(), platform=body.platform, kind="phone",
               token_hash=hash_token(token), last_seen_at=utcnow())
    db.add(d)
    db.flush()
    audit(db, user, "device_paired", user, device=d.name, kind="phone")
    db.commit()
    return {"token": token, "device_id": d.id}


@router.get("/summary")
def summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = local_today()
    ws = week_start(today)
    ms = today.replace(day=1)
    a, b = local_day_bounds(min(ws, ms))[0], local_day_bounds(today)[1]
    entries = entries_between(db, [user.id], a, b)

    def total(day_from: date, day_to: date, loc: str | None = None) -> float:
        lo, hi = local_day_bounds(day_from)[0], local_day_bounds(day_to)[1]
        return sum(worked_seconds(e, lo, hi) for e in entries if loc is None or e.location == loc)

    days = []
    for i in range(7):
        d = ws + timedelta(days=i)
        days.append({"date": d.isoformat(), **{loc: round(total(d, d, loc)) for loc in LOCATIONS}})
    return {
        "today": round(total(today, today)),
        "week": round(total(ws, ws + timedelta(days=6))),
        "month": round(total(ms, today)),
        "week_by_location": {loc: round(total(ws, ws + timedelta(days=6), loc)) for loc in LOCATIONS},
        "week_days": days,
        "weekly_target_hours": user.weekly_target_hours,
    }


@router.get("/entries")
def my_entries(start: date | None = None, end: date | None = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    _, _, a, b = date_range(start, end)
    return [entry_out(e) for e in entries_between(db, [user.id], a, b)]


@router.get("/export.csv")
def my_export(start: date | None = None, end: date | None = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    s, e, a, b = date_range(start, end)
    rows = entry_rows(entries_between(db, [user.id], a, b), {user.id: user})
    return csv_response(f"hours-{user.employee_code or user.id}-{s}-{e}.csv", rows)


@router.get("/corrections")
def my_corrections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Correction).where(Correction.user_id == user.id)
                      .order_by(Correction.created_at.desc()).limit(50))
    return [correction_out(c) for c in rows]


@router.post("/corrections")
def request_correction(body: CorrectionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = Correction(user_id=user.id, kind=body.kind, reason=body.reason.strip(), break_minutes=body.break_minutes)
    if body.kind in ("edit", "delete"):
        entry = db.get(TimeEntry, body.entry_id or 0)
        if not entry or entry.user_id != user.id:
            raise HTTPException(404, "That entry was not found.")
        if entry.end is None:
            raise HTTPException(400, "Clock out before changing a running session.")
        c.entry_id = entry.id
    if body.kind in ("add", "edit"):
        if not body.start or not body.end:
            raise HTTPException(400, "Give a start and end time.")
        try:
            c.start = to_utc_naive(datetime.fromisoformat(body.start.replace("Z", "+00:00")))
            c.end = to_utc_naive(datetime.fromisoformat(body.end.replace("Z", "+00:00")))
        except ValueError:
            raise HTTPException(400, "The start or end time is not a valid date and time.")
        span = (c.end - c.start).total_seconds()
        if span <= 0:
            raise HTTPException(400, "The end time must be after the start time.")
        if span > settings.max_shift_hours * 3600:
            raise HTTPException(400, f"A single entry can't be longer than {settings.max_shift_hours} hours.")
        if body.break_minutes * 60 >= span:
            raise HTTPException(400, "The break is longer than the shift.")
        if c.end > utcnow() + timedelta(minutes=5):
            raise HTTPException(400, "You can't log hours in the future.")
        c.location = body.location if body.location in LOCATIONS else "remote"
    db.add(c)
    audit(db, user, "correction_requested", user, kind=body.kind)
    db.commit()
    return correction_out(c)


@router.post("/pairing-code")
def pairing_code(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.consent_version != settings.consent_version:
        raise HTTPException(403, "Read and accept the tracking notice before linking a computer.")
    code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    db.add(PairingCode(user_id=user.id, code_hash=hash_token(code), expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    return {"code": code, "expires_in_minutes": 10}


@router.get("/devices")
def my_devices(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Device).where(Device.user_id == user.id, Device.revoked.is_(False)))
    return [{"id": d.id, "name": d.name, "platform": d.platform, "kind": d.kind, "created_at": iso(d.created_at),
             "last_seen_at": iso(d.last_seen_at)} for d in rows]


@router.delete("/devices/{device_id}")
def remove_device(device_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "That computer was not found.")
    d.revoked = True
    audit(db, user, "device_removed", user, device=d.name)
    db.commit()
    return {"ok": True}
