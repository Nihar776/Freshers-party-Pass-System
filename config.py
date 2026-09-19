"""
config.py
Centralized configuration loaded from environment variables.
Copy .env.example to .env and fill in real values before running.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # loads .env if present; real deployments should set env vars directly


def _require(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"See .env.example for the full list."
        )
    return val


# --- Security ---
# HS256 signing secret for PASS tokens (QR codes). MUST be long, random, and kept secret.
# Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"
SECRET_KEY: str = _require("SECRET_KEY")
JWT_ALGORITHM: str = "HS256"

# Separate secret for LOGIN SESSION tokens, deliberately different from
# SECRET_KEY above - a leak of one should never help forge the other.
SESSION_SECRET_KEY: str = _require("SESSION_SECRET_KEY")
SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "12"))

# One-time secret for the phone-friendly /bootstrap-admin-page setup flow.
# Set this in your hosting env vars, use it once to create your first admin,
# then feel free to remove it from the environment (the endpoint also
# locks itself once any admin account exists, regardless).
BOOTSTRAP_SECRET: str = os.getenv("BOOTSTRAP_SECRET", "")

# Token has no expiry by default (the pass is valid until the event), but you
# can cap it by setting PASS_TOKEN_TTL_HOURS (e.g. "72").
PASS_TOKEN_TTL_HOURS: int | None = (
    int(os.getenv("PASS_TOKEN_TTL_HOURS")) if os.getenv("PASS_TOKEN_TTL_HOURS") else None
)

# --- Event metadata (embedded in the token, not secret) ---
EVENT_ID: str = os.getenv("EVENT_ID", "FRESHERS_2026")
EVENT_NAME: str = os.getenv("EVENT_NAME", "Freshers' Party 2026")
EVENT_VENUE: str = os.getenv("EVENT_VENUE", "College Main Auditorium")
EVENT_DATE: str = os.getenv("EVENT_DATE", "TBD")

# --- Database ---
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./event_passes.db")

# --- SMTP / Email ---
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASS: str = os.getenv("SMTP_PASS", "")
SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "College Fest Team")
# If true, uses STARTTLS (587). If false, uses implicit SSL (465).
SMTP_USE_STARTTLS: bool = os.getenv("SMTP_USE_STARTTLS", "true").lower() == "true"

# --- App ---
# Base URL where /scanner and /verify are reachable, used only for logging/QR fallback text.
APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

IS_PRODUCTION: bool = APP_BASE_URL.startswith("https")

PASS_PRICE: float = 499.0
