import os
from fastapi.testclient import TestClient
from main import app
from datetime import datetime

client = TestClient(app)

def test_reserve():
    # first send OTP
    print(client.post("/api/student/send-otp", json={"sap_id": "57601260008", "email": "alienfromsadala@gmail.com"}).json())
    
    # Wait, the DB contains a hash. Let's look up the student directly.
    import os
    from dotenv import load_dotenv
    load_dotenv()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from schema_v2 import Student
    engine = create_engine(os.getenv("DATABASE_URL"))
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    st = db.query(Student).filter(Student.sap_id == "57601260008").first()
    st.otp_hash = "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92" # hash of '123456'
    st.otp_expires_at = datetime.utcnow()
    # actually need a future time
    from datetime import timedelta
    st.otp_expires_at = datetime.utcnow() + timedelta(minutes=5)
    db.commit()
    
    # verify otp
    res = client.post("/api/student/verify-otp", json={"sap_id": "57601260008", "otp": "123456"})
    print("verify otp:", res.json())
    pass_uuid = res.json().get('pass_uuid')
    
    # reserve
    print("reserving with pass_uuid:", pass_uuid)
    res = client.post("/api/student/reserve", json={
        "sap_id": "57601260008",
        "pass_uuid": pass_uuid,
        "food_preference": "veg",
        "group_sap_ids": []
    })
    print("reserve res:", res.status_code, res.text)

if __name__ == "__main__":
    test_reserve()
