import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import iso, user_out
from ..db import get_db
from ..models import ROLES, AuditLog, Device, User
from ..security import hash_password, require_role, temp_password
from ..tracking import audit

router = APIRouter(prefix="/api/admin", tags=["admins"])
admin = require_role("admin")


class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    employee_code: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=128)
    role: str = "worker"
    manager_email: str | None = None
    weekly_target_hours: float = Field(40, ge=0, le=100)


class UserPatch(BaseModel):
    name: str | None = Field(None, max_length=255)
    employee_code: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=128)
    role: str | None = None
    manager_id: int | None = None
    clear_manager: bool = False
    active: bool | None = None
    weekly_target_hours: float | None = Field(None, ge=0, le=100)


class ImportIn(BaseModel):
    csv_text: str = Field(max_length=2_000_000)


def _by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def _create(db: Session, actor: User, body: UserIn) -> tuple[User, str]:
    email = body.email.strip().lower()
    if "@" not in email:
        raise ValueError(f"'{body.email}' is not an email address.")
    if body.role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}.")
    if _by_email(db, email):
        raise ValueError(f"{email} already has an account.")
    mgr = None
    if body.manager_email:
        mgr = _by_email(db, body.manager_email)
        if not mgr:
            raise ValueError(f"Manager {body.manager_email} has no account yet. Add managers first.")
    pw = temp_password()
    u = User(email=email, name=body.name.strip(), employee_code=(body.employee_code or "").strip() or None,
             department=(body.department or "").strip() or None, role=body.role, manager_id=mgr.id if mgr else None,
             password_hash=hash_password(pw), must_change_password=True, weekly_target_hours=body.weekly_target_hours)
    db.add(u)
    db.flush()
    audit(db, actor, "user_created", u, role=u.role)
    return u, pw


@router.get("/users")
def list_users(_: User = Depends(admin), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.name))]


@router.post("/users")
def create_user(body: UserIn, actor: User = Depends(admin), db: Session = Depends(get_db)):
    try:
        u, pw = _create(db, actor, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"user": user_out(u), "temporary_password": pw}


@router.post("/users/import")
def import_users(body: ImportIn, actor: User = Depends(admin), db: Session = Depends(get_db)):
    """CSV columns: email,name,employee_code,department,role,manager_email (header row required)."""
    reader = csv.DictReader(io.StringIO(body.csv_text.lstrip("﻿")))
    needed = {"email", "name"}
    if not reader.fieldnames or not needed <= {f.strip().lower() for f in reader.fieldnames}:
        raise HTTPException(400, "The CSV needs a header row with at least: email,name")
    created, errors = [], []
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]
    # Managers first, so workers can point at them in the same file.
    rows.sort(key=lambda r: 0 if r.get("role") in ("admin", "manager") else 1)
    for i, r in enumerate(rows, start=2):
        try:
            with db.begin_nested():
                u, pw = _create(db, actor, UserIn(
                    email=r.get("email", ""), name=r.get("name", ""), employee_code=r.get("employee_code") or None,
                    department=r.get("department") or None, role=r.get("role") or "worker",
                    manager_email=r.get("manager_email") or None))
            created.append({"email": u.email, "name": u.name, "temporary_password": pw})
        except Exception as e:  # noqa: BLE001 - report every bad row instead of failing the whole file
            errors.append({"row": r.get("email") or f"line {i}", "error": str(e).splitlines()[0]})
    db.commit()
    return {"created": created, "errors": errors}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, actor: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(400, f"Role must be one of {', '.join(ROLES)}.")
        if u.id == actor.id and body.role != "admin":
            raise HTTPException(400, "You can't remove your own admin role.")
        u.role = body.role
    if body.active is not None:
        if u.id == actor.id and not body.active:
            raise HTTPException(400, "You can't deactivate your own account.")
        u.active = body.active
        if not body.active:
            for d in db.scalars(select(Device).where(Device.user_id == u.id)):
                d.revoked = True
    if body.clear_manager:
        u.manager_id = None
    elif body.manager_id is not None:
        if body.manager_id == u.id or not db.get(User, body.manager_id):
            raise HTTPException(400, "Pick a different manager.")
        u.manager_id = body.manager_id
    for field in ("name", "employee_code", "department", "weekly_target_hours"):
        value = getattr(body, field)
        if value is not None:
            setattr(u, field, value)
    audit(db, actor, "user_updated", u, changes=body.model_dump(exclude_none=True))
    db.commit()
    return user_out(u)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, actor: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    pw = temp_password()
    u.password_hash, u.must_change_password = hash_password(pw), True
    audit(db, actor, "password_reset", u)
    db.commit()
    return {"temporary_password": pw}


@router.get("/audit")
def audit_log(limit: int = 200, _: User = Depends(admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(min(limit, 1000)))
    names = {u.id: u.name for u in db.scalars(select(User))}
    return [{"at": iso(r.at), "actor": names.get(r.actor_id), "action": r.action,
             "target": names.get(r.target_user_id), "detail": r.detail} for r in rows]
