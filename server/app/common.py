import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from fastapi.responses import Response

from .config import settings
from .models import Correction, TimeEntry, User
from .tracking import local_day_bounds, local_today, to_local, week_start, worked_seconds


def to_utc_naive(dt: datetime) -> datetime:
    """Datetimes from the browser carry an offset; a naive one is read as company local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=settings.timezone)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def date_range(start: date | None, end: date | None) -> tuple[date, date, datetime, datetime]:
    """Inclusive local dates -> UTC [a, b). Defaults to the current week."""
    start = start or week_start(local_today())
    end = end or start + timedelta(days=6)
    if end < start:
        raise HTTPException(400, "The end date is before the start date.")
    if (end - start).days > 400:
        raise HTTPException(400, "Pick a range of 400 days or less.")
    return start, end, local_day_bounds(start)[0], local_day_bounds(end)[1]


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name, "employee_code": u.employee_code,
        "department": u.department, "role": u.role, "manager_id": u.manager_id,
        "manager_name": u.manager.name if u.manager else None, "active": u.active,
        "weekly_target_hours": u.weekly_target_hours, "must_change_password": u.must_change_password,
        "consent": u.consent_version == settings.consent_version, "consent_at": iso(u.consent_at),
    }


def entry_out(e: TimeEntry) -> dict:
    return {
        "id": e.id, "user_id": e.user_id, "start": iso(e.start), "end": iso(e.end),
        "break_minutes": e.break_minutes, "location": e.location, "source": e.source,
        "status": e.status, "note": e.note, "running": e.end is None,
        "worked_seconds": round(worked_seconds(e)),
    }


def correction_out(c: Correction) -> dict:
    return {
        "id": c.id, "user_id": c.user_id, "user_name": c.user.name, "kind": c.kind, "entry_id": c.entry_id,
        "start": iso(c.start), "end": iso(c.end), "break_minutes": c.break_minutes, "location": c.location,
        "reason": c.reason, "status": c.status, "reviewer_note": c.reviewer_note,
        "reviewed_at": iso(c.reviewed_at), "created_at": iso(c.created_at),
    }


def hours(seconds: float) -> str:
    return f"{seconds / 3600:.2f}"


def csv_response(filename: str, rows: list[list]) -> Response:
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel reads UTF-8 names (Cyrillic etc.) correctly
    csv.writer(buf).writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def entry_rows(entries: list[TimeEntry], users: dict[int, User]) -> list[list]:
    rows = [["Employee code", "Name", "Department", "Date", "Start", "End", "Break (min)",
             "Hours", "Location", "Source", "Status", "Note"]]
    for e in entries:
        u = users.get(e.user_id)
        s = to_local(e.start)
        en = to_local(e.end) if e.end else None
        rows.append([u.employee_code if u else "", u.name if u else e.user_id, u.department if u else "",
                     s.date().isoformat(), s.strftime("%H:%M"),
                     en.strftime("%H:%M") + (" (+1)" if en and en.date() != s.date() else "") if en else "running",
                     e.break_minutes, hours(worked_seconds(e)), e.location, e.source, e.status, e.note])
    return rows
