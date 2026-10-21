import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import user_out
from ..db import get_db
from ..models import User
from ..security import create_access_token, current_user, hash_password, verify_password
from ..tracking import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

_failures: dict[str, list[float]] = defaultdict(list)
_WINDOW, _MAX_FAILS = 900, 8


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    key = body.email.strip().lower()
    recent = [t for t in _failures[key] if time.time() - t < _WINDOW]
    _failures[key] = recent
    if len(recent) >= _MAX_FAILS:
        raise HTTPException(429, "Too many failed sign-ins. Wait 15 minutes, or ask an admin to reset your password.")
    user = db.scalar(select(User).where(func.lower(User.email) == key))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        _failures[key].append(time.time())
        raise HTTPException(401, "Wrong email or password.")
    _failures.pop(key, None)
    return {"token": create_access_token(user), "user": user_out(user)}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is wrong.")
    if body.new_password == body.current_password:
        raise HTTPException(400, "Choose a password different from the current one.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    audit(db, user, "password_changed", user)
    db.commit()
    return {"ok": True}
