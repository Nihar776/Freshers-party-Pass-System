import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    res = conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE typname = 'paymentstatus'")).fetchall()
    print("paymentstatus ENUM values in DB:")
    for r in res:
        print(r[0])
