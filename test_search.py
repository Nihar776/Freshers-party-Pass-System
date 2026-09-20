"""Quick test of the search query."""
from database import SessionLocal
from schema_v2 import Student
from sqlalchemy import func

db = SessionLocal()

for q in ["rah", "test", "03", "Sarah"]:
    like = f"%{q.lower()}%"
    results = db.query(Student).filter(
        (func.lower(Student.name).like(like)) | (func.lower(Student.sap_id).like(like))
    ).order_by(Student.name).limit(20).all()
    print(f'Search "{q}": {len(results)} results')
    for s in results:
        print(f"  {s.sap_id} | {s.name} | {s.payment_status.value}")
    print()

db.close()
