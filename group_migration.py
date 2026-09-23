import uuid
from database import SessionLocal
from schema_v2 import Student, PaymentStatus

db = SessionLocal()
students = db.query(Student).filter(
    Student.payment_status.in_([PaymentStatus.VERIFIED, PaymentStatus.PENDING_VERIFICATION]),
    Student.group_id.is_(None)
).all()

count = 0
for s in students:
    s.group_id = uuid.uuid4().hex
    s.is_group_payer = True
    count += 1

db.commit()
print(f"Migrated {count} students with missing group_ids.")
