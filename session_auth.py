"""
session_auth.py
Login sessions (separate JWT from the pass-QR tokens) + FastAPI
dependencies that gate routes by role.

Flow:
  POST /login -> verify username/password -> issue a signed session token
  in an httponly cookie -> every protected route reads that cookie via
  require_role(...) to find out who's asking and whether they're allowed.
"""
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import SESSION_SECRET_KEY, JWT_ALGORITHM, SESSION_TTL_HOURS
from database import get_db
from schema_v2 import User, UserRole

SESSION_COOKIE_NAME = "session_token"


class AuthError(Exception):
    pass


def create_session_token(user: User) -> str:
    payload = {
        "typ": "session",  # distinguishes this from a pass-QR token even though algorithm matches
        "user_id": user.id,
        "role": user.role.value,
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_TTL_HOURS * 3600,
    }
    return jwt.encode(payload, SESSION_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SESSION_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session expired, please log in again") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid session") from exc

    if payload.get("typ") != "session":
        raise AuthError("Invalid session token type")
    return payload


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Base dependency: resolves the logged-in user from the session cookie.
    Raises 401 if not logged in, session expired, or the account was
    disabled by an admin after the token was issued.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")

    try:
        payload = decode_session_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or disabled")

    return user


def require_role(*allowed_roles: UserRole):
    """
    Dependency factory: use as Depends(require_role(UserRole.ADMIN)) on any
    route that should only be reachable by specific roles.

    Example:
        @app.post("/admin/distributors")
        def add_distributor(..., user: User = Depends(require_role(UserRole.ADMIN))):
            ...
    """
    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' is not permitted to access this",
            )
        return user
    return _dependency
