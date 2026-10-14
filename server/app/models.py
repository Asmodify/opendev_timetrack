from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC; every timestamp in the database is naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES = ("worker", "manager", "admin")
LOCATIONS = ("office", "remote")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    employee_code: Mapped[str | None] = mapped_column(String(64), index=True)
    department: Mapped[str | None] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16), default="worker")
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    weekly_target_hours: Mapped[float] = mapped_column(Float, default=40.0)
    consent_version: Mapped[str | None] = mapped_column(String(32))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    manager: Mapped["User | None"] = relationship(remote_side=[id])


class Project(Base):
    """Something hours can be logged against (a client, product or internal work)."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    client: Mapped[str | None] = mapped_column(String(128))
    color: Mapped[str] = mapped_column(String(7), default="#2f5d9e")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OfficeLocation(Base):
    """A workplace the phone app watches for, as a circle around a point."""

    __tablename__ = "office_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[int] = mapped_column(Integer, default=150)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(Base):
    """A computer running the desktop helper, or a phone running the app, linked to one worker."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="computer")  # computer | phone
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship()


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    end: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # None while the session is running
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(16), default="remote")
    # "agent" = desktop helper, "phone" = arrived at an office, "web" = clock button, "manual" = approved correction
    source: Mapped[str] = mapped_column(String(16), default="web")
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime)
    # "ok" or "review" (auto-closed after MAX_SHIFT_HOURS; a manager should check it)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    note: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    # Automatic sessions start unconfirmed; the worker reviews their day and confirms it.
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship()
    project: Mapped[Project | None] = relationship()


class Correction(Base):
    """A worker's request to add, change or remove hours. A manager approves or rejects it."""

    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # add | edit | delete
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("time_entries.id"))
    start: Mapped[datetime | None] = mapped_column(DateTime)
    end: Mapped[datetime | None] = mapped_column(DateTime)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str | None] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | approved | rejected
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewer_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
