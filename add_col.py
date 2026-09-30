import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

engine = create_engine(os.getenv('DATABASE_URL'))
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE online_orders ADD COLUMN discount_code_id INTEGER REFERENCES discount_codes(id);"))
    print("Added discount_code_id column")
