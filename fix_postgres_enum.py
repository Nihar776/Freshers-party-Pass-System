from database import engine
from sqlalchemy import text
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TYPE discounttype ADD VALUE 'FIXED'"))
        conn.commit()
    except Exception as e:
        print("Add value failed:", e)
        conn.rollback()
    
    conn.execute(text("UPDATE discount_codes SET discount_type='FIXED' WHERE discount_type='fixed'"))
    conn.commit()
