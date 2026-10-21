"""Time-off / leave request flow: create, approve, balance, cancel, and who may approve."""
from datetime import date, timedelta


def _req(client, headers, **body):
    return client.post("/api/me/leave", json=body, headers=headers)


def test_leave_request_approval_and_balance(client, people):
    w1, boss = people["w1@example.com"], people["boss@example.com"]
    start = (date.today() + timedelta(days=7)).isoformat()
    end = (date.today() + timedelta(days=9)).isoformat()

    r = _req(client, w1, type="annual", start_date=start, end_date=end, reason="Trip")
    assert r.status_code == 200, r.text
    assert r.json()["days"] == 3 and r.json()["status"] == "pending"

    mine = client.get("/api/me/leave", headers=w1).json()
    assert mine["balance"]["pending_days"] == 3
    assert mine["balance"]["remaining_days"] == mine["balance"]["entitlement_days"]
    assert len(mine["requests"]) == 1
    lid = mine["requests"][0]["id"]

    pending = client.get("/api/team/leave", headers=boss).json()
    assert any(x["id"] == lid for x in pending)

    ok = client.post(f"/api/team/leave/{lid}/approve", json={"note": "Enjoy"}, headers=boss)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"

    after = client.get("/api/me/leave", headers=w1).json()
    assert after["balance"]["used_days"] == 3
    assert after["balance"]["remaining_days"] == after["balance"]["entitlement_days"] - 3


def test_half_day_counts_as_half(client, people):
    w1 = people["w1@example.com"]
    day = (date.today() + timedelta(days=20)).isoformat()
    r = _req(client, w1, type="annual", start_date=day, end_date=day, half_day=True)
    assert r.status_code == 200 and r.json()["days"] == 0.5


def test_overtime_requires_hours_and_single_day(client, people):
    w2 = people["w2@example.com"]
    day = (date.today() + timedelta(days=3)).isoformat()
    nextday = (date.today() + timedelta(days=4)).isoformat()
    assert _req(client, w2, type="overtime", start_date=day, end_date=day, hours=0).status_code == 400
    assert _req(client, w2, type="overtime", start_date=day, end_date=nextday, hours=2).status_code == 400
    ok = _req(client, w2, type="overtime", start_date=day, end_date=day, hours=2.5)
    assert ok.status_code == 200 and ok.json()["hours"] == 2.5 and ok.json()["unit"] == "hours"


def test_bad_dates_and_unknown_type_rejected(client, people):
    w1 = people["w1@example.com"]
    start = (date.today() + timedelta(days=5)).isoformat()
    before = (date.today() + timedelta(days=4)).isoformat()
    assert _req(client, w1, type="annual", start_date=start, end_date=before).status_code == 400
    assert _req(client, w1, type="holiday", start_date=start, end_date=start).status_code == 400


def test_nobody_approves_their_own(client, people, admin):
    boss = people["boss@example.com"]
    start = (date.today() + timedelta(days=30)).isoformat()
    r = _req(client, boss, type="annual", start_date=start, end_date=start, reason="Day off")
    lid = r.json()["id"]
    # The manager cannot approve their own request...
    assert client.post(f"/api/team/leave/{lid}/approve", json={"note": ""}, headers=boss).status_code == 403
    # ...but an admin can.
    assert client.post(f"/api/team/leave/{lid}/approve", json={"note": ""}, headers=admin).status_code == 200


def test_worker_cancels_pending_request(client, people):
    w2 = people["w2@example.com"]
    start = (date.today() + timedelta(days=12)).isoformat()
    lid = _req(client, w2, type="sick", start_date=start, end_date=start, reason="Flu").json()["id"]
    assert client.post(f"/api/me/leave/{lid}/cancel", headers=w2).status_code == 200
    assert client.post(f"/api/me/leave/{lid}/cancel", headers=w2).status_code == 409
    statuses = [x["status"] for x in client.get("/api/me/leave", headers=w2).json()["requests"] if x["id"] == lid]
    assert statuses == ["cancelled"]


def test_leave_type_catalog_in_me(client, people):
    w1 = people["w1@example.com"]
    me = client.get("/api/me", headers=w1).json()
    keys = {t["key"] for t in me["leave_types"]}
    assert {"annual", "sick", "overtime"} <= keys
