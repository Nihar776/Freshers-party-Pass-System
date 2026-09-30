import os
from fastapi.testclient import TestClient
from main import app
from database import SessionLocal
from schema_v2 import User, UserRole
from session_auth import create_session_token

client = TestClient(app)

def get_admin_token():
    db = SessionLocal()
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    if not admin:
        print("No admin user found.")
        return None
    token = create_session_token(admin)
    db.close()
    return token

def test_upload():
    token = get_admin_token()
    if not token:
        return
    
    # Mock CSV data
    csv_content = b"sap_id,name,branch,year,email\n999999991,Test1,CSE,2,t1@test.com\n"
    
    print("Sending POST request to /admin/roster/import...")
    response = client.post(
        "/admin/roster/import",
        cookies={"session_token": token},
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    print("Status Code:", response.status_code)
    print("Response JSON:", response.json() if response.content else response.text)

if __name__ == "__main__":
    test_upload()
