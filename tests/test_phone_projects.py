from conftest import HOME


def test_admin_sets_up_projects_and_offices(client, admin, people):
    w = people["w1@example.com"]
    r = client.post("/api/admin/projects", json={"name": "Fleet portal", "client": "Open Tee", "color": "#0e6b58"}, headers=admin)
    assert r.status_code == 200, r.text
    assert client.post("/api/admin/projects", json={"name": "X"}, headers=w).status_code == 403
    r = client.post("/api/admin/offices", json={"name": "HQ", "latitude": 47.9185, "longitude": 106.9176, "radius_m": 120}, headers=admin)
    assert r.status_code == 200, r.text
    assert [p["name"] for p in client.get("/api/me/projects", headers=w).json()] == ["Fleet portal"]
    assert client.get("/api/me/offices", headers=w).json()[0]["radius_m"] == 120


def test_phone_signs_in_once_and_reports_arrival(client, people):
    w = people["w1@example.com"]
    reg = client.post("/api/me/phone", json={"device_name": "Bat's iPhone", "platform": "ios"}, headers=w)
    assert reg.status_code == 200, reg.text
    phone = {"Authorization": f"Bearer {reg.json()['token']}"}

    # The device token works for the worker's own endpoints...
    assert client.get("/api/me", headers=phone).json()["user"]["email"] == "w1@example.com"
    # ...but not for manager or admin endpoints the worker can't use anyway.
    assert client.get("/api/team/live", headers=phone).status_code == 403

    office = client.get("/api/me/offices", headers=phone).json()[0]
    # A remote laptop session gets replaced by an office session when the phone arrives.
    client.post("/api/me/consent", json={"accept": True}, headers=w)
    r = client.post("/api/agent/presence", json={"event": "arrive", "office_id": office["id"]}, headers=phone)
    assert r.json() == {"state": "working", "location": "office", "entry_id": r.json()["entry_id"]}
    again = client.post("/api/agent/presence", json={"event": "arrive", "office_id": office["id"]}, headers=phone)
    assert again.json()["entry_id"] == r.json()["entry_id"]
    left = client.post("/api/agent/presence", json={"event": "leave", "office_id": office["id"]}, headers=phone)
    assert left.json()["state"] == "stopped"
    running = client.get("/api/me", headers=phone).json()["running"]
    assert running is None


def test_arrival_does_not_override_manual_clock(client, people):
    w = people["other@example.com"]
    phone = {"Authorization": "Bearer " + client.post("/api/me/phone", json={"device_name": "Pixel"}, headers=w).json()["token"]}
    client.post("/api/me/consent", json={"accept": True}, headers=w)
    office = client.get("/api/me/offices", headers=w).json()[0]
    client.post("/api/me/clock-in", json={}, headers={**w, **HOME})
    r = client.post("/api/agent/presence", json={"event": "arrive", "office_id": office["id"]}, headers=phone)
    assert r.json()["state"] == "manual"
    client.post("/api/me/clock-out", headers=w)


def test_unlinked_phone_is_signed_out(client, people):
    w = people["w2@example.com"]
    reg = client.post("/api/me/phone", json={"device_name": "Old phone"}, headers=w).json()
    phone = {"Authorization": f"Bearer {reg['token']}"}
    client.delete(f"/api/me/devices/{reg['device_id']}", headers=w)
    assert client.get("/api/me", headers=phone).status_code == 401


def test_tag_and_confirm_day(client, admin, people):
    w = people["w1@example.com"]
    entries = client.get("/api/me/entries", headers=w).json()
    auto = [e for e in entries if e["source"] in ("agent", "phone") and not e["running"]]
    assert auto and not any(e["confirmed"] for e in auto)
    project = client.get("/api/me/projects", headers=w).json()[0]
    r = client.patch(f"/api/me/entries/{auto[0]['id']}", json={"project_id": project["id"], "note": "Sprint work"}, headers=w)
    assert r.json()["project"]["name"] == "Fleet portal"

    day = auto[0]["start"][:10]
    confirmed = client.post("/api/me/confirm-day", json={"date": day}, headers=w).json()["confirmed"]
    assert confirmed >= 1
    other = people["w2@example.com"]
    assert client.patch(f"/api/me/entries/{auto[0]['id']}", json={"note": "x"}, headers=other).status_code == 404

    summary = client.get("/api/team/summary", headers=admin).json()
    assert any(p["name"] == "Fleet portal" for p in summary["projects"])
