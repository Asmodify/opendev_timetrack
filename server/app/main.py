import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from .config import settings
from .db import Base, SessionLocal, engine
from .models import User
from .routers import admin, agent, auth, me, team
from .security import hash_password
from .tracking import close_stale

log = logging.getLogger("timetrack")
WEB = Path(__file__).resolve().parent.parent / "web"


def bootstrap() -> None:
    Base.metadata.create_all(engine)
    if settings.secret_key == "dev-only-change-me":
        log.warning("SECRET_KEY is not set. Set it before running in production.")
    with SessionLocal() as db:
        has_admin = db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
        if not has_admin and settings.first_admin_email and settings.first_admin_password:
            db.add(User(email=settings.first_admin_email.lower(), name="Administrator", role="admin",
                        password_hash=hash_password(settings.first_admin_password), must_change_password=True))
            db.commit()
            log.warning("Created first admin %s", settings.first_admin_email)


async def sweeper() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            with SessionLocal() as db:
                if close_stale(db):
                    db.commit()
        except Exception:  # keep the loop alive; the next pass retries
            log.exception("stale-session sweep failed")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    task = asyncio.create_task(sweeper())
    yield
    task.cancel()


app = FastAPI(title=f"{settings.company_name} Time Tracking", lifespan=lifespan)
for r in (auth.router, me.router, agent.router, team.router, admin.router):
    app.include_router(r)
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
