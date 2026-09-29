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
    
    # Create new tables if they don't exist
    Base.metadata.create_all(engine, tables=[
        Base.metadata.tables['online_orders'],
        Base.metadata.tables['order_members']
    ])
    logger.info("Created online_orders and order_members tables.")

    with engine.connect() as conn:
        logger.info("Altering students table for sale_channel and OTP fields...")
        
        columns_to_add = [
            ("sale_channel", "VARCHAR(50)"),
            ("otp_last_sent_at", "TIMESTAMP")
        ]
        
        for col_name, col_def in columns_to_add:
            try:
                conn.execute(text(f"ALTER TABLE students ADD COLUMN {col_name} {col_def};"))
                logger.info(f"Added {col_name} column.")
            except Exception as e:
                logger.warning(f"{col_name} might already exist: {e}")
                
        conn.commit()
        logger.info("Migration completed successfully.")

if __name__ == "__main__":
    run_migration()
