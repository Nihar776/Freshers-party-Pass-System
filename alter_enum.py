import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

db_url = os.getenv('DATABASE_URL')
engine = create_engine(db_url)
engine.execution_options(isolation_level="AUTOCOMMIT")

try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TYPE paymentstatus ADD VALUE 'RESERVED';"))
        conn.execute(text("ALTER TYPE paymentstatus ADD VALUE 'EXPIRED';"))
        print("Successfully added RESERVED and EXPIRED to paymentstatus!")
except Exception as e:
    print('Error:', e)
