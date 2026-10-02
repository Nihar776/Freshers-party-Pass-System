import sys
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
