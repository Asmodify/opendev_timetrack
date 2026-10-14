from datetime import timedelta

from conftest import HOME, OFFICE

from app.db import SessionLocal
from app.models import TimeEntry, utcnow
from app.tracking import close_stale


def pair(client, headers, name="Laptop"):
    code = client.post("/api/me/pairing-code", headers=headers)
    assert code.status_code == 200, code.text
    r = client.post("/api/agent/pair", json={"code": code.json()["code"], "device_name": name, "platform": "test"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_consent_required_before_pairing(client, people):
    w = people["w2@example.com"]
    assert client.post("/api/me/pairing-code", headers=w).status_code == 403


def test_agent_session_office_then_remote_then_idle(client, people):
    w = people["w1@example.com"]
    assert client.post("/api/me/consent", json={"accept": True}, headers=w).json()["consent"] is True
    dev = pair(client, w)

    r = client.post("/api/agent/heartbeat", json={"active": True, "idle_seconds": 5}, headers={**dev, **OFFICE})
    assert r.json()["state"] == "working" and r.json()["location"] == "office"

    # Moving to home network closes the office session and opens a remote one.
    r = client.post("/api/agent/heartbeat", json={"active": True, "idle_seconds": 0}, headers={**dev, **HOME})
    assert r.json()["location"] == "remote"
    entries = client.get("/api/me/entries", headers=w).json()
    assert [e["location"] for e in entries] == ["office", "remote"]
    assert entries[0]["running"] is False and entries[1]["running"] is True

    # Idle past the timeout ends the session at the last input, not at "now".
    r = client.post("/api/agent/heartbeat", json={"active": False, "idle_seconds": 20 * 60}, headers={**dev, **HOME})
    assert r.json()["state"] == "stopped"
    assert client.get("/api/me", headers=w).json()["running"] is None


def test_withdrawing_consent_blocks_heartbeats(client, people):
    w = people["w1@example.com"]
    dev = pair(client, w, "Desktop")
    client.post("/api/me/consent", json={"accept": False}, headers=w)
    r = client.post("/api/agent/heartbeat", json={"active": True}, headers={**dev, **OFFICE})
    assert r.status_code == 403
    client.post("/api/me/consent", json={"accept": True}, headers=w)


def test_silent_helper_session_is_closed_by_sweeper(client, people):
    w = people["w1@example.com"]
    dev = pair(client, w, "Old PC")
    client.post("/api/agent/heartbeat", json={"active": True}, headers={**dev, **OFFICE})
    with SessionLocal() as db:
        e = db.query(TimeEntry).filter(TimeEntry.end.is_(None)).one()
        e.start = e.last_activity_at = utcnow() - timedelta(hours=1)
        last = e.last_activity_at
        db.commit()
        assert close_stale(db) == 1
        db.commit()
        db.refresh(e)
        assert e.end == last


def test_web_clock_and_long_shift_goes_to_review(client, people):
    w = people["w2@example.com"]
    r = client.post("/api/me/clock-in", json={"note": "site visit"}, headers={**w, **HOME})
    assert r.json()["location"] == "remote"
    assert client.post("/api/me/clock-in", json={}, headers=w).status_code == 409
    with SessionLocal() as db:
        e = db.get(TimeEntry, r.json()["id"])
        e.start = utcnow() - timedelta(hours=20)
        db.commit()
        close_stale(db)
        db.commit()
        db.refresh(e)
        assert e.status == "review" and (e.end - e.start) == timedelta(hours=14)


def test_correction_flow_and_manager_scope(client, people):
    w, boss, other = people["w2@example.com"], people["boss@example.com"], people["other@example.com"]
    r = client.post("/api/me/corrections", headers=w, json={
        "kind": "add", "start": "2026-10-12T09:00:00+08:00", "end": "2026-10-12T18:00:00+08:00",
        "break_minutes": 60, "location": "office", "reason": "Forgot to clock in"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    assert client.get("/api/team/corrections", headers=other).status_code == 403
    pending = client.get("/api/team/corrections", headers=boss).json()
    assert [c["id"] for c in pending] == [cid]
    assert client.post(f"/api/team/corrections/{cid}/approve", json={}, headers=boss).status_code == 200

    entries = client.get("/api/me/entries?start=2026-10-12&end=2026-10-12", headers=w).json()
    assert any(e["source"] == "manual" and e["worked_seconds"] == 8 * 3600 for e in entries)

    summary = client.get("/api/team/summary?start=2026-10-12&end=2026-10-18", headers=boss).json()
    names = {r["user"]["name"] for r in summary["rows"]}
    assert "Other Person" not in names and "Saraa Worker" in names

    csv_text = client.get("/api/team/export.csv?kind=entries&start=2026-10-12&end=2026-10-18", headers=boss).text
    assert "Saraa Worker" in csv_text and "Other Person" not in csv_text


def test_bad_correction_rejected(client, people):
    w = people["w2@example.com"]
    r = client.post("/api/me/corrections", headers=w, json={
        "kind": "add", "start": "2026-10-12T18:00:00+08:00", "end": "2026-10-12T09:00:00+08:00", "reason": "oops"})
    assert r.status_code == 400


def test_live_board_and_login_lockout(client, admin):
    live = client.get("/api/team/live", headers=admin).json()
    assert live["total"] >= 5
    for _ in range(8):
        client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"}).status_code == 429
