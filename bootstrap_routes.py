"""
bootstrap_routes.py
Phone/browser-friendly replacement for bootstrap_admin.py - lets you
create the very first admin account by just opening a URL, no terminal or
SSH access needed. Protected by a secret you set yourself in Render's
environment variables, AND only works while zero admin accounts exist -
so even if the secret leaks later, it can't be replayed.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from schema_v2 import User, UserRole
from security import hash_password
from config import BOOTSTRAP_SECRET

router = APIRouter(tags=["bootstrap"])
BASE_DIR = Path(__file__).resolve().parent


class BootstrapRequest(BaseModel):
    secret: str
    username: str
    full_name: str
    password: str


@router.get("/bootstrap-admin-page", response_class=HTMLResponse)
def bootstrap_admin_page(db: Session = Depends(get_db)):
    already_exists = db.query(User).filter(User.role == UserRole.ADMIN).first() is not None
    if already_exists or not BOOTSTRAP_SECRET:
        return HTMLResponse(
            "<body style='font-family:sans-serif;padding:40px;text-align:center;color:#888;'>"
            "Bootstrap is disabled - an admin account already exists, or BOOTSTRAP_SECRET isn't set. "
            "Log in at <a href='/login-page'>/login-page</a> instead.</body>",
            status_code=403,
        )
    return HTMLResponse(content=(BASE_DIR / "templates" / "bootstrap.html").read_text(encoding="utf-8"))


@router.post("/bootstrap-admin")
def bootstrap_admin(payload: BootstrapRequest, db: Session = Depends(get_db)):
    if not BOOTSTRAP_SECRET:
        raise HTTPException(status_code=403, detail="Bootstrap is disabled (no BOOTSTRAP_SECRET configured)")
    if payload.secret != BOOTSTRAP_SECRET:
        raise HTTPException(status_code=403, detail="Incorrect setup secret")

    already_exists = db.query(User).filter(User.role == UserRole.ADMIN).first() is not None
    if already_exists:
        raise HTTPException(status_code=403, detail="An admin account already exists - bootstrap is locked")

    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="That username is already taken")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    admin = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name or payload.username,
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.commit()

    return {"message": f"Admin account '{payload.username}' created. You can now log in at /login-page."}
