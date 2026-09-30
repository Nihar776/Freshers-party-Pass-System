from database import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE discount_codes ADD COLUMN required_group_size INTEGER NULL;'))
    conn.commit()
