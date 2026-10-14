import ipaddress
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _networks(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(part.strip(), strict=False) for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./timetrack.db")
    secret_key: str = os.getenv("SECRET_KEY", "dev-only-change-me")
    token_hours: int = int(os.getenv("TOKEN_HOURS", "12"))
    company_name: str = os.getenv("COMPANY_NAME", "OpenDevelopment")
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo(os.getenv("COMPANY_TZ", "Asia/Ulaanbaatar")))
    # Public IP ranges of the office network(s). A request from one of these is tagged "office".
    office_networks: list = field(default_factory=lambda: _networks(os.getenv("OFFICE_NETWORKS", "")))
    # Only trust X-Forwarded-For when running behind a reverse proxy you control.
    trust_proxy: bool = _bool("TRUST_PROXY")
    # Close an automatic session after this many minutes without activity.
    idle_timeout_minutes: int = int(os.getenv("IDLE_TIMEOUT_MINUTES", "15"))
    # Any session still open after this long is closed and sent to a manager for review.
    max_shift_hours: int = int(os.getenv("MAX_SHIFT_HOURS", "14"))
    consent_version: str = os.getenv("CONSENT_VERSION", "2026-10")
    # Browser origins allowed to call the API from another domain (e.g. a web build of the phone app). Usually empty.
    cors_origins: list = field(default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()])
    first_admin_email: str = os.getenv("FIRST_ADMIN_EMAIL", "")
    first_admin_password: str = os.getenv("FIRST_ADMIN_PASSWORD", "")


settings = Settings()
