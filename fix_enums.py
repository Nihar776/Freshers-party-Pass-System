from sqlalchemy import create_engine, text
from config import DATABASE_URL
engine = create_engine(DATABASE_URL.replace('postgres://', 'postgresql://'))
with engine.connect() as conn:
    conn.execute(text("ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'RESERVED';"))
    conn.execute(text("ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'EXPIRED';"))
    conn.commit()
    print("Fixed uppercase!")
