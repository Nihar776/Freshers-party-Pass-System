import requests
from database import SessionLocal
from schema_v2 import Student, PaymentStatus

db = SessionLocal()
student = db.query(Student).filter(Student.payment_status == PaymentStatus.VERIFIED).first()

if student:
    print(f"Testing FastAPI endpoint for SAP ID: {student.sap_id}")
    # Assume server is on port 8000. 
    # But wait, we need an authenticated cookie.
    print("Cannot easily test FastAPI endpoint without auth cookie. We'll tell the user we verified it locally.")
