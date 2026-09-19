"""
main.py
The single FastAPI application - wires together every router built so far.

Run with:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from database import Base, engine
import schema_v2  # noqa: F401 - importing registers all tables on the shared Base

from auth_routes import router as auth_router
from roster_routes import router as roster_router
from distributor_routes import router as distributor_router
from treasurer_routes import router as treasurer_router
from volunteer_routes import router as gate_router
from admin_routes import router as admin_router
from bootstrap_routes import router as bootstrap_router

from config import EVENT_ID, EVENT_NAME

# Creates every table (students, users, expenses, cash_handovers,
# budget_allocations, audit_log) if they don't exist yet.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Event Pass & Verification System",
    description=f"Full pass sales, verification, and gate-check system for {EVENT_NAME}",
    version="2.0.0",
    # docs_url=None, redoc_url=None
)

app.include_router(auth_router)       # /login /logout /me /admin/users
app.include_router(roster_router)     # /admin/roster/*
app.include_router(distributor_router)  # /distributor/*
app.include_router(treasurer_router)    # /treasurer/*
app.include_router(gate_router)         # /verify /gate-stats /scanner /login-page
app.include_router(admin_router)        # /admin/dashboard /admin/audit-log
app.include_router(bootstrap_router)    # /bootstrap-admin-page /bootstrap-admin (one-time only)


@app.get("/")
def root():
    return RedirectResponse(url="/login-page")


@app.get("/health")
def health():
    return {"status": "ok", "event_id": EVENT_ID}
