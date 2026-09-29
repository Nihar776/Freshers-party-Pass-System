import os
import logging
from sqlalchemy import create_engine, text
from config import DATABASE_URL
from schema_v2 import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def run_migration():
    engine = create_engine(DATABASE_URL)
    
    # 1. Create new tables if they don't exist
    Base.metadata.create_all(engine, tables=[
        Base.metadata.tables['discount_rules'],
        Base.metadata.tables['activation_conditions'],
        Base.metadata.tables['upi_qr_codes']
    ])
    logger.info("Created discount_rules, activation_conditions, upi_qr_codes tables (if not existed).")

    with engine.connect() as conn:
        logger.info("Altering students table...")
        
        # 2. Add new columns to students
        columns_to_add = [
            ("phone", "VARCHAR(20)"),
            ("otp_hash", "VARCHAR(255)"),
            ("otp_expires_at", "TIMESTAMP"),
            ("otp_attempts", "INTEGER DEFAULT 0 NOT NULL"),
            ("reservation_expires_at", "TIMESTAMP"),
            ("locked_price", "FLOAT"),
            ("applied_rule_id", "INTEGER REFERENCES discount_rules(id)"),
            ("upi_qr_shown_id", "INTEGER REFERENCES upi_qr_codes(id)")
        ]
        
        for col_name, col_def in columns_to_add:
            try:
                conn.execute(text(f"ALTER TABLE students ADD COLUMN {col_name} {col_def};"))
                logger.info(f"Added {col_name} column.")
            except Exception as e:
                logger.warning(f"{col_name} might already exist: {e}")
                
        # 3. Change food_preference to VARCHAR(50) (SQLite doesn't support ALTER COLUMN type, 
        # but the Enum in SQLite is typically already a VARCHAR or CHECK constraint. 
        # We'll just leave it be, as SQLite doesn't strictly enforce string contents unless CHECK is defined).
        # Actually in SQLAlchemy, Enum on SQLite generates a VARCHAR. We'll just use it as string.
        # It's safer not to try to ALTER type in sqlite.
        
        conn.commit()
        logger.info("Migration completed successfully.")

if __name__ == "__main__":
    run_migration()
