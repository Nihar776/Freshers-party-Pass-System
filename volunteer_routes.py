"""
volunteer_routes.py
Gate-night verification, rewired onto the new Student/User schema.
Replaces the old /verify in main.py (v1) - that one didn't know about
roles, payment verification status, or who scanned the entry.

Only a logged-in VOLUNTEER (or ADMIN) can check students in. Every
successful scan records exactly which volunteer processed it.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import update, func
from sqlalchemy.orm import Session

from database import get_db
from schema_v2 import Student, User, UserRole, PaymentStatus
from session_auth import require_role
from auth import verify_pass_token, InvalidPassToken
from audit import write_audit_log
from config import EVENT_ID

router = APIRouter(tags=["gate"])
GATE_ROLES = (UserRole.VOLUNTEER, UserRole.ADMIN)
BASE_DIR = Path(__file__).resolve().parent


class VerifyRequest(BaseModel):
    token: str


class VerifyResponse(BaseModel):
    message: str
    student_name: str
    sap_id: str
    entered_at: datetime
    food_preference: str


class GateStats(BaseModel):
    total_verified_passes: int
    total_entered: int
    pending_entry: int
    
from settings_manager import get_current_scanner_mode

@router.get("/scanner-mode")
def get_scanner_mode(volunteer: User = Depends(require_role(*GATE_ROLES))):
    return {"mode": get_current_scanner_mode()}


@router.post("/verify", response_model=VerifyResponse)
def verify_and_check_in(
    payload: VerifyRequest,
    db: Session = Depends(get_db),
    volunteer: User = Depends(require_role(*GATE_ROLES)),
):
    try:
        token_data = verify_pass_token(payload.token)
    except InvalidPassToken as exc:
        raise HTTPException(status_code=400, detail=f"Counterfeit pass: {exc}") from exc

    if token_data.get("event_id") != EVENT_ID:
        raise HTTPException(status_code=400, detail="Counterfeit pass: wrong event")

    student = db.query(Student).filter(Student.pass_uuid == token_data["pass_id"]).first()
    if not student:
        raise HTTPException(status_code=404, detail="Pass not found in database")

    if student.sap_id != token_data.get("sap_id"):
        raise HTTPException(status_code=400, detail="Counterfeit pass: SAP ID mismatch")

    # Defensive check: a pass token should only ever exist for a VERIFIED
    # sale, but if payment was somehow rejected/reversed after issuance,
    # never let it scan in.
    if student.payment_status != PaymentStatus.VERIFIED:
        raise HTTPException(
            status_code=403,
            detail=f"Payment not verified (status: {student.payment_status.value}) - do not admit",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    result = db.execute(
        update(Student)
        .where(Student.id == student.id, Student.is_used.is_(False))
        .values(is_used=True, entered_at=now, scanned_by_id=volunteer.id)
    )

    if result.rowcount == 0:
        db.rollback()
        db.refresh(student)
        entered_str = student.entered_at.strftime("%I:%M %p") if student.entered_at else "unknown time"
        scanned_by_name = student.scanned_by.full_name if student.scanned_by else "unknown volunteer"
        raise HTTPException(
            status_code=409,
            detail=f"Pass already used at {entered_str} (scanned by {scanned_by_name})",
        )

    write_audit_log(
        db, user_id=volunteer.id, action="gate_checkin", table_name="students",
        record_id=student.id, new_value={"entered_at": now.isoformat(), "scanned_by": volunteer.full_name},
    )
    db.commit()
    db.refresh(student)

    return VerifyResponse(
        message="Entry approved - issue wristband",
        student_name=student.name, sap_id=student.sap_id, entered_at=student.entered_at,
        food_preference=student.food_preference.value if student.food_preference else "veg"
    )


@router.post("/verify-food", response_model=VerifyResponse)
def verify_food_check_in(
    payload: VerifyRequest,
    db: Session = Depends(get_db),
    volunteer: User = Depends(require_role(*GATE_ROLES)),
):
    try:
        token_data = verify_pass_token(payload.token)
    except InvalidPassToken as exc:
        raise HTTPException(status_code=400, detail=f"Counterfeit pass: {exc}") from exc

    if token_data.get("event_id") != EVENT_ID:
        raise HTTPException(status_code=400, detail="Counterfeit pass: wrong event")

    student = db.query(Student).filter(Student.pass_uuid == token_data["pass_id"]).first()
    if not student:
        raise HTTPException(status_code=404, detail="Pass not found in database")

    if student.sap_id != token_data.get("sap_id"):
        raise HTTPException(status_code=400, detail="Counterfeit pass: SAP ID mismatch")

    if student.payment_status != PaymentStatus.VERIFIED:
        raise HTTPException(
            status_code=403,
            detail=f"Payment not verified (status: {student.payment_status.value}) - do not give food",
        )
        
    if not student.is_used:
        raise HTTPException(
            status_code=403,
            detail="Student has not entered the gate yet! Scan gate entry first.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    result = db.execute(
        update(Student)
        .where(Student.id == student.id, Student.food_received.is_(False))
        .values(food_received=True, food_received_at=now, food_scanned_by_id=volunteer.id)
    )

    if result.rowcount == 0:
        db.rollback()
        db.refresh(student)
        received_str = student.food_received_at.strftime("%I:%M %p") if student.food_received_at else "unknown time"
        scanned_by_name = student.food_scanned_by.full_name if student.food_scanned_by else "unknown volunteer"
        raise HTTPException(
            status_code=409,
            detail=f"Food already received at {received_str} (scanned by {scanned_by_name})",
        )

    write_audit_log(
        db, user_id=volunteer.id, action="food_checkin", table_name="students",
        record_id=student.id, new_value={"food_received_at": now.isoformat(), "food_scanned_by": volunteer.full_name},
    )
    db.commit()
    db.refresh(student)

    food_pref_str = student.food_preference.value if student.food_preference else "veg"
    return VerifyResponse(
        message=f"Give {food_pref_str.upper()} Food",
        student_name=student.name, sap_id=student.sap_id, entered_at=student.food_received_at,
        food_preference=food_pref_str
    )


@router.get("/gate-stats", response_model=GateStats)
def gate_stats(
    db: Session = Depends(get_db),
    volunteer: User = Depends(require_role(*GATE_ROLES)),
):
    total_verified = db.query(func.count(Student.id)).filter(
        Student.payment_status == PaymentStatus.VERIFIED
    ).scalar() or 0
    entered = db.query(func.count(Student.id)).filter(Student.is_used.is_(True)).scalar() or 0
    return GateStats(total_verified_passes=total_verified, total_entered=entered,
                      pending_entry=total_verified - entered)



