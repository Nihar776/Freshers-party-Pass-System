import asyncio
import os
from dotenv import load_dotenv
from fastapi import UploadFile
from fastapi.datastructures import Headers
from roster_routes import import_roster
from database import SessionLocal
from schema_v2 import User, UserRole

load_dotenv()
db = SessionLocal()

# We need an admin user that actually exists or just mock one. 
# In import_roster, it uses `admin.id` for audit logging.
admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
if not admin:
    admin = User(id=9999, username='testadmin', role=UserRole.ADMIN)

class MockFile:
    def __init__(self, content):
        self.content = content
    def read(self):
        return self.content

f = UploadFile(filename='test.csv', file=MockFile(b'sap_id,name,branch,year,email\n999999999,TestUser,CSE,2,test@example.com\n'))

try:
    print("Testing import_roster...")
    result = import_roster(file=f, db=db, admin=admin)
    print("Success!", result)
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    print("Rolling back transaction to avoid touching prod DB...")
    db.rollback()
    db.close()
