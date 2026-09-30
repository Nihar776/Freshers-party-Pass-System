from database import engine
from sqlalchemy import text
with engine.connect() as conn:
    res = conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE typname = 'discounttype'")).fetchall()
    print([r[0] for r in res])
