from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from database import get_db
from schema_v2 import User, UserRole
from session_auth import get_current_user, require_role

router = APIRouter(tags=["pages"])
BASE_DIR = Path(__file__).resolve().parent


@router.get("/login-page", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(content=(BASE_DIR / "templates" / "login.html").read_text(encoding="utf-8"))


@router.get("/admin-page", response_class=HTMLResponse)
def admin_page(admin: User = Depends(require_role(UserRole.ADMIN))):
    return HTMLResponse(content=(BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8"))


@router.get("/distributor-page", response_class=HTMLResponse)
def distributor_page(distributor: User = Depends(require_role(UserRole.DISTRIBUTOR, UserRole.ADMIN))):
    return HTMLResponse(content=(BASE_DIR / "templates" / "distributor.html").read_text(encoding="utf-8"))


@router.get("/treasurer-page", response_class=HTMLResponse)
def treasurer_page(treasurer: User = Depends(require_role(UserRole.TREASURER, UserRole.ADMIN))):
    return HTMLResponse(content=(BASE_DIR / "templates" / "treasurer.html").read_text(encoding="utf-8"))


@router.get("/scanner", response_class=HTMLResponse)
def scanner_page(volunteer: User = Depends(require_role(UserRole.VOLUNTEER, UserRole.ADMIN))):
    return HTMLResponse(content=(BASE_DIR / "templates" / "scanner.html").read_text(encoding="utf-8"))
