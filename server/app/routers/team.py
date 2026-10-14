from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import correction_out, csv_response, date_range, entry_out, entry_rows, hours, iso, user_out
from ..db import get_db
from ..models import Correction, Device, Project, TimeEntry, User, utcnow
from ..security import require_role
from ..tracking import (audit, entries_between, local_day_bounds, open_entry, to_local, visible_users,
                        worked_seconds)

router = APIRouter(prefix="/api/team", tags=["managers"])
manager = require_role("manager", "admin")


class ReviewIn(BaseModel):
    note: str = Field("", max_length=500)


def _scope(db: Session, viewer: User) -> dict[int, User]:
    return {u.id: u for u in visible_users(db, viewer)}


@router.get("/live")
def live(viewer: User = Depends(manager), db: Session = Depends(get_db)):
    users = _scope(db, viewer)
    out = []
    for u in users.values():
        if not u.active:
            continue
        e = open_entry(db, u.id)
        last_seen = db.scalar(select(Device.last_seen_at).where(Device.user_id == u.id, Device.revoked.is_(False))
                              .order_by(Device.last_seen_at.desc()))
        out.append({"user": {"id": u.id, "name": u.name, "department": u.department, "employee_code": u.employee_code},
                    "working": bool(e), "location": e.location if e else None, "since": iso(e.start) if e else None,
                    "source": e.source if e else None, "computer_last_seen": iso(last_seen)})
    out.sort(key=lambda r: (not r["working"], r["user"]["name"]))
    return {"working": sum(r["working"] for r in out), "total": len(out), "people": out}


def _summary(db: Session, viewer: User, start: date | None, end: date | None, department: str | None):
    s, e, a, b = date_range(start, end)
    users = {k: u for k, u in _scope(db, viewer).items() if u.active and (not department or u.department == department)}
    totals = defaultdict(lambda: {"office": 0.0, "remote": 0.0, "days": set(), "review": 0, "unconfirmed": 0})
    by_project: dict = defaultdict(float)
    for entry in entries_between(db, list(users), a, b):
        secs = worked_seconds(entry, a, b)
        t = totals[entry.user_id]
        t[entry.location] += secs
        t["days"].add(to_local(entry.start).date())
        t["review"] += entry.status == "review"
        t["unconfirmed"] += not entry.confirmed and entry.end is not None
        by_project[entry.project_id] += secs
    weeks = ((e - s).days + 1) / 7
    rows = []
    for u in users.values():
        t = totals[u.id]
        total = t["office"] + t["remote"]
        rows.append({"user": {"id": u.id, "name": u.name, "department": u.department, "employee_code": u.employee_code},
                     "office_seconds": round(t["office"]), "remote_seconds": round(t["remote"]),
                     "total_seconds": round(total), "days_worked": len(t["days"]),
                     "target_seconds": round(u.weekly_target_hours * 3600 * weeks), "needs_review": t["review"],
                     "unconfirmed": t["unconfirmed"]})
    rows.sort(key=lambda r: r["user"]["name"])
    names = {p.id: p for p in db.scalars(select(Project))}
    projects = sorted(({"id": pid, "name": names[pid].name if pid in names else "No project",
                        "color": names[pid].color if pid in names else "#8a9a94", "seconds": round(sec)}
                       for pid, sec in by_project.items()), key=lambda x: -x["seconds"])
    return s, e, rows, projects


@router.get("/summary")
def summary(start: date | None = None, end: date | None = None, department: str | None = None,
            viewer: User = Depends(manager), db: Session = Depends(get_db)):
    s, e, rows, projects = _summary(db, viewer, start, end, department)
    departments = sorted({u.department for u in _scope(db, viewer).values() if u.department})
    return {"start": s.isoformat(), "end": e.isoformat(), "rows": rows, "departments": departments,
            "projects": projects}


@router.get("/export.csv")
def export(kind: str = "summary", start: date | None = None, end: date | None = None, department: str | None = None,
           viewer: User = Depends(manager), db: Session = Depends(get_db)):
    if kind == "entries":
        s, e, a, b = date_range(start, end)
        users = {k: u for k, u in _scope(db, viewer).items() if not department or u.department == department}
        rows = entry_rows(entries_between(db, list(users), a, b), users)
    else:
        s, e, data, _ = _summary(db, viewer, start, end, department)
        rows = [["Employee code", "Name", "Department", "Office hours", "Remote hours", "Total hours",
                 "Target hours", "Days worked", "Entries to review"]]
        rows += [[r["user"]["employee_code"] or "", r["user"]["name"], r["user"]["department"] or "",
                  hours(r["office_seconds"]), hours(r["remote_seconds"]), hours(r["total_seconds"]),
                  hours(r["target_seconds"]), r["days_worked"], r["needs_review"]] for r in data]
    audit(db, viewer, "export", kind=kind, start=s.isoformat(), end=e.isoformat())
    db.commit()
    return csv_response(f"timesheet-{kind}-{s}-{e}.csv", rows)


@router.get("/entries")
def user_entries(user_id: int, start: date | None = None, end: date | None = None,
                 viewer: User = Depends(manager), db: Session = Depends(get_db)):
    if user_id not in _scope(db, viewer):
        raise HTTPException(404, "That person is not on your team.")
    _, _, a, b = date_range(start, end)
    return [entry_out(e) for e in entries_between(db, [user_id], a, b)]


@router.get("/corrections")
def corrections(status: str = "pending", viewer: User = Depends(manager), db: Session = Depends(get_db)):
    ids = [i for i in _scope(db, viewer) if i != viewer.id or viewer.role == "admin"]
    rows = db.scalars(select(Correction).where(Correction.user_id.in_(ids), Correction.status == status)
                      .order_by(Correction.created_at.desc()).limit(200))
    return [correction_out(c) for c in rows]


def _review(db: Session, viewer: User, cid: int) -> Correction:
    c = db.get(Correction, cid)
    if not c or c.user_id not in _scope(db, viewer):
        raise HTTPException(404, "That request was not found.")
    if c.user_id == viewer.id and viewer.role != "admin":
        raise HTTPException(403, "Your own requests must be approved by your manager or an admin.")
    if c.status != "pending":
        raise HTTPException(409, "This request was already reviewed.")
    return c


@router.post("/corrections/{cid}/approve")
def approve(cid: int, body: ReviewIn, viewer: User = Depends(manager), db: Session = Depends(get_db)):
    c = _review(db, viewer, cid)
    if c.kind == "add":
        db.add(TimeEntry(user_id=c.user_id, start=c.start, end=c.end, break_minutes=c.break_minutes,
                         location=c.location or "remote", source="manual", note=c.reason, confirmed=True))
    else:
        entry = db.get(TimeEntry, c.entry_id or 0)
        if not entry:
            raise HTTPException(409, "The entry no longer exists.")
        if c.kind == "delete":
            db.delete(entry)
        else:
            entry.start, entry.end, entry.break_minutes = c.start, c.end, c.break_minutes
            entry.location, entry.status = c.location or entry.location, "ok"
            entry.note = (entry.note + " | " if entry.note else "") + f"Corrected: {c.reason}"
    c.status, c.reviewer_id, c.reviewer_note, c.reviewed_at = "approved", viewer.id, body.note, utcnow()
    audit(db, viewer, "correction_approved", c.user, correction=c.id, kind=c.kind)
    db.commit()
    return correction_out(c)


@router.post("/corrections/{cid}/reject")
def reject(cid: int, body: ReviewIn, viewer: User = Depends(manager), db: Session = Depends(get_db)):
    c = _review(db, viewer, cid)
    c.status, c.reviewer_id, c.reviewer_note, c.reviewed_at = "rejected", viewer.id, body.note, utcnow()
    audit(db, viewer, "correction_rejected", c.user, correction=c.id)
    db.commit()
    return correction_out(c)
