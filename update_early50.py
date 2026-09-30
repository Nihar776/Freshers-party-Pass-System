from database import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text("UPDATE discount_codes SET discount_type='fixed' WHERE code='EARLY50'"))
    conn.commit()
