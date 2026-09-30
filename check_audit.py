import os
from sqlalchemy import create_engine, text

db_url = 'postgresql://postgres.fxjrzgadqfujczwvaxid:jFUHJftygkkBgf34567890@aws-0-ap-south-1.pooler.supabase.com:5432/postgres'
engine = create_engine(db_url)
try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_log';"))
        columns = [row[0] for row in result]
        print('Columns in audit_log table:', columns)
except Exception as e:
    print('Error connecting to DB:', e)
