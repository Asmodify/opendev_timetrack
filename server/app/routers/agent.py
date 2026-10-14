import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Device, OfficeLocation, PairingCode, utcnow
from ..security import current_device, hash_token
from ..tracking import audit, client_ip, close_entry, heartbeat, open_entry, presence

router = APIRouter(prefix="/api/agent", tags=["desktop helper"])


class PairIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    device_name: str = Field(min_length=1, max_length=128)
    platform: str = Field("", max_length=64)


class HeartbeatIn(BaseModel):
    active: bool
    idle_seconds: int = Field(0, ge=0, le=7 * 86400)


class PresenceIn(BaseModel):
    event: str = Field(pattern="^(arrive|leave)$")
    office_id: int


class StopIn(BaseModel):
    reason: str = Field("", max_length=64)


@router.post("/pair")
def pair(body: PairIn, db: Session = Depends(get_db)):
    pc = db.scalar(select(PairingCode).where(PairingCode.code_hash == hash_token(body.code.strip().upper())))
    if not pc or pc.used or pc.expires_at < utcnow():
        raise HTTPException(400, "That code is wrong or has expired. Create a new one in the dashboard.")
    pc.used = True
    token = secrets.token_urlsafe(32)
    device = Device(user_id=pc.user_id, name=body.device_name.strip(), platform=body.platform,
                    token_hash=hash_token(token))
    db.add(device)
    db.flush()
    audit(db, device.user, "device_paired", device.user, device=device.name)
    db.commit()
    return {"token": token, "user_name": device.user.name, "device_id": device.id}


def _require_consent(device: Device) -> None:
    if device.user.consent_version != settings.consent_version:
        raise HTTPException(403, "Automatic tracking is off until you accept the tracking notice in the dashboard.")


@router.post("/heartbeat")
def agent_heartbeat(body: HeartbeatIn, request: Request, device: Device = Depends(current_device),
                    db: Session = Depends(get_db)):
    _require_consent(device)
    result = heartbeat(db, device, client_ip(request), body.active, body.idle_seconds)
    db.commit()
    return result


@router.post("/stop")
def agent_stop(body: StopIn, device: Device = Depends(current_device), db: Session = Depends(get_db)):
    """Sent when the computer locks, sleeps or shuts down."""
    entry = open_entry(db, device.user_id)
    device.last_seen_at = utcnow()
    if entry and entry.source == "agent":
        close_entry(entry)
        db.commit()
        return {"state": "stopped", "reason": body.reason or "stop"}
    db.commit()
    return {"state": "idle"}


@router.post("/presence")
def phone_presence(body: PresenceIn, device: Device = Depends(current_device), db: Session = Depends(get_db)):
    """The phone app entered or left an office area."""
    if device.kind != "phone":
        raise HTTPException(400, "Only the phone app reports office arrivals.")
    _require_consent(device)
    office = db.get(OfficeLocation, body.office_id)
    if not office or not office.active:
        raise HTTPException(404, "That office no longer exists. Reopen the app to refresh the office list.")
    result = presence(db, device, body.event, office.name)
    db.commit()
    return result
