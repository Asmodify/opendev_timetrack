# OpenDevelopment Time Tracking

The company's hour-tracking system for all staff, kept separate from the admin dashboard and the driver app.

- **Workers** clock in and out from any browser or the phone app, or let it happen automatically: the desktop helper tracks computer use, and the phone app checks them in when they arrive at an office. They see their day as a timeline, tag hours with projects, confirm automatic sessions, export their hours, request corrections, and send time-off requests (leave, sick days, work-from-home, overtime and more) with a yearly leave balance.
- **Managers** see who is working right now, team timesheets (office vs remote, hours by project, unconfirmed sessions), and approve or reject corrections and time-off requests.
- **Admins (HR)** add people one by one or import a CSV, set roles and managers, manage projects and office areas, reset passwords, export payroll CSVs and read the audit log.

## How automatic tracking works

1. A worker accepts the tracking notice in the dashboard (it can be withdrawn at any time) and links a computer with a one-time code.
2. The desktop helper (`agent/timetrack_agent.py`) tells the server once a minute whether the keyboard or mouse was used in the last 5 minutes. No keystrokes, screenshots, apps, websites or GPS are collected.
3. The server opens a session on the first activity and closes it after `IDLE_TIMEOUT_MINUTES` without activity (or when the helper stops), ending it at the last activity it saw.
4. If the request comes from one of the `OFFICE_NETWORKS` addresses, the hours are tagged **Office**, otherwise **Remote**. Moving between them splits the session.
5. With the phone app's office check-in on, arriving inside an office area starts an office session and leaving ends it. The phone sends only "arrive"/"leave", never coordinates. See [mobile/README.md](mobile/README.md).
6. Automatic sessions start as **drafts**. As in Timely's timeline, the worker reviews their day, adds projects, and confirms it.
7. Anything still open after `MAX_SHIFT_HOURS` is closed and flagged for a manager to review.

> **Before rollout:** tracking employees' computer activity and work location is personal data. Give staff the written notice, follow your labour and data-protection rules, and get HR/legal sign-off. The consent step, the "what is never recorded" list and the audit log are built in for this, but they do not replace that review.

## Run it

```bash
cp .env.example .env        # fill in SECRET_KEY, POSTGRES_PASSWORD, OFFICE_NETWORKS, FIRST_ADMIN_*
docker compose up -d --build
```

Open `http://SERVER:8000`, sign in as `FIRST_ADMIN_EMAIL`, change the password, then import staff under **People**. Put it behind HTTPS (nginx, Caddy or your load balancer) before anyone signs in from outside the office, and keep `TRUST_PROXY=true` only when that proxy sets `X-Forwarded-For`.

To find the office's public IP for `OFFICE_NETWORKS`, open https://ifconfig.me from an office computer.

### Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cd server && uvicorn app.main:app --reload       # SQLite by default
pytest ../tests                                   # or set TEST_DATABASE_URL to a PostgreSQL URL
```

## Importing staff

CSV with a header row: `email,name,employee_code,department,role,manager_email`. Roles: `worker`, `manager`, `admin`. Managers in the same file are created first. Each new person gets a temporary password (shown once, downloadable as CSV) and must change it at first sign-in.

## Desktop helper

See [agent/build.md](agent/build.md) for packaging it as a Windows or macOS program and setting it up on each computer.

## Phone app

See [mobile/README.md](mobile/README.md) for building the Android and iOS app and how office check-in behaves in the background.

## Layout

```
server/app/        FastAPI app: models, tracking rules, routers (auth, me, agent, team, admin)
server/web/        Dashboard (plain HTML, CSS and JavaScript, no build step)
agent/             Desktop helper (standard-library Python)
mobile/            Flutter phone app (Android, iOS)
tests/             API and tracking-rule tests
```

## Not yet included

- Single sign-on with company accounts; sign-in is email and password for now.
- Database migrations (tables are created on first start; add Alembic before changing the schema in production).
