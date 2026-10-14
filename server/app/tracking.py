"""Session rules shared by the web clock and the desktop helper."""
import ipaddress
from datetime import date, datetime, time, timedelta, timezone

from fastapi import Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AuditLog, Device, TimeEntry, User, utcnow


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def location_for(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "remote"
    return "office" if any(addr in net for net in settings.office_networks) else "remote"


def audit(db: Session, actor: User | None, action: str, target: User | None = None, **detail) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action,
                    target_user_id=target.id if target else None, detail=detail))


def open_entry(db: Session, user_id: int) -> TimeEntry | None:
    return db.scalar(select(TimeEntry).where(TimeEntry.user_id == user_id, TimeEntry.end.is_(None))
                     .order_by(TimeEntry.start.desc()))


def start_entry(db: Session, user: User, location: str, source: str, device: Device | None = None,
                at: datetime | None = None, note: str = "", project_id: int | None = None) -> TimeEntry:
    at = at or utcnow()
    entry = TimeEntry(user_id=user.id, start=at, location=location, source=source,
                      device_id=device.id if device else None, last_activity_at=at, note=note,
                      project_id=project_id, confirmed=source == "web")
    db.add(entry)
    return entry


def close_entry(entry: TimeEntry, at: datetime | None = None) -> None:
    entry.end = max(at or utcnow(), entry.start)


def heartbeat(db: Session, device: Device, ip: str, active: bool, idle_seconds: int) -> dict:
    """Called by the desktop helper about once a minute.

    active=True  -> the worker used the keyboard or mouse recently: open or extend a session.
    active=False -> the computer is idle: close the session once it has been idle long enough.
    """
    now = utcnow()
    user = device.user
    device.last_seen_at = now
    location = location_for(ip)
    entry = open_entry(db, user.id)
    timeout = timedelta(minutes=settings.idle_timeout_minutes)
    last_input = now - timedelta(seconds=max(0, idle_seconds))

    if entry and entry.source != "agent":
        # The worker clocked in by hand; the web clock owns this session.
        return {"state": "manual", "location": entry.location, "entry_id": entry.id}

    if entry and entry.last_activity_at and now - entry.last_activity_at > timeout + timedelta(minutes=2):
        # Helper was offline (sleep, shutdown, lost network): end the old session where activity stopped.
        close_entry(entry, entry.last_activity_at)
        entry = None

    if active:
        if entry and entry.location != location:
            close_entry(entry, now)
            entry = None
        if entry is None:
            entry = start_entry(db, user, location, "agent", device, at=last_input)
        entry.last_activity_at = max(entry.last_activity_at or now, last_input)
        db.flush()
        return {"state": "working", "location": entry.location, "entry_id": entry.id,
                "since": entry.start.isoformat() + "Z"}

    if entry:
        if now - last_input >= timeout:
            close_entry(entry, entry.last_activity_at or last_input)
            return {"state": "stopped", "reason": "idle"}
        return {"state": "working", "location": entry.location, "entry_id": entry.id,
                "since": entry.start.isoformat() + "Z"}
    return {"state": "idle"}


def presence(db: Session, device: Device, event: str, office_name: str) -> dict:
    """Called by the phone app when it enters or leaves an office area.

    The phone sends only the event, never coordinates.
    """
    user = device.user
    device.last_seen_at = utcnow()
    entry = open_entry(db, user.id)
    if event == "arrive":
        if entry and entry.location == "office":
            return {"state": "working", "location": "office", "entry_id": entry.id}
        if entry and entry.source in ("agent", "phone"):
            close_entry(entry)  # e.g. was working remotely on the laptop, now walked into the office
        elif entry:
            return {"state": "manual", "location": entry.location, "entry_id": entry.id}
        entry = start_entry(db, user, "office", "phone", device, note=f"Arrived at {office_name}")
        db.flush()
        return {"state": "working", "location": "office", "entry_id": entry.id}
    # leave
    if entry and entry.source == "phone":
        close_entry(entry)
        return {"state": "stopped", "reason": "left office"}
    return {"state": "idle" if not entry else "manual"}


def close_stale(db: Session) -> int:
    """Close sessions whose helper went silent, and any session that ran past MAX_SHIFT_HOURS."""
    now = utcnow()
    closed = 0
    silent_cutoff = now - timedelta(minutes=settings.idle_timeout_minutes + 2)
    long_cutoff = now - timedelta(hours=settings.max_shift_hours)
    stale = db.scalars(select(TimeEntry).where(TimeEntry.end.is_(None), or_(
        and_(TimeEntry.source == "agent", TimeEntry.last_activity_at < silent_cutoff),
        TimeEntry.start < long_cutoff,
    ))).all()
    for entry in stale:
        if entry.start < long_cutoff:
            close_entry(entry, entry.start + timedelta(hours=settings.max_shift_hours))
            entry.status = "review"
            entry.note = (entry.note + " " if entry.note else "") + f"[Closed automatically after {settings.max_shift_hours} h]"
        else:
            close_entry(entry, entry.last_activity_at)
        closed += 1
    return closed


# ---------- reporting helpers ----------

def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC bounds of one calendar day in the company time zone."""
    start = datetime.combine(day, time.min, tzinfo=settings.timezone)
    end = start + timedelta(days=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(start), to_utc(end)


def local_today() -> date:
    return datetime.now(settings.timezone).date()


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def to_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(settings.timezone)


def worked_seconds(entry: TimeEntry, a: datetime | None = None, b: datetime | None = None) -> float:
    """Worked seconds of an entry, optionally clipped to [a, b). The break is spread across the shift."""
    end = entry.end or utcnow()
    span = (end - entry.start).total_seconds()
    if span <= 0:
        return 0.0
    net = max(0.0, span - entry.break_minutes * 60)
    lo = max(entry.start, a) if a else entry.start
    hi = min(end, b) if b else end
    part = (hi - lo).total_seconds()
    return net * part / span if part > 0 else 0.0


def entries_between(db: Session, user_ids: list[int] | None, a: datetime, b: datetime) -> list[TimeEntry]:
    q = select(TimeEntry).where(TimeEntry.start < b, or_(TimeEntry.end.is_(None), TimeEntry.end > a))
    if user_ids is not None:
        q = q.where(TimeEntry.user_id.in_(user_ids))
    return list(db.scalars(q.order_by(TimeEntry.start)))


def visible_users(db: Session, viewer: User) -> list[User]:
    """Admins see everyone; managers see their direct reports and themselves."""
    q = select(User).order_by(User.name)
    if viewer.role != "admin":
        q = q.where(or_(User.manager_id == viewer.id, User.id == viewer.id))
    return list(db.scalars(q))
