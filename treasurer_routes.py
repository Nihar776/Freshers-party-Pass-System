"""
treasurer_routes.py
The treasurer's world: approve/reject pending UPI sales (this is the ONLY
place a UPI pass's QR gets generated and emailed), record cash handovers
from distributors, and track expenses/budget.

Admins can also act here (they can do everything), but a plain distributor
cannot.
"""
import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Form, File, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from database import get_db
from schema_v2 import (
    Student, User, UserRole, PaymentStatus, PaymentMode,
    CashHandover, Expense, BudgetAllocation, FundType,
    CashHandoverRequest, HandoverRequestStatus
)
from session_auth import require_role
from audit import write_audit_log
from auth import generate_pass_token, generate_qr_image
from mailer import send_pass_email

router = APIRouter(prefix="/treasurer", tags=["treasurer"])

TREASURY_ROLES = (UserRole.TREASURER, UserRole.ADMIN)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class VerificationMemberItem(BaseModel):
    student_id: int
    sap_id: str
    name: str
    email: Optional[str] = None
    branch: str

class PendingVerificationGroupItem(BaseModel):
    group_id: str
    total_amount: float
    member_count: int
    utr_number: Optional[str]
    distributor_name: str
    sold_at: Optional[str]
    duplicate_screenshot_warning: bool
    has_screenshot: bool
    members: list[VerificationMemberItem]
    payer_student_id: Optional[int]


class VerifyActionResult(BaseModel):
    message: str
    sap_id: str
    payment_status: PaymentStatus


class RejectRequest(BaseModel):
    reason: str


class DistributorCashRow(BaseModel):
    distributor_id: int
    distributor_name: str
    total_cash_collected: float
    total_handed_over: float
    outstanding: float


class CashHandoverPayload(BaseModel):
    distributor_id: int
    amount: float
    notes: Optional[str] = None


class ExpenseCreateRequest(BaseModel):
    description: str
    category: str
    fund_type: FundType
    amount: float


class BudgetSetRequest(BaseModel):
    category: str
    fund_type: FundType
    allocated_amount: float


class BudgetStatusItem(BaseModel):
    category: str
    fund_type: FundType
    allocated: float
    spent: float
    remaining: float


class FinanceSummary(BaseModel):
    net_verified_collection: float
    total_upi_verified: float
    total_cash_verified: float
    total_expenses: float
    net_funds_remaining: float
    total_cash_remaining: float
    total_upi_remaining: float


# ---------------------------------------------------------------------------
# Verification queue
# ---------------------------------------------------------------------------
@router.get("/pending-verifications", response_model=list[PendingVerificationGroupItem])
def pending_verifications(
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    rows = (
        db.query(Student)
        .filter(Student.payment_status == PaymentStatus.PENDING_VERIFICATION)
        .order_by(Student.sold_at.asc())
        .all()
    )
    
    # Group by group_id
    groups = {}
    for r in rows:
        gid = r.group_id or str(r.id)  # fallback to id if no group_id (legacy data)
        if gid not in groups:
            groups[gid] = []
        groups[gid].append(r)

    result = []
    for gid, members in groups.items():
        payer = next((m for m in members if m.is_group_payer), members[0])
        
        dup = False
        if payer.screenshot_phash:
            dup = db.query(Student).filter(
                Student.screenshot_phash == payer.screenshot_phash, Student.id != payer.id
            ).first() is not None

        result.append(PendingVerificationGroupItem(
            group_id=gid,
            total_amount=sum((m.amount or 0) for m in members),
            member_count=len(members),
            utr_number=payer.utr_number,
            distributor_name=payer.distributor.full_name if payer.distributor else "unknown",
            sold_at=payer.sold_at.isoformat() if payer.sold_at else None,
            duplicate_screenshot_warning=dup,
            has_screenshot=bool(payer.payment_screenshot),
            members=[
                VerificationMemberItem(
                    student_id=m.id, sap_id=m.sap_id, name=m.name, email=m.email, branch=m.branch
                ) for m in members
            ],
            payer_student_id=payer.id
        ))

    return result


@router.get("/pending-verifications/{student_id}/screenshot")
def get_screenshot(
    student_id: int,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    """Returns the screenshot as base64 so the treasurer can actually look at it."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student or not student.payment_screenshot:
        raise HTTPException(status_code=404, detail="No screenshot on file")
    return {"sap_id": student.sap_id, "screenshot_base64": student.payment_screenshot}


@router.post("/verify-group/{group_id}", response_model=VerifyActionResult)
def verify_group_payment(
    group_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(UserRole.TREASURER, UserRole.ADMIN)),
):
    # Try finding by group_id or fallback to single ID for legacy data
    students = db.query(Student).filter(
        (Student.group_id == group_id) | (Student.id == (int(group_id) if group_id.isdigit() else 0))
    ).all()
    
    if not students:
        raise HTTPException(status_code=404, detail="Group not found")

    verified_count = 0
    errors = []
    
    for student in students:
        if student.payment_status != PaymentStatus.PENDING_VERIFICATION:
            continue
            
        old_snapshot = {"payment_status": student.payment_status.value}
        student.payment_status = PaymentStatus.VERIFIED
        student.verified_by_id = treasurer.id
        student.verified_at = func.now()
        db.flush()

        write_audit_log(
            db, user_id=treasurer.id, action="payment_verified", table_name="students",
            record_id=student.id, old_value=old_snapshot, new_value={"payment_status": "verified"},
        )
        
        try:
            token = generate_pass_token(sap_id=student.sap_id, pass_uuid=student.pass_uuid)
            qr_image = generate_qr_image(token)
            background_tasks.add_task(
                send_pass_email,
                recipient_email=student.email, 
                student_name=student.name, 
                qr_image_bytes=qr_image, 
                sap_id=student.sap_id
            )
            verified_count += 1
        except Exception as exc:
            errors.append(f"{student.sap_id}: {exc}")

    db.commit()

    if errors:
        raise HTTPException(status_code=502, detail=f"Verified {verified_count}, but some emails failed: {', '.join(errors)}")

    return VerifyActionResult(message=f"{verified_count} payments verified and passes being emailed in the background", sap_id=group_id,
                               payment_status=PaymentStatus.VERIFIED)


@router.post("/reject-group/{group_id}", response_model=VerifyActionResult)
def reject_group(
    group_id: str,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    students = db.query(Student).filter(
        (Student.group_id == group_id) | (Student.id == (int(group_id) if group_id.isdigit() else 0))
    ).all()
    
    if not students:
        raise HTTPException(status_code=404, detail="Group not found")

    rejected_count = 0
    for student in students:
        if student.payment_status != PaymentStatus.PENDING_VERIFICATION:
            continue
            
        old_snapshot = {"payment_status": student.payment_status.value}
        student.payment_status = PaymentStatus.REJECTED
        student.verified_by_id = treasurer.id
        student.verified_at = func.now()
        student.rejection_reason = payload.reason
        db.flush()

        write_audit_log(
            db, user_id=treasurer.id, action="payment_rejected", table_name="students",
            record_id=student.id, old_value=old_snapshot,
            new_value={"payment_status": "rejected", "reason": payload.reason},
        )
        rejected_count += 1
        
    db.commit()

    return VerifyActionResult(message=f"{rejected_count} payments rejected (distributors can retry)", sap_id=group_id,
                               payment_status=PaymentStatus.REJECTED)


@router.post("/verify/{student_id}", response_model=VerifyActionResult)
def verify_payment(
    student_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(UserRole.TREASURER, UserRole.ADMIN)),
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.payment_status != PaymentStatus.PENDING_VERIFICATION:
        raise HTTPException(status_code=409, detail=f"Not pending - current status: {student.payment_status.value}")

    old_snapshot = {"payment_status": student.payment_status.value}
    student.payment_status = PaymentStatus.VERIFIED
    student.verified_by_id = treasurer.id
    student.verified_at = func.now()
    db.flush()

    write_audit_log(
        db, user_id=treasurer.id, action="payment_verified", table_name="students",
        record_id=student.id, old_value=old_snapshot, new_value={"payment_status": "verified"},
    )
    db.commit()
    db.refresh(student)

    # Only NOW does the QR get generated and emailed - this is the whole
    # point of holding back UPI verification.
    token = generate_pass_token(sap_id=student.sap_id, pass_uuid=student.pass_uuid)
    qr_image = generate_qr_image(token)

    background_tasks.add_task(
        send_pass_email,
        recipient_email=student.email, 
        student_name=student.name, 
        qr_image_bytes=qr_image, 
        sap_id=student.sap_id
    )

    return VerifyActionResult(message="Payment verified, pass is being emailed in the background", sap_id=student.sap_id,

                               student_id=student.id,payment_status=student.payment_status)


@router.post("/reject/{student_id}", response_model=VerifyActionResult)
def reject_payment(
    student_id: int,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.payment_status != PaymentStatus.PENDING_VERIFICATION:
        raise HTTPException(status_code=409, detail=f"Not pending - current status: {student.payment_status.value}")

    old_snapshot = {"payment_status": student.payment_status.value}
    # REJECTED unlocks the SAP ID for resale (see distributor sell_pass's WHERE clause).
    student.payment_status = PaymentStatus.REJECTED
    student.rejection_reason = payload.reason
    db.flush()

    write_audit_log(
        db, user_id=treasurer.id, action="payment_rejected", table_name="students",
        record_id=student.id, old_value=old_snapshot,
        new_value={"payment_status": "rejected", "reason": payload.reason},
    )
    db.commit()
    db.refresh(student)

    return VerifyActionResult(message="Payment rejected - SAP ID is unlocked for resale",
                               sap_id=student.sap_id,
 student_id=student.id,payment_status=student.payment_status)


# ---------------------------------------------------------------------------
# Cash custody
# ---------------------------------------------------------------------------
@router.get("/cash-outstanding", response_model=list[DistributorCashRow])
def cash_outstanding(
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    distributors = db.query(User).filter(User.role == UserRole.DISTRIBUTOR).all()
    result = []
    for d in distributors:
        collected = db.query(func.coalesce(func.sum(Student.amount), 0.0)).filter(
            Student.distributor_id == d.id, Student.payment_mode == PaymentMode.CASH,
            Student.payment_status == PaymentStatus.VERIFIED,
        ).scalar()
        handed = db.query(func.coalesce(func.sum(CashHandover.amount), 0.0)).filter(
            CashHandover.distributor_id == d.id
        ).scalar()
        if collected > 0 or handed > 0:
            result.append(DistributorCashRow(
                distributor_id=d.id, distributor_name=d.full_name,
                total_cash_collected=collected, total_handed_over=handed,
                outstanding=collected - handed,
            ))
    return result


@router.post("/cash-handover")
def record_cash_handover(
    payload: CashHandoverPayload,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    distributor = db.query(User).filter(
        User.id == payload.distributor_id, User.role == UserRole.DISTRIBUTOR
    ).first()
    if not distributor:
        raise HTTPException(status_code=404, detail="Distributor not found")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    handover = CashHandover(
        distributor_id=distributor.id, treasurer_id=treasurer.id,
        amount=payload.amount, notes=payload.notes,
    )
    db.add(handover)
    db.flush()

    write_audit_log(
        db, user_id=treasurer.id, action="cash_handover", table_name="cash_handovers",
        record_id=handover.id,
        new_value={"distributor_id": distributor.id, "amount": payload.amount, "notes": payload.notes},
    )
    db.commit()

    return {"message": f"₹{payload.amount} recorded as handed over by {distributor.full_name}"}


@router.get("/handover-requests")
def list_handover_requests(
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    requests = db.query(CashHandoverRequest).filter(
        CashHandoverRequest.status == HandoverRequestStatus.PENDING
    ).order_by(CashHandoverRequest.created_at.asc()).all()
    
    return [
        {
            "id": r.id,
            "distributor_id": r.distributor_id,
            "distributor_name": r.distributor.full_name,
            "amount": r.amount,
            "created_at": r.created_at.isoformat()
        }
        for r in requests
    ]


@router.post("/handover-requests/{req_id}/approve")
def approve_handover_request(
    req_id: int,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    from datetime import datetime
    req = db.query(CashHandoverRequest).filter(CashHandoverRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != HandoverRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Request is not pending")
        
    req.status = HandoverRequestStatus.APPROVED
    req.resolved_at = datetime.utcnow()
    req.resolved_by_id = treasurer.id

    handover = CashHandover(
        distributor_id=req.distributor_id, treasurer_id=treasurer.id,
        amount=req.amount, notes="Approved from distributor request"
    )
    db.add(handover)
    db.flush()

    write_audit_log(
        db, user_id=treasurer.id, action="cash_handover", table_name="cash_handovers",
        record_id=handover.id,
        new_value={"distributor_id": req.distributor_id, "amount": req.amount, "notes": "Approved from request"},
    )
    db.commit()
    return {"message": "Handover request approved"}


@router.post("/handover-requests/{req_id}/reject")
def reject_handover_request(
    req_id: int,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    from datetime import datetime
    req = db.query(CashHandoverRequest).filter(CashHandoverRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != HandoverRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Request is not pending")
        
    req.status = HandoverRequestStatus.REJECTED
    req.resolved_at = datetime.utcnow()
    req.resolved_by_id = treasurer.id
    db.commit()
    return {"message": "Handover request rejected"}


@router.get("/history")
def get_treasurer_history(
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    # 1. Verified UPI Payments
    upi_students = db.query(Student).filter(
        Student.payment_mode == PaymentMode.UPI,
        Student.payment_status == PaymentStatus.VERIFIED
    ).order_by(Student.verified_at.desc()).all()
    
    verified_upi = [
        {
            "id": s.id,
            "sap_id": s.sap_id,
            "name": s.name,
            "amount": s.amount,
            "verified_at": s.verified_at.isoformat() if s.verified_at else None,
            "verified_by_name": s.verified_by.full_name if s.verified_by else "System"
        }
        for s in upi_students
    ]

    # 2. Approved Cash Handovers
    handovers = db.query(CashHandover).order_by(CashHandover.handed_over_at.desc()).all()
    approved_cash = [
        {
            "id": h.id,
            "distributor_name": h.distributor.full_name if h.distributor else "Unknown",
            "amount": h.amount,
            "handed_over_at": h.handed_over_at.isoformat() if h.handed_over_at else None,
            "treasurer_name": h.treasurer.full_name if h.treasurer else "System",
            "notes": h.notes
        }
        for h in handovers
    ]

    return {
        "verified_upi": verified_upi,
        "approved_cash": approved_cash
    }


# ---------------------------------------------------------------------------
# Expenses & budget
# ---------------------------------------------------------------------------
@router.post("/expenses")
def add_expense(
    description: str = Form(...),
    category: str = Form(...),
    fund_type: FundType = Form(...),
    amount: float = Form(...),
    receipt: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    receipt_b64 = None
    if receipt:
        receipt_b64 = base64.b64encode(receipt.file.read()).decode("utf-8")

    expense = Expense(
        description=description, category=category, fund_type=fund_type, amount=amount,
        recorded_by_id=treasurer.id, receipt_image=receipt_b64,
    )
    db.add(expense)
    db.flush()

    write_audit_log(
        db, user_id=treasurer.id, action="expense_added", table_name="expenses",
        record_id=expense.id,
        new_value={"description": description, "category": category, "fund_type": fund_type.value, "amount": amount},
    )
    db.commit()

    return {"message": "Expense recorded", "id": expense.id}


@router.get("/expenses")
def list_expenses(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    q = db.query(Expense)
    if category:
        q = q.filter(Expense.category == category)
    rows = q.order_by(Expense.spent_at.desc()).all()
    return [
        {"id": e.id, "description": e.description, "category": e.category,
         "fund_type": e.fund_type, "amount": e.amount, "spent_at": e.spent_at.isoformat(),
         "recorded_by": e.recorded_by.full_name}
        for e in rows
    ]


@router.post("/budget")
def set_budget(
    payload: BudgetSetRequest,
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    existing = db.query(BudgetAllocation).filter(
        BudgetAllocation.category == payload.category,
        BudgetAllocation.fund_type == payload.fund_type
    ).first()
    old_snapshot = {"allocated_amount": existing.allocated_amount} if existing else None

    if existing:
        existing.allocated_amount = payload.allocated_amount
        existing.set_by_id = treasurer.id
        record_id = existing.id
    else:
        existing = BudgetAllocation(
            category=payload.category, fund_type=payload.fund_type, allocated_amount=payload.allocated_amount, set_by_id=treasurer.id,
        )
        db.add(existing)
        db.flush()
        record_id = existing.id

    write_audit_log(
        db, user_id=treasurer.id, action="budget_set", table_name="budget_allocations",
        record_id=record_id, old_value=old_snapshot,
        new_value={"category": payload.category, "fund_type": payload.fund_type.value, "allocated_amount": payload.allocated_amount},
    )
    db.commit()

    return {"message": f"Budget for '{payload.category}' ({payload.fund_type.value}) set to ₹{payload.allocated_amount}"}


@router.get("/budget-status", response_model=list[BudgetStatusItem])
def budget_status(
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    allocations = db.query(BudgetAllocation).all()
    result = []
    for a in allocations:
        spent = db.query(func.coalesce(func.sum(Expense.amount), 0.0)).filter(
            Expense.category == a.category,
            Expense.fund_type == a.fund_type
        ).scalar()
        result.append(BudgetStatusItem(
            category=a.category, fund_type=a.fund_type, allocated=a.allocated_amount, spent=spent,
            remaining=a.allocated_amount - spent,
        ))
    return result


@router.get("/finance-summary", response_model=FinanceSummary)
def finance_summary(
    db: Session = Depends(get_db),
    treasurer: User = Depends(require_role(*TREASURY_ROLES)),
):
    upi_verified = db.query(func.coalesce(func.sum(Student.amount), 0.0)).filter(
        Student.payment_mode == PaymentMode.UPI, Student.payment_status == PaymentStatus.VERIFIED,
    ).scalar()
    cash_verified = db.query(func.coalesce(func.sum(Student.amount), 0.0)).filter(
        Student.payment_mode == PaymentMode.CASH, Student.payment_status == PaymentStatus.VERIFIED,
    ).scalar()
    total_cash_expenses = db.query(func.coalesce(func.sum(Expense.amount), 0.0)).filter(
        Expense.fund_type == FundType.CASH
    ).scalar()
    total_upi_expenses = db.query(func.coalesce(func.sum(Expense.amount), 0.0)).filter(
        Expense.fund_type == FundType.UPI
    ).scalar()
    
    total_expenses = total_cash_expenses + total_upi_expenses
    net = upi_verified + cash_verified

    return FinanceSummary(
        net_verified_collection=net,
        total_upi_verified=upi_verified,
        total_cash_verified=cash_verified,
        total_expenses=total_expenses,
        net_funds_remaining=net - total_expenses,
        total_cash_remaining=cash_verified - total_cash_expenses,
        total_upi_remaining=upi_verified - total_upi_expenses,
    )
