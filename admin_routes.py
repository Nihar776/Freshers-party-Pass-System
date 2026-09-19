"""
admin_routes.py
The admin's full-picture dashboard: every stat requested, pulled from the
students/expenses/handovers tables. Also exposes the audit log for review
and a one-click integrity check on the hash chain.
"""
from typing import Optional
import csv
import io

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from schema_v2 import (
    Student, User, UserRole, PaymentStatus, PaymentMode, PassType,
    Expense, CashHandover, AuditLog,
)
from session_auth import require_role
from audit import verify_chain_integrity, write_audit_log

router = APIRouter(prefix="/admin", tags=["admin-dashboard"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class DistributorSales(BaseModel):
    distributor_name: str
    passes_sold: int
    amount_collected: float


class BranchSales(BaseModel):
    branch: str
    passes_sold: int
    percent_of_total: float


class PaymentModeBreakdown(BaseModel):
    mode: str
    count: int
    amount: float
    percent_of_count: float
    percent_of_amount: float


class PassTypeBreakdown(BaseModel):
    pass_type: str
    count: int
    percent: float


class DashboardResponse(BaseModel):
    # Sales overview
    total_roster_size: int
    total_sold: int             # verified + pending
    total_verified: int
    total_pending_verification: int
    total_rejected: int

    distributor_wise: list[DistributorSales]
    branch_wise: list[BranchSales]
    payment_mode_breakdown: list[PaymentModeBreakdown]
    pass_type_breakdown: list[PassTypeBreakdown]

    # Money (VERIFIED sales only - pending UPI never counts toward "collected")
    net_collection: float
    net_cash_collection: float
    net_upi_collection: float

    # Expenses / funds
    total_expenses: float
    net_funds_remaining: float
    total_cash_outstanding_with_distributors: float

    # Gate night
    total_entered: int
    pending_entry: int


class AuditLogEntry(BaseModel):
    id: int
    timestamp: str
    user_name: Optional[str]
    action: str
    table_name: str
    record_id: int
    old_value: Optional[dict]
    new_value: Optional[dict]

    class Config:
        from_attributes = True


class StudentOverrideRequest(BaseModel):
    payment_status: Optional[PaymentStatus] = None
    is_used: Optional[bool] = None


class AuditIntegrityResult(BaseModel):
    intact: bool
    first_broken_entry_id: Optional[int]
    total_entries: int


ADMIN_ONLY = (UserRole.ADMIN,)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    total_roster = db.query(func.count(Student.id)).scalar() or 0

    status_counts = dict(
        db.query(Student.payment_status, func.count(Student.id))
        .group_by(Student.payment_status).all()
    )
    total_verified = status_counts.get(PaymentStatus.VERIFIED, 0)
    total_pending = status_counts.get(PaymentStatus.PENDING_VERIFICATION, 0)
    total_rejected = status_counts.get(PaymentStatus.REJECTED, 0)
    total_sold = total_verified + total_pending

    # --- Distributor-wise (verified sales only - that's real, counted money) ---
    dist_rows = (
        db.query(User.full_name, func.count(Student.id), func.coalesce(func.sum(Student.amount), 0.0))
        .join(Student, Student.distributor_id == User.id)
        .filter(Student.payment_status == PaymentStatus.VERIFIED)
        .group_by(User.full_name)
        .order_by(func.count(Student.id).desc())
        .all()
    )
    distributor_wise = [
        DistributorSales(distributor_name=name, passes_sold=count, amount_collected=amount)
        for name, count, amount in dist_rows
    ]

    # --- Branch-wise ---
    branch_rows = (
        db.query(Student.branch, func.count(Student.id))
        .filter(Student.payment_status == PaymentStatus.VERIFIED)
        .group_by(Student.branch)
        .order_by(func.count(Student.id).desc())
        .all()
    )
    branch_wise = [
        BranchSales(branch=b, passes_sold=c, percent_of_total=round(100 * c / total_verified, 1) if total_verified else 0.0)
        for b, c in branch_rows
    ]

    # --- Payment mode breakdown ---
    mode_rows = (
        db.query(Student.payment_mode, func.count(Student.id), func.coalesce(func.sum(Student.amount), 0.0))
        .filter(Student.payment_status == PaymentStatus.VERIFIED)
        .group_by(Student.payment_mode)
        .all()
    )
    total_amount = sum(amt for _, _, amt in mode_rows) or 1.0  # avoid /0
    payment_mode_breakdown = [
        PaymentModeBreakdown(
            mode=mode.value if mode else "unknown", count=count, amount=amount,
            percent_of_count=round(100 * count / total_verified, 1) if total_verified else 0.0,
            percent_of_amount=round(100 * amount / total_amount, 1),
        )
        for mode, count, amount in mode_rows
    ]
    net_cash = next((r.amount for r in payment_mode_breakdown if r.mode == "cash"), 0.0)
    net_upi = next((r.amount for r in payment_mode_breakdown if r.mode == "upi"), 0.0)

    # --- Pass type breakdown ---
    type_rows = (
        db.query(Student.pass_type, func.count(Student.id))
        .filter(Student.payment_status == PaymentStatus.VERIFIED)
        .group_by(Student.pass_type)
        .all()
    )
    pass_type_breakdown = [
        PassTypeBreakdown(
            pass_type=pt.value, count=c,
            percent=round(100 * c / total_verified, 1) if total_verified else 0.0,
        )
        for pt, c in type_rows
    ]

    # --- Cash outstanding across ALL distributors ---
    all_cash_collected = db.query(func.coalesce(func.sum(Student.amount), 0.0)).filter(
        Student.payment_mode == PaymentMode.CASH, Student.payment_status == PaymentStatus.VERIFIED
    ).scalar()
    all_handed_over = db.query(func.coalesce(func.sum(CashHandover.amount), 0.0)).scalar()
    cash_outstanding = all_cash_collected - all_handed_over

    # --- Expenses / net funds ---
    total_expenses = db.query(func.coalesce(func.sum(Expense.amount), 0.0)).scalar()
    net_collection = net_cash + net_upi

    # --- Gate night ---
    total_entered = db.query(func.count(Student.id)).filter(Student.is_used.is_(True)).scalar() or 0

    return DashboardResponse(
        total_roster_size=total_roster,
        total_sold=total_sold,
        total_verified=total_verified,
        total_pending_verification=total_pending,
        total_rejected=total_rejected,
        distributor_wise=distributor_wise,
        branch_wise=branch_wise,
        payment_mode_breakdown=payment_mode_breakdown,
        pass_type_breakdown=pass_type_breakdown,
        net_collection=net_collection,
        net_cash_collection=net_cash,
        net_upi_collection=net_upi,
        total_expenses=total_expenses,
        net_funds_remaining=net_collection - total_expenses,
        total_cash_outstanding_with_distributors=cash_outstanding,
        total_entered=total_entered,
        pending_entry=total_verified - total_entered,
    )


# ---------------------------------------------------------------------------
# Audit log review
# ---------------------------------------------------------------------------
@router.get("/audit-log", response_model=list[AuditLogEntry])
def view_audit_log(
    action: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    rows = q.order_by(AuditLog.id.desc()).limit(limit).all()
    return [
        AuditLogEntry(
            id=r.id, timestamp=r.timestamp.isoformat(),
            user_name=r.user.full_name if r.user else None,
            action=r.action, table_name=r.table_name, record_id=r.record_id,
            old_value=r.old_value, new_value=r.new_value,
        )
        for r in rows
    ]


@router.get("/audit-log/verify-integrity", response_model=AuditIntegrityResult)
def check_audit_integrity(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    intact, bad_id = verify_chain_integrity(db)
    total = db.query(func.count(AuditLog.id)).scalar() or 0
    return AuditIntegrityResult(intact=intact, first_broken_entry_id=bad_id, total_entries=total)


# ---------------------------------------------------------------------------
# Export & Overrides
# ---------------------------------------------------------------------------
@router.get("/export/attendees")
def export_attendees(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    students = db.query(Student).filter(Student.is_used.is_(True)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "SAP ID", "Branch", "Entered At", "Scanned By"])
    for s in students:
        scanned_by = s.scanned_by.full_name if s.scanned_by else "Unknown"
        entered_at = s.entered_at.isoformat() if s.entered_at else "Unknown"
        writer.writerow([s.name, s.sap_id, s.branch, entered_at, scanned_by])
    
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=attendees.csv"})


@router.get("/export/sales")
def export_sales(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    students = db.query(Student).filter(Student.payment_status != PaymentStatus.NOT_PURCHASED).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "SAP ID", "Pass Type", "Amount", "Payment Mode", "Status", "Distributor"])
    for s in students:
        distributor = s.distributor.full_name if s.distributor else "Unknown"
        pass_type = s.pass_type.value if s.pass_type else ""
        payment_mode = s.payment_mode.value if s.payment_mode else ""
        writer.writerow([s.name, s.sap_id, pass_type, s.amount or 0, payment_mode, s.payment_status.value, distributor])
    
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=sales.csv"})


@router.patch("/students/{student_id}/override")
def override_student(
    student_id: int,
    payload: StudentOverrideRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    old_snapshot = {
        "payment_status": student.payment_status.value if student.payment_status else None,
        "is_used": student.is_used
    }
    
    new_snapshot = {}
    if payload.payment_status is not None:
        student.payment_status = payload.payment_status
        new_snapshot["payment_status"] = payload.payment_status.value
    if payload.is_used is not None:
        student.is_used = payload.is_used
        new_snapshot["is_used"] = payload.is_used

    if not new_snapshot:
        return {"message": "No changes requested"}

    db.flush()

    write_audit_log(
        db, user_id=admin.id, action="admin_override", table_name="students",
        record_id=student.id, old_value=old_snapshot, new_value=new_snapshot,
    )
    db.commit()
    db.refresh(student)

    return {"message": "Student record overridden successfully"}
