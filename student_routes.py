from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime, timedelta, timezone
import secrets
import hashlib
import base64
from typing import Optional, List
from pydantic import BaseModel
from io import BytesIO
from PIL import Image

from database import get_db, engine
from schema_v2 import (
    Student, PaymentStatus, DiscountRule, DiscountRuleType, ConditionType,
    Combinator, UpiQrCode, OnlineOrder, OrderMember, SaleChannel, PricingEffect,
    DiscountCode, DiscountType
)
from settings_manager import get_settings
from mailer import send_otp_email

router = APIRouter(prefix="/api/student", tags=["student_portal"])

# --- Rate Limiting (in-memory, simplified) ---
IP_RATE_LIMITS = {} # {ip: [timestamp1, timestamp2]}
def check_rate_limit(request: Request):
    ip = request.client.host
    now = datetime.utcnow()
    timestamps = IP_RATE_LIMITS.get(ip, [])
    # keep only last 60 seconds
    timestamps = [t for t in timestamps if (now - t).total_seconds() < 60]
    if len(timestamps) > 10:
        raise HTTPException(status_code=429, detail="Too many requests")
    timestamps.append(now)
    IP_RATE_LIMITS[ip] = timestamps

class SearchRequest(BaseModel):
    query: str

class SendOtpRequest(BaseModel):
    sap_id: str
    email: Optional[str] = None

class VerifyOtpRequest(BaseModel):
    sap_id: str
    otp: str

class ReserveRequest(BaseModel):
    sap_id: str
    pass_uuid: str
    food_preference: Optional[str] = None
    group_sap_ids: Optional[List[str]] = None
    coupon_code: Optional[str] = None

class PriceQuoteRequest(BaseModel):
    group_size: int = 1
    coupon_code: Optional[str] = None

class UploadPaymentRequest(BaseModel):
    sap_id: str
    pass_uuid: str
    utr_number: Optional[str] = None
    payment_screenshot: str  # base64

IST = timezone(timedelta(hours=5, minutes=30))
def get_ist_now():
    return datetime.now(IST)

def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()

def _average_hash(image_bytes: bytes, hash_size: int = 8) -> str:
    img = Image.open(BytesIO(image_bytes)).convert("L").resize((hash_size, hash_size))
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return hashlib.sha256(bits.encode()).hexdigest()[:16]

def validate_image(base64_str: str) -> bytes:
    try:
        # Handle "data:image/png;base64,..." prefix if present
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
        img_bytes = base64.b64decode(base64_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 encoding")
    
    if len(img_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image size exceeds 5MB")
        
    try:
        img = Image.open(BytesIO(img_bytes))
        if img.format not in ['JPEG', 'PNG', 'WEBP']:
            raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP are supported")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")
        
    return img_bytes

def get_enrolled_count(db: Session, settings: dict) -> int:
    count_distributor = settings.get("count_distributor_passes", True)
    now = datetime.utcnow()
    
    # 1. Distributor count
    query_dist = db.query(Student).filter(
        Student.payment_status.in_([PaymentStatus.VERIFIED, PaymentStatus.PENDING_VERIFICATION])
    )
    # Online orders will set Student.payment_status to VERIFIED/PENDING_VERIFICATION eventually,
    # but we will only count them if they are VERIFIED. Let's count distributor specifically:
    dist_count = 0
    if count_distributor:
        dist_count = query_dist.filter(Student.sale_channel == SaleChannel.DISTRIBUTOR).count()

    # 2. Online Order count
    # Expire lazy holds
    db.query(OnlineOrder).filter(
        OnlineOrder.status == PaymentStatus.RESERVED,
        OnlineOrder.reservation_expires_at < now
    ).update({"status": PaymentStatus.EXPIRED}, synchronize_session=False)
    db.flush()
    
    online_count = db.query(OrderMember).join(OnlineOrder).filter(
        OnlineOrder.status.in_([PaymentStatus.RESERVED, PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED])
    ).count()
    
    return dist_count + online_count

def is_rule_active(db: Session, rule: DiscountRule, enrolled_count: int, now: datetime) -> bool:
    if not rule.is_enabled: return False
    if rule.usage_cap is not None:
        used = db.query(OrderMember).join(OnlineOrder).filter(
            OnlineOrder.applied_rule_id == rule.id,
            OnlineOrder.status.in_([PaymentStatus.RESERVED, PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED])
        ).count()
        print(f"DEBUG: rule {rule.id} usage_cap={rule.usage_cap} used={used}")
        if used >= rule.usage_cap:
            return False
            
    if not rule.conditions: return True
    
    results = []
    for condition in rule.conditions:
        if condition.condition_type == ConditionType.AFTER_N: results.append(enrolled_count >= condition.val_n)
        elif condition.condition_type == ConditionType.BEFORE_N: results.append(enrolled_count < condition.val_n)
        elif condition.condition_type == ConditionType.BETWEEN_N_M: results.append(condition.val_n <= enrolled_count <= condition.val_m)
        elif condition.condition_type == ConditionType.AFTER_T: results.append(now >= condition.time_t1)
        elif condition.condition_type == ConditionType.BEFORE_T: results.append(now < condition.time_t1)
        elif condition.condition_type == ConditionType.BETWEEN_T: results.append(condition.time_t1 <= now <= condition.time_t2)
        elif condition.condition_type == ConditionType.DAILY_SLOT:
            ct = now.strftime("%H:%M")
            results.append(condition.time_slot_start <= ct <= condition.time_slot_end)
        else: results.append(False)
            
    return all(results) if rule.condition_combinator == Combinator.AND else any(results)

def get_active_rule(db: Session, is_group: bool = False):
    settings = get_settings()
    enrolled_count = get_enrolled_count(db, settings)
    now_ist = get_ist_now()
    
    rules = db.query(DiscountRule).filter(
        DiscountRule.is_enabled == True,
        DiscountRule.auto_applied == True
    ).order_by(DiscountRule.priority.desc()).all()
    
    for rule in rules:
        if (rule.type == DiscountRuleType.GROUP and not is_group) or (rule.type != DiscountRuleType.GROUP and is_group):
            continue
        if is_rule_active(db, rule, enrolled_count, now_ist):
            return rule
    return None

@router.get("/search")
def search_student(query: str, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
        
    like = f"%{query.lower()}%"
    students = db.query(Student).filter(
        (func.lower(Student.name).like(like)) | (func.lower(Student.sap_id).like(like))
    ).limit(20).all()
    results = []
    for s in students:
        masked_sap = s.sap_id
        if len(masked_sap) > 6: masked_sap = masked_sap[:4] + "****" + masked_sap[-2:]
        masked_email = ""
        if s.email:
            parts = s.email.split("@")
            if len(parts) == 2: masked_email = parts[0][0] + "****@" + parts[1]
        
        # Check active order
        has_active_order = db.query(OrderMember).join(OnlineOrder).filter(
            OrderMember.sap_id == s.sap_id,
            OnlineOrder.status.in_([PaymentStatus.RESERVED, PaymentStatus.PENDING_VERIFICATION])
        ).first() is not None
        
        status_disp = "not_purchased"
        if s.payment_status in [PaymentStatus.VERIFIED, PaymentStatus.PENDING_VERIFICATION]:
            status_disp = "purchased"
        elif has_active_order:
            status_disp = "in_progress"
            
        results.append({
            "sap_id": s.sap_id,
            "name": s.name,
            "branch": s.branch,
            "year": s.year or "",
            "masked_sap_id": masked_sap,
            "masked_email": masked_email,
            "has_email": bool(s.email and s.email.strip()),
            "payment_status": status_disp
        })
    return results

@router.post("/send-otp")
def send_otp(req: SendOtpRequest, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    check_rate_limit(request)
    student = db.query(Student).filter(Student.sap_id == req.sap_id).first()
    if not student: raise HTTPException(status_code=404, detail="Student not found")
    
    # Check if already verified or pending
    if student.payment_status in [PaymentStatus.VERIFIED, PaymentStatus.PENDING_VERIFICATION]:
        raise HTTPException(status_code=400, detail="Pass already purchased or pending.")
        
    target_email = (student.email or "").strip()
    if not target_email:
        provided_email = (req.email or "").strip()
        if not provided_email:
            raise HTTPException(status_code=400, detail="Please enter your email address to receive your OTP.")
        if "@" not in provided_email or "." not in provided_email.split("@")[-1]:
            raise HTTPException(status_code=400, detail="Please enter a valid email address.")
        target_email = provided_email
        student.email = provided_email
        db.flush()

    # Check cooldown
    now = datetime.utcnow()
    if student.otp_last_sent_at and (now - student.otp_last_sent_at).total_seconds() < 60:
        raise HTTPException(status_code=429, detail="Please wait 60s before requesting another OTP.")

    otp = str(secrets.randbelow(900000) + 100000)
    student.otp_hash = hash_otp(otp)
    student.otp_expires_at = now + timedelta(minutes=5)
    student.otp_attempts = 0
    student.otp_last_sent_at = now
    db.commit()
    
    try:
        from mailer import send_otp_email
        background_tasks.add_task(send_otp_email, target_email, student.name, otp)
    except Exception as e:
        pass # The task will be queued and handle its own errors

    masked_target = target_email
    parts = target_email.split("@")
    if len(parts) == 2:
        masked_target = parts[0][0] + "****@" + parts[1]
        
    return {"message": "OTP sent successfully", "masked_email": masked_target}
    
@router.post("/verify-otp")
def verify_otp(req: VerifyOtpRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    student = db.query(Student).filter(Student.sap_id == req.sap_id).first()
    if not student or not student.otp_hash or not student.otp_expires_at:
        raise HTTPException(status_code=400, detail="No OTP requested")
        
    if datetime.utcnow() > student.otp_expires_at:
        raise HTTPException(status_code=400, detail="OTP expired")
        
    if student.otp_attempts >= 5:
        student.otp_hash = None
        db.commit()
        raise HTTPException(status_code=400, detail="Too many attempts. Request a new OTP.")
        
    if student.otp_hash != hash_otp(req.otp):
        student.otp_attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    # Success: clear OTP
    student.otp_hash = None
    student.otp_expires_at = None
    student.otp_attempts = 0
    db.commit()
    
    # Generate pass_uuid if not exists (already default, but let's just return it as a session token)
    return {"message": "OTP verified", "pass_uuid": student.pass_uuid}

@router.get("/validate-coupon")
def validate_student_coupon(
    code: str,
    request: Request,
    db: Session = Depends(get_db)
):
    check_rate_limit(request)
    if not code:
        raise HTTPException(status_code=400, detail="Coupon code is required")
    code_upper = code.upper().strip()
    dc = db.query(DiscountCode).filter(func.upper(DiscountCode.code) == code_upper).first()
    if not dc:
        raise HTTPException(status_code=404, detail="Invalid coupon code")
    if not dc.is_active:
        raise HTTPException(status_code=400, detail="This coupon code is inactive")
    if dc.max_uses is not None and dc.times_used >= dc.max_uses:
        raise HTTPException(status_code=400, detail="This coupon code has reached its usage limit")
        
    return {
        "valid": True,
        "code": dc.code,
        "type": dc.discount_type.value if hasattr(dc.discount_type, "value") else str(dc.discount_type),
        "value": dc.discount_value
    }


@router.post("/price-quote")
def get_price_quote(req: PriceQuoteRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    base_price = float(settings.get("base_price", 500))
    count = max(1, req.group_size)
    total_base = base_price * count

    is_group = count > 1
    active_rule = get_active_rule(db, is_group=is_group)
    
    rule_price = total_base
    rule_name = None
    if active_rule:
        rule_name = active_rule.name
        if active_rule.pricing_effect == PricingEffect.FIXED:
            rule_price = active_rule.discount_value if not is_group else active_rule.group_total_price
        elif active_rule.pricing_effect == PricingEffect.FLAT_OFF:
            rule_price = max(0.0, total_base - active_rule.discount_value)
        elif active_rule.pricing_effect == PricingEffect.PERCENT_OFF:
            rule_price = max(0.0, total_base * (1.0 - (active_rule.discount_value / 100.0)))

    coupon_price = total_base
    coupon_info = None
    if req.coupon_code:
        code_upper = req.coupon_code.upper().strip()
        dc = db.query(DiscountCode).filter(func.upper(DiscountCode.code) == code_upper).first()
        if not dc:
            raise HTTPException(status_code=404, detail="Invalid coupon code")
        if not dc.is_active:
            raise HTTPException(status_code=400, detail="This coupon code is inactive")
        if dc.max_uses is not None and dc.times_used >= dc.max_uses:
            raise HTTPException(status_code=400, detail="This coupon code has reached its usage limit")
            
        dc_type = dc.discount_type.value if hasattr(dc.discount_type, "value") else str(dc.discount_type)
        if dc_type == "percentage":
            coupon_price = max(0.0, total_base * (1.0 - (dc.discount_value / 100.0)))
            discount_desc = f"{dc.discount_value}% off"
        else:
            coupon_price = max(0.0, total_base - dc.discount_value)
            discount_desc = f"₹{dc.discount_value} off"

        coupon_info = {
            "code": dc.code,
            "type": dc_type,
            "value": dc.discount_value,
            "desc": discount_desc
        }

    # Best deal
    if req.coupon_code and active_rule:
        final_price = min(rule_price, coupon_price)
    elif req.coupon_code:
        final_price = coupon_price
    elif active_rule:
        final_price = rule_price
    else:
        final_price = total_base

    return {
        "base_price": base_price,
        "group_size": count,
        "total_base": total_base,
        "final_price": round(final_price, 2),
        "discount_amount": round(max(0.0, total_base - final_price), 2),
        "rule_name": rule_name,
        "coupon": coupon_info
    }


@router.post("/reserve")
def reserve_pass(req: ReserveRequest, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.sap_id == req.sap_id, Student.pass_uuid == req.pass_uuid).first()
    if not student: raise HTTPException(status_code=401, detail="Unauthorized")
        
    now = datetime.utcnow()
    settings = get_settings()
    
    if not settings.get("portal_enabled", True):
        raise HTTPException(status_code=403, detail="Online purchases are currently closed.")
    
    # Check if this student already has an active order
    existing_order = db.query(OnlineOrder).filter(
        OnlineOrder.leader_sap_id == req.sap_id,
        OnlineOrder.status == PaymentStatus.RESERVED
    ).first()
    
    if existing_order:
        if existing_order.reservation_expires_at > now:
            # Resume existing
            return {
                "message": "Resumed existing reservation",
                "order_reference": existing_order.order_reference,
                "locked_price": existing_order.locked_total_price,
                "reservation_expires_at": existing_order.reservation_expires_at,
                "qr_id": existing_order.upi_qr_shown_id
            }
        else:
            existing_order.status = PaymentStatus.EXPIRED
            if existing_order.discount_code_id:
                old_dc = db.query(DiscountCode).filter(DiscountCode.id == existing_order.discount_code_id).first()
                if old_dc and old_dc.times_used > 0:
                    old_dc.times_used -= 1
            db.commit()
            
    # Also check if student is in any member list of an active order
    active_member = db.query(OrderMember).join(OnlineOrder).filter(
        OrderMember.sap_id == req.sap_id,
        OnlineOrder.status.in_([PaymentStatus.RESERVED, PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED])
    ).first()
    if active_member:
        raise HTTPException(status_code=400, detail="You already have an active pass or purchase in progress.")

    is_group = bool(req.group_sap_ids)
    all_saps = [req.sap_id]
    if is_group: all_saps.extend(req.group_sap_ids)
    
    # Atomic transaction for caps
    # End any pending transaction from early reads to get a fresh snapshot
    db.commit()
    # Lock the rules table exclusively to serialize concurrent reservations
    db.execute(text("LOCK TABLE discount_rules IN EXCLUSIVE MODE"))
    
    active_rule = get_active_rule(db, is_group=is_group)
    base_price = settings.get("base_price", 500)
    
    if is_group and active_rule and active_rule.group_size != len(all_saps):
        raise HTTPException(status_code=400, detail=f"Group rule requires exactly {active_rule.group_size} members.")

    total_base = base_price * len(all_saps)
    locked_price = total_base
    rule_applied = None
    applied_label = None

    if active_rule:
        rule_applied = active_rule
        applied_label = active_rule.name
        if active_rule.pricing_effect == PricingEffect.FIXED:
            locked_price = active_rule.discount_value if not is_group else active_rule.group_total_price
        elif active_rule.pricing_effect == PricingEffect.FLAT_OFF:
            locked_price = max(0.0, total_base - active_rule.discount_value)
        elif active_rule.pricing_effect == PricingEffect.PERCENT_OFF:
            locked_price = max(0.0, total_base * (1.0 - (active_rule.discount_value / 100.0)))

    dc = None
    if req.coupon_code:
        code_upper = req.coupon_code.upper().strip()
        dc = db.query(DiscountCode).filter(func.upper(DiscountCode.code) == code_upper).first()
        if not dc:
            raise HTTPException(status_code=404, detail="Invalid coupon code")
        if not dc.is_active:
            raise HTTPException(status_code=400, detail="Coupon code is inactive")
        if dc.max_uses is not None and dc.times_used >= dc.max_uses:
            raise HTTPException(status_code=400, detail="Coupon code usage limit reached")

        dc_type = dc.discount_type.value if hasattr(dc.discount_type, "value") else str(dc.discount_type)
        if dc_type == "percentage":
            coupon_price = max(0.0, total_base * (1.0 - (dc.discount_value / 100.0)))
        elif dc_type == "flat":
            coupon_price = max(0.0, total_base - dc.discount_value)
        else:
            coupon_price = total_base

        if active_rule:
            locked_price = min(locked_price, coupon_price)
            if coupon_price <= locked_price:
                applied_label = f"Coupon: {dc.code}"
        else:
            locked_price = coupon_price
            applied_label = f"Coupon: {dc.code}"

        dc.times_used += 1

    qr = db.query(UpiQrCode).filter_by(is_active=True).first()
    
    order = OnlineOrder(
        leader_sap_id=req.sap_id,
        status=PaymentStatus.RESERVED,
        locked_total_price=locked_price,
        applied_rule_id=rule_applied.id if rule_applied else None,
        discount_code_id=dc.id if dc else None,
        upi_qr_shown_id=qr.id if qr else None,
        reservation_expires_at=now + timedelta(minutes=settings.get("hold_time_minutes", 30))
    )
    db.add(order)
    db.flush()  # gets order.id without committing
    
    # Add members
    per_person = locked_price / len(all_saps) if len(all_saps) > 0 else 0
    for sap in all_saps:
        # verify they don't have active
        mem = db.query(OrderMember).join(OnlineOrder).filter(
            OrderMember.sap_id == sap,
            OnlineOrder.status.in_([PaymentStatus.RESERVED, PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED])
        ).first()
        if mem:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Student {sap} already has an active order.")
            
        om = OrderMember(
            order_id=order.id,
            sap_id=sap,
            food_preference=req.food_preference if settings.get("food_enabled") else None,
            locked_price=per_person
        )
        db.add(om)
        
    db.commit()

    return {
        "message": "Reservation successful",
        "order_reference": order.order_reference,
        "locked_price": locked_price,
        "rule_name": applied_label or "",
        "reservation_expires_at": order.reservation_expires_at,
        "qr_id": qr.id if qr else None
    }

class CancelReservationRequest(BaseModel):
    sap_id: str
    pass_uuid: str

@router.post("/cancel-reservation")
def cancel_reservation(req: CancelReservationRequest, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.sap_id == req.sap_id, Student.pass_uuid == req.pass_uuid).first()
    if not student: raise HTTPException(status_code=401, detail="Unauthorized")
        
    order = db.query(OnlineOrder).filter(
        OnlineOrder.leader_sap_id == req.sap_id,
        OnlineOrder.status == PaymentStatus.RESERVED
    ).first()
    if not order: raise HTTPException(status_code=400, detail="No active reservation found")
    
    order.status = PaymentStatus.EXPIRED
    if order.discount_code_id:
        dc = db.query(DiscountCode).filter(DiscountCode.id == order.discount_code_id).first()
        if dc and dc.times_used > 0:
            dc.times_used -= 1
    db.commit()
    return {"message": "Reservation cancelled"}

@router.post("/upload-payment")
def upload_payment(req: UploadPaymentRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.sap_id == req.sap_id, Student.pass_uuid == req.pass_uuid).first()
    if not student: raise HTTPException(status_code=401, detail="Unauthorized")
        
    order = db.query(OnlineOrder).filter(
        OnlineOrder.leader_sap_id == req.sap_id,
        OnlineOrder.status == PaymentStatus.RESERVED
    ).first()
    if not order: raise HTTPException(status_code=400, detail="No active reservation found")
        
    now = datetime.utcnow()
    if order.reservation_expires_at and order.reservation_expires_at < now:
        order.status = PaymentStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Reservation expired. Start again.")
        
    img_bytes = validate_image(req.payment_screenshot)
    phash = _average_hash(img_bytes)
    
    # Check duplicate hash in BOTH channels
    # 1. Online
    dup_online = db.query(OnlineOrder).filter(
        OnlineOrder.screenshot_phash == phash,
        OnlineOrder.id != order.id,
        OnlineOrder.status.in_([PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED])
    ).first()
    # 2. Distributor
    dup_dist = db.query(Student).filter(
        Student.screenshot_phash == phash,
        Student.payment_status.in_([PaymentStatus.VERIFIED, PaymentStatus.PENDING_VERIFICATION])
    ).first()
    
    if dup_online or dup_dist:
        raise HTTPException(status_code=400, detail="This screenshot has already been used.")

    order.utr_number = req.utr_number
    order.screenshot_phash = phash
    order.payment_screenshot = req.payment_screenshot
    order.status = PaymentStatus.PENDING_VERIFICATION
    db.commit()
    
    leader_member = db.query(OrderMember).filter(OrderMember.order_id == order.id, OrderMember.sap_id == req.sap_id).first()
    if leader_member and leader_member.student and leader_member.student.email:
        from mailer import send_pending_confirmation_email
        background_tasks.add_task(
            send_pending_confirmation_email,
            recipient_email=leader_member.student.email,
            student_name=leader_member.student.name,
            utr_number=order.utr_number
        )
    
    return {"message": "Payment uploaded successfully"}
