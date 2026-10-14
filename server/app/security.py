import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Device, User, utcnow

_ITER = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER).hex()
    return f"pbkdf2_sha256${_ITER}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters)).hex()
    return hmac.compare_digest(check, digest)


def hash_token(token: str) -> str:
    """Device tokens and pairing codes are random, so a plain SHA-256 is enough to store them."""
    return hashlib.sha256(token.encode()).hexdigest()


def temp_password() -> str:
    return secrets.token_urlsafe(9)


def create_access_token(user: User) -> str:
    payload = {"sub": str(user.id), "role": user.role, "exp": utcnow() + timedelta(hours=settings.token_hours)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return header[7:].strip()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(_bearer(request), settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account is disabled.")
    return user


def require_role(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this page.")
        return user

    return checker


def current_device(request: Request, db: Session = Depends(get_db)) -> Device:
    device = db.scalar(select(Device).where(Device.token_hash == hash_token(_bearer(request))))
    if not device or device.revoked or not device.user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This computer is no longer linked. Pair it again.")
    return device
