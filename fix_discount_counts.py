import codecs
import re

# 1. student_routes.py modifications
with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/student_routes.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix batch expire
target1 = """    # Expire lazy holds
    db.query(OnlineOrder).filter(
        OnlineOrder.status == PaymentStatus.RESERVED,
        OnlineOrder.reservation_expires_at < now
    ).update({"status": PaymentStatus.EXPIRED}, synchronize_session=False)"""

replacement1 = """    # Expire lazy holds
    expired_orders = db.query(OnlineOrder).filter(
        OnlineOrder.status == PaymentStatus.RESERVED,
        OnlineOrder.reservation_expires_at < now
    ).all()
    for o in expired_orders:
        o.status = PaymentStatus.EXPIRED
        if o.discount_code_id:
            dc = db.query(DiscountCode).filter_by(id=o.discount_code_id).first()
            if dc and dc.times_used > 0:
                dc.times_used -= 1"""
code = code.replace(target1, replacement1)

# Fix existing order dynamic expire
target2 = """            existing_order.status = PaymentStatus.EXPIRED
            db.flush()"""
replacement2 = """            existing_order.status = PaymentStatus.EXPIRED
            if existing_order.discount_code_id:
                dc = db.query(DiscountCode).filter_by(id=existing_order.discount_code_id).first()
                if dc and dc.times_used > 0:
                    dc.times_used -= 1
            db.flush()"""
code = code.replace(target2, replacement2)

# Fix cancel_reservation
target3 = """    if order.status == PaymentStatus.RESERVED:
        order.status = PaymentStatus.EXPIRED
        db.commit()"""
replacement3 = """    if order.status == PaymentStatus.RESERVED:
        order.status = PaymentStatus.EXPIRED
        if order.discount_code_id:
            dc = db.query(DiscountCode).filter_by(id=order.discount_code_id).first()
            if dc and dc.times_used > 0:
                dc.times_used -= 1
        db.commit()"""
code = code.replace(target3, replacement3)

target4 = """        if order.reservation_expires_at and order.reservation_expires_at < now:
            order.status = PaymentStatus.EXPIRED
            db.commit()"""
replacement4 = """        if order.reservation_expires_at and order.reservation_expires_at < now:
            order.status = PaymentStatus.EXPIRED
            if order.discount_code_id:
                dc = db.query(DiscountCode).filter_by(id=order.discount_code_id).first()
                if dc and dc.times_used > 0:
                    dc.times_used -= 1
            db.commit()"""
code = code.replace(target4, replacement4)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/student_routes.py', 'w', encoding='utf-8') as f:
    f.write(code)


# 2. treasurer_routes.py modifications
with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/treasurer_routes.py', 'r', encoding='utf-8') as f:
    treasurer_code = f.read()

target_treasurer = """    order.status = PaymentStatus.REJECTED
    order.rejection_reason = payload.reason
    order.approved_by_id = treasurer.id"""

replacement_treasurer = """    order.status = PaymentStatus.REJECTED
    order.rejection_reason = payload.reason
    order.approved_by_id = treasurer.id
    if order.discount_code_id:
        from schema_v2 import DiscountCode
        dc = db.query(DiscountCode).filter_by(id=order.discount_code_id).first()
        if dc and dc.times_used > 0:
            dc.times_used -= 1"""
treasurer_code = treasurer_code.replace(target_treasurer, replacement_treasurer)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/treasurer_routes.py', 'w', encoding='utf-8') as f:
    f.write(treasurer_code)

# 3. Create a script to recount existing discount codes to fix the DB state
recount_script = """import sys
import os

# Add to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from schema_v2 import DiscountCode, OnlineOrder, Student, PaymentStatus

def run():
    db = SessionLocal()
    codes = db.query(DiscountCode).all()
    for dc in codes:
        # Count online orders that are RESERVED, PENDING, or VERIFIED
        online_count = db.query(OnlineOrder).filter(
            OnlineOrder.discount_code_id == dc.id,
            OnlineOrder.status.in_([PaymentStatus.RESERVED, PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED])
        ).count()
        
        # Count distributor sales that are PENDING or VERIFIED
        dist_count = db.query(Student).filter(
            Student.discount_code_id == dc.id,
            Student.payment_status.in_([PaymentStatus.PENDING_VERIFICATION, PaymentStatus.VERIFIED])
        ).count()
        
        real_count = online_count + dist_count
        if dc.times_used != real_count:
            print(f"Fixing {dc.code}: was {dc.times_used}, now {real_count}")
            dc.times_used = real_count
    
    db.commit()
    print("Done recalculating discount code usages.")

if __name__ == "__main__":
    run()
"""

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/recount_codes.py', 'w', encoding='utf-8') as f:
    f.write(recount_script)
