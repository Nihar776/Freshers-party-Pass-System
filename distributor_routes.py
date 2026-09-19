"""
distributor_routes.py
The distributor's world: search the pre-loaded roster, sell a pass (cash
issues the QR immediately; UPI goes into the treasurer's verification
queue), and check their own sales / outstanding cash balance.
"""
import hashlib
import base64
from io import BytesIO
from typing import Optional, List
from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy import update, func
from sqlalchemy.orm import Session
from PIL import Image

from database import get_db
from schema_v2 import Student, User, UserRole, PaymentStatus, PaymentMode, PassType, CashHandover
from session_auth import require_role
from audit import write_audit_log
from auth import generate_pass_token, generate_qr_image
from mailer import send_pass_email
from config import PASS_PRICE

router = APIRouter(prefix="/distributor", tags=["distributor"])


# ---------------------------------------------------------------------------
# Perceptual hash - deliberately simple (average hash over PIL only, no
# extra dependency). Good enough to catch "exact same screenshot reused for
# a second SAP ID" which is the common cheat; won't catch a screenshot
# that's been cropped/re-photographed. Flag for human review, never
# auto-block - false positives are possible.
# ---------------------------------------------------------------------------
def _average_hash(image_bytes: bytes, hash_size: int = 8) -> str:
    img = Image.open(BytesIO(image_bytes)).convert("L").resize((hash_size, hash_size))
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return hashlib.sha256(bits.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class StudentSearchResult(BaseModel):
    sap_id: str
    name: str
    branch: str
    gender: Optional[str]
    payment_status: PaymentStatus

    class Config:
        from_attributes = True


class SellResult(BaseModel):
    message: str
    sap_id: str
    payment_status: PaymentStatus
    duplicate_screenshot_warning: bool = False


class GroupSellResult(BaseModel):
    message: str
    sap_ids: List[str]
    duplicate_screenshot_warning: bool = False


class MySaleSummary(BaseModel):
    sap_id: str
    name: str
    pass_type: PassType
    payment_mode: Optional[PaymentMode]
    amount: Optional[float]
    payment_status: PaymentStatus
    sold_at: Optional[str]

    class Config:
        from_attributes = True


class CashBalanceResponse(BaseModel):
    total_cash_collected: float
    total_handed_over: float
    outstanding_with_you: float


# ---------------------------------------------------------------------------
# Search - read-only, scoped to what a distributor actually needs to see
# ---------------------------------------------------------------------------
@router.get("/search", response_model=list[StudentSearchResult])
def search_students(
    query: str = Query(..., min_length=2, description="Partial name or SAP ID"),
    branch: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.DISTRIBUTOR)),
):
    like = f"%{query}%"
    q = db.query(Student).filter((Student.name.ilike(like)) | (Student.sap_id.ilike(like)))
    if branch:
        q = q.filter(Student.branch == branch)
    return q.order_by(Student.name).limit(20).all()


# ---------------------------------------------------------------------------
# Sell a pass
# ---------------------------------------------------------------------------
@router.post("/sell", response_model=SellResult)
def sell_pass(
    sap_id: str = Form(...),
    pass_type: PassType = Form(PassType.FULL),
    payment_mode: PaymentMode = Form(...),
    utr_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),  # only needed if the roster row lacks one
    screenshot: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    distributor: User = Depends(require_role(UserRole.DISTRIBUTOR)),
):
    student = db.query(Student).filter(Student.sap_id == sap_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="SAP ID not found in roster")

    if student.payment_status in (PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED):
        raise HTTPException(
            status_code=409,
            detail=f"Pass already {student.payment_status.value} for {student.name} ({student.sap_id})",
        )

    if payment_mode == PaymentMode.UPI:
        if not utr_number or not utr_number.strip():
            raise HTTPException(status_code=400, detail="UTR number is required for UPI payments")
        if not screenshot:
            raise HTTPException(status_code=400, detail="Payment screenshot is required for UPI payments")

    resolved_email = email or student.email
    if not resolved_email:
        raise HTTPException(status_code=400, detail="No email on file - please provide one to send the pass")

    old_snapshot = {"payment_status": student.payment_status.value}

    duplicate_warning = False
    screenshot_b64 = None
    phash = None
    if screenshot:
        img_bytes = screenshot.file.read()
        try:
            phash = _average_hash(img_bytes)
        except Exception:
            raise HTTPException(status_code=400, detail="Uploaded file isn't a readable image")
        duplicate_warning = db.query(Student).filter(
            Student.screenshot_phash == phash, Student.sap_id != sap_id
        ).first() is not None
        screenshot_b64 = base64.b64encode(img_bytes).decode("utf-8")

    # --- Atomic guard: only proceed if still unsold (handles two distributors racing) ---
    result = db.execute(
        update(Student)
        .where(
            Student.id == student.id,
            Student.payment_status.in_([PaymentStatus.NOT_PURCHASED, PaymentStatus.REJECTED]),
        )
        .values(
            pass_type=pass_type,
            payment_mode=payment_mode,
            amount=PASS_PRICE,
            email=resolved_email,
            distributor_id=distributor.id,
            utr_number=utr_number,
            payment_screenshot=screenshot_b64,
            screenshot_phash=phash,
            sold_at=func.now(),
            payment_status=(
                PaymentStatus.VERIFIED if payment_mode == PaymentMode.CASH
                else PaymentStatus.PENDING_VERIFICATION
            ),
            # cash sales are self-verified by the distributor collecting real money
            verified_by_id=distributor.id if payment_mode == PaymentMode.CASH else None,
            verified_at=func.now() if payment_mode == PaymentMode.CASH else None,
            rejection_reason=None,
        )
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pass was just sold by someone else - refresh and check")

    db.refresh(student)

    write_audit_log(
        db,
        user_id=distributor.id,
        action="sale_created",
        table_name="students",
        record_id=student.id,
        old_value=old_snapshot,
        new_value={
            "payment_status": student.payment_status.value,
            "payment_mode": payment_mode.value,
            "amount": PASS_PRICE,
            "duplicate_screenshot_warning": duplicate_warning,
        },
    )
    db.commit()
    db.refresh(student)

    if payment_mode == PaymentMode.CASH:
        # Cash is trusted immediately - issue the QR now.
        token = generate_pass_token(sap_id=student.sap_id, pass_uuid=student.pass_uuid)
        qr_image = generate_qr_image(token)
        try:
            send_pass_email(
                recipient_email=student.email,
                student_name=student.name,
                qr_image_bytes=qr_image,
                sap_id=student.sap_id,
            )
        except Exception as exc:
            # Sale is already recorded - don't lose it over an email hiccup,
            # surface the failure so it can be resent.
            raise HTTPException(
                status_code=502, detail=f"Pass recorded but email failed to send: {exc}"
            ) from exc
        message = "Cash sale recorded - pass emailed immediately"
    else:
        message = "UPI sale recorded - pending treasurer verification before the pass is sent"

    return SellResult(
        message=message,
        sap_id=student.sap_id,
        payment_status=student.payment_status,
        duplicate_screenshot_warning=duplicate_warning,
    )


# ---------------------------------------------------------------------------
# Group Sales and Discounts
# ---------------------------------------------------------------------------
def calculate_discount(group_size: int, date: Optional[datetime] = None) -> float:
    if date is None:
        date = datetime.now()
    
    # Mon (21/9): Group of 6 gets 10% off, Group of 8 gets 12% off.
    # Tue (22/9): Group of 8 gets 10% off, Group of 10 gets 12% off.
    # Wed (23/9): No discounts.
    if date.month == 9:
        if date.day == 21:  # Monday
            if group_size >= 8:
                return 0.12
            elif group_size >= 6:
                return 0.10
        elif date.day == 22:  # Tuesday
            if group_size >= 10:
                return 0.12
            elif group_size >= 8:
                return 0.10
    
    return 0.0


@router.post("/sell-group", response_model=GroupSellResult)
def sell_group(
    sap_ids: List[str] = Form(...),
    payer_sap_id: str = Form(...),
    payment_mode: PaymentMode = Form(...),
    utr_number: Optional[str] = Form(None),
    screenshot: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    distributor: User = Depends(require_role(UserRole.DISTRIBUTOR)),
):
    if not sap_ids:
        raise HTTPException(status_code=400, detail="Group must have at least one student")

    if payment_mode == PaymentMode.UPI:
        if not utr_number or not utr_number.strip():
            raise HTTPException(status_code=400, detail="UTR number is required for UPI payments")
        if not screenshot:
            raise HTTPException(status_code=400, detail="Payment screenshot is required for UPI payments")

    students = db.query(Student).filter(Student.sap_id.in_(sap_ids)).all()
    if len(students) != len(sap_ids):
        found_saps = {s.sap_id for s in students}
        missing = set(sap_ids) - found_saps
        raise HTTPException(status_code=404, detail=f"SAP IDs not found: {', '.join(missing)}")

    for student in students:
        if student.payment_status in (PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED):
            raise HTTPException(
                status_code=409,
                detail=f"Pass already {student.payment_status.value} for {student.name} ({student.sap_id})"
            )
        if not student.email:
            raise HTTPException(status_code=400, detail=f"No email on file for {student.sap_id} - cannot process group sale")

    group_size = len(sap_ids)
    discount = calculate_discount(group_size)
    total_base_amount = PASS_PRICE * group_size
    final_total_amount = total_base_amount * (1.0 - discount)
    amount_per_student = final_total_amount / group_size

    duplicate_warning = False
    screenshot_b64 = None
    phash = None
    if screenshot:
        img_bytes = screenshot.file.read()
        try:
            phash = _average_hash(img_bytes)
        except Exception:
            raise HTTPException(status_code=400, detail="Uploaded file isn't a readable image")
        duplicate_warning = db.query(Student).filter(
            Student.screenshot_phash == phash, ~Student.sap_id.in_(sap_ids)
        ).first() is not None
        screenshot_b64 = base64.b64encode(img_bytes).decode("utf-8")

    # --- Atomic guard: update all selected students ---
    student_ids = [s.id for s in students]
    group_id = uuid.uuid4().hex

    result = db.execute(
        update(Student)
        .where(
            Student.id.in_(student_ids),
            Student.payment_status.in_([PaymentStatus.NOT_PURCHASED, PaymentStatus.REJECTED]),
        )
        .values(
            pass_type=PassType.FULL,
            payment_mode=payment_mode,
            amount=amount_per_student,
            distributor_id=distributor.id,
            group_id=group_id,
            sold_at=func.now(),
            payment_status=(
                PaymentStatus.VERIFIED if payment_mode == PaymentMode.CASH
                else PaymentStatus.PENDING_VERIFICATION
            ),
            verified_by_id=distributor.id if payment_mode == PaymentMode.CASH else None,
            verified_at=func.now() if payment_mode == PaymentMode.CASH else None,
            rejection_reason=None,
        )
    )
    if result.rowcount != len(students):
        db.rollback()
        raise HTTPException(status_code=409, detail="One or more passes were sold by someone else - refresh and check")

    payer_student = next((s for s in students if s.sap_id == payer_sap_id), None)
    if not payer_student:
        db.rollback()
        raise HTTPException(status_code=400, detail="Payer SAP ID not found in group")

    db.execute(
        update(Student)
        .where(Student.id == payer_student.id)
        .values(
            is_group_payer=True,
            utr_number=utr_number,
            payment_screenshot=screenshot_b64,
            screenshot_phash=phash,
        )
    )

    for student in students:
        db.refresh(student)

        write_audit_log(
            db,
            user_id=distributor.id,
            action="group_sale_created",
            table_name="students",
            record_id=student.id,
            old_value={"payment_status": PaymentStatus.NOT_PURCHASED.value},
            new_value={
                "payment_status": student.payment_status.value,
                "payment_mode": payment_mode.value,
                "amount": amount_per_student,
                "duplicate_screenshot_warning": duplicate_warning,
            },
        )
    db.commit()

    email_failures = 0
    if payment_mode == PaymentMode.CASH:
        for student in students:
            db.refresh(student)
            token = generate_pass_token(sap_id=student.sap_id, pass_uuid=student.pass_uuid)
            qr_image = generate_qr_image(token)
            try:
                send_pass_email(
                    recipient_email=student.email,
                    student_name=student.name,
                    qr_image_bytes=qr_image,
                    sap_id=student.sap_id,
                )
            except Exception as exc:
                import logging
                logging.error(f"Failed to send group pass email to {student.sap_id}: {exc}")
                email_failures += 1
        
        if email_failures > 0:
            message = f"Cash sale recorded. {len(students) - email_failures} emails sent, {email_failures} failed."
        else:
            message = f"Cash sale recorded for group - {len(students)} passes emailed immediately"
    else:
        message = f"UPI sale recorded for group - {len(students)} passes pending treasurer verification"

    return GroupSellResult(
        message=message,
        sap_ids=sap_ids,
        duplicate_screenshot_warning=duplicate_warning,
    )


# ---------------------------------------------------------------------------
# Distributor's own view: their sales, their outstanding cash
# ---------------------------------------------------------------------------
@router.get("/my-sales", response_model=list[MySaleSummary])
def my_sales(
    db: Session = Depends(get_db),
    distributor: User = Depends(require_role(UserRole.DISTRIBUTOR)),
):
    rows = (
        db.query(Student)
        .filter(Student.distributor_id == distributor.id)
        .order_by(Student.sold_at.desc())
        .all()
    )
    return [
        MySaleSummary(
            sap_id=r.sap_id, name=r.name, pass_type=r.pass_type, payment_mode=r.payment_mode,
            amount=r.amount, payment_status=r.payment_status,
            sold_at=r.sold_at.isoformat() if r.sold_at else None,
        )
        for r in rows
    ]


@router.get("/my-cash-balance", response_model=CashBalanceResponse)
def my_cash_balance(
    db: Session = Depends(get_db),
    distributor: User = Depends(require_role(UserRole.DISTRIBUTOR)),
):
    total_cash = db.query(func.coalesce(func.sum(Student.amount), 0.0)).filter(
        Student.distributor_id == distributor.id,
        Student.payment_mode == PaymentMode.CASH,
        Student.payment_status == PaymentStatus.VERIFIED,
    ).scalar()

    total_handed_over = db.query(func.coalesce(func.sum(CashHandover.amount), 0.0)).filter(
        CashHandover.distributor_id == distributor.id
    ).scalar()

    return CashBalanceResponse(
        total_cash_collected=total_cash,
        total_handed_over=total_handed_over,
        outstanding_with_you=total_cash - total_handed_over,
    )


@router.post("/resend-email/{sap_id}")
def resend_email(
    sap_id: str,
    db: Session = Depends(get_db),
    distributor: User = Depends(require_role(UserRole.DISTRIBUTOR)),
):
    student = db.query(Student).filter(Student.sap_id == sap_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.payment_status != PaymentStatus.VERIFIED:
        raise HTTPException(status_code=400, detail="Cannot resend email - pass is not verified")
    if not student.email:
        raise HTTPException(status_code=400, detail="No email address on file for this student")

    token = generate_pass_token(sap_id=student.sap_id, pass_uuid=student.pass_uuid)
    qr_image = generate_qr_image(token)
    try:
        send_pass_email(
            recipient_email=student.email,
            student_name=student.name,
            qr_image_bytes=qr_image,
            sap_id=student.sap_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to resend email: {exc}") from exc

    return {"message": "Email sent successfully"}
