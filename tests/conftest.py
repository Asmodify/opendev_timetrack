import os
import sys
import tempfile
from pathlib import Path

_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ.update({
    "DATABASE_URL": os.getenv("TEST_DATABASE_URL", f"sqlite:///{_db}"),
    "SECRET_KEY": "test-secret-0123456789abcdef0123456789abcdef",
    "OFFICE_NETWORKS": "203.0.113.0/24",
    "TRUST_PROXY": "true",
    "FIRST_ADMIN_EMAIL": "admin@example.com",
    "FIRST_ADMIN_PASSWORD": "admin-pass-123",
    "COMPANY_TZ": "Asia/Ulaanbaatar",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

OFFICE = {"X-Forwarded-For": "203.0.113.7"}
HOME = {"X-Forwarded-For": "198.51.100.20"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "admin@example.com", "admin-pass-123")


@pytest.fixture(scope="session")
def people(client, admin):
    """One manager with two workers, plus a worker in another team."""
    csv_text = (
        "email,name,employee_code,department,role,manager_email\n"
        "w1@example.com,Bat Worker,E001,Engineering,worker,boss@example.com\n"
        "w2@example.com,Saraa Worker,E002,Engineering,worker,boss@example.com\n"
        "boss@example.com,Dorj Manager,M001,Engineering,manager,\n"
        "other@example.com,Other Person,E003,Sales,worker,\n"
        "bad-row,,,,,\n"
    )
    r = client.post("/api/admin/users/import", json={"csv_text": csv_text}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["created"]) == 4 and len(body["errors"]) == 1
    pw = {p["email"]: p["temporary_password"] for p in body["created"]}
    return {email: login(client, email, pw[email]) for email in pw}
