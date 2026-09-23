import os
from sqlalchemy import create_engine, text
from config import DATABASE_URL
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def run_migration():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        logger.info("Adding food check-in columns to students table...")
        
        # Check if columns exist first (optional, but good for safety)
        try:
            conn.execute(text("ALTER TABLE students ADD COLUMN food_received BOOLEAN DEFAULT FALSE NOT NULL;"))
            logger.info("Added food_received column.")
        except Exception as e:
            logger.warning(f"food_received might already exist: {e}")
            
        try:
            conn.execute(text("ALTER TABLE students ADD COLUMN food_received_at TIMESTAMP;"))
            logger.info("Added food_received_at column.")
        except Exception as e:
            logger.warning(f"food_received_at might already exist: {e}")
            
        try:
            conn.execute(text("ALTER TABLE students ADD COLUMN food_scanned_by_id INTEGER REFERENCES users(id);"))
            logger.info("Added food_scanned_by_id column.")
        except Exception as e:
            logger.warning(f"food_scanned_by_id might already exist: {e}")

        conn.commit()
        logger.info("Migration completed successfully.")

if __name__ == "__main__":
    run_migration()
