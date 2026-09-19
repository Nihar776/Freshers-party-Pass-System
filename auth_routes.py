"""
auth_routes.py
Login/logout endpoints, plus admin-only user management (add/disable
distributors, treasurers, volunteers). Wire this router into main.py with
app.include_router(auth_router).
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from schema_v2 import User, UserRole
from security import hash_password, verify_password
from session_auth import create_session_token, require_role, get_current_user, SESSION_COOKIE_NAME
from config import IS_PRODUCTION

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    message: str
    full_name: str
    role: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: UserRole


class UserSummary(BaseModel):
    id: int
    username: str
    full_name: str
    role: UserRole
    is_active: bool


# ---------------------------------------------------------------------------
# Login / logout - open to anyone with valid credentials
# ---------------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()

    # Deliberately identical error for "no such user" and "wrong password" -
    # don't let the response leak which usernames exist.
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_session_token(user)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,       # not readable by JS - blocks XSS token theft
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=12 * 3600,
    )
    return LoginResponse(message="Logged in", full_name=user.full_name, role=user.role.value)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserSummary)
def whoami(user: User = Depends(get_current_user)):
    return UserSummary(
        id=user.id, username=user.username, full_name=user.full_name,
        role=user.role, is_active=user.is_active,
    )


# ---------------------------------------------------------------------------
# Admin-only: manage treasurer / distributor / volunteer accounts
# ---------------------------------------------------------------------------
@router.post("/admin/users", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' already exists")
    
    if payload.role == UserRole.ADMIN and admin.id != 1:
        raise HTTPException(status_code=403, detail="Only the super-admin (id=1) can create other admins")

    new_user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        created_by_id=admin.id,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # NOTE: once audit_log is wired in, this is exactly the kind of action
    # ("distributor_created" / "treasurer_created" / "volunteer_created")
    # that should write an AuditLog row here, tagged with admin.id.

    return UserSummary(
        id=new_user.id, username=new_user.username, full_name=new_user.full_name,
        role=new_user.role, is_active=new_user.is_active,
    )


@router.get("/admin/users", response_model=list[UserSummary])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
):
    users = db.query(User).order_by(User.role, User.full_name).all()
    return [
        UserSummary(id=u.id, username=u.username, full_name=u.full_name, role=u.role, is_active=u.is_active)
        for u in users
    ]


@router.patch("/admin/users/{user_id}/disable")
def disable_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot disable your own account")

    target.is_active = False
    db.commit()
    return {"message": f"{target.full_name} disabled"}


@router.patch("/admin/users/{user_id}/enable")
def enable_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_active = True
    db.commit()
    return {"message": f"{target.full_name} enabled"}
