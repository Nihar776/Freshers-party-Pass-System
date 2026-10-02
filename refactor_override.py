import codecs
import re

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/admin_routes.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace the override_student function signature and body
old_override_sig = """@router.patch("/students/{student_id}/override")
async def override_student(
    student_id: int,
    payment_status: Optional[PaymentStatus] = Form(None),
    is_used: Optional[bool] = Form(None),
    food_preference: Optional[FoodPreference] = Form(None),
    payment_mode: Optional[PaymentMode] = Form(None),
    utr_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    screenshot: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):"""

new_override_sig = """@router.patch("/students/{student_id}/override")
async def override_student(
    student_id: int,
    payment_status: Optional[PaymentStatus] = Form(None),
    is_used: Optional[bool] = Form(None),
    food_preference: Optional[FoodPreference] = Form(None),
    payment_mode: Optional[PaymentMode] = Form(None),
    utr_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    screenshot: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):"""
code = code.replace(old_override_sig, new_override_sig)

# Add logic for phone, NOT_PURCHASED cleanup, and VERIFIED assignments
target = """    if payment_status is not None:
        student.payment_status = payment_status
        new_snapshot["payment_status"] = payment_status.value if hasattr(payment_status, "value") else str(payment_status)
        if payment_status == PaymentStatus.NOT_PURCHASED:
            student.group_id = None
            student.amount = 0.0
            student.verified_by_id = None
            student.utr_number = None
            student.payment_screenshot = None
            student.screenshot_phash = None"""

replacement = """    if payment_status is not None:
        student.payment_status = payment_status
        new_snapshot["payment_status"] = payment_status.value if hasattr(payment_status, "value") else str(payment_status)
        
        if payment_status == PaymentStatus.NOT_PURCHASED:
            student.group_id = None
            student.amount = 0.0
            student.verified_by_id = None
            student.utr_number = None
            student.payment_screenshot = None
            student.screenshot_phash = None
            student.sold_at = None
            student.distributor_id = None
            student.payment_mode = None
            student.is_group_payer = False
            student.discount_code_id = None
            student.verified_at = None
            
            # Unblock any active orders
            from schema_v2 import OnlineOrder, OrderMember
            active_orders = db.query(OnlineOrder).join(OrderMember).filter(
                OrderMember.sap_id == student.sap_id,
                OnlineOrder.status.in_([PaymentStatus.RESERVED, PaymentStatus.PENDING_VERIFICATION])
            ).all()
            for order in active_orders:
                order.status = PaymentStatus.REJECTED
                order.rejection_reason = "Admin Override"
                
        elif payment_status in [PaymentStatus.VERIFIED, PaymentStatus.PENDING_VERIFICATION]:
            if not student.sold_at:
                student.sold_at = func.now()
            if not student.distributor_id:
                student.distributor_id = admin.id
            if payment_status == PaymentStatus.VERIFIED and not student.verified_by_id:
                student.verified_by_id = admin.id
                student.verified_at = func.now()
            
            if student.amount is None or student.amount == 0.0:
                from student_routes import get_price_quote, PriceQuoteRequest
                quote = get_price_quote(PriceQuoteRequest(group_size=1), db=db)
                student.amount = quote["final_price"]
                new_snapshot["amount_assigned"] = student.amount"""
code = code.replace(target, replacement)

target_email = """    if email is not None:
        student.email = email
        new_snapshot["email"] = email"""

replacement_email = """    if email is not None:
        student.email = email
        new_snapshot["email"] = email
    
    if phone is not None:
        student.phone = phone
        new_snapshot["phone"] = phone"""
code = code.replace(target_email, replacement_email)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/admin_routes.py', 'w', encoding='utf-8') as f:
    f.write(code)
