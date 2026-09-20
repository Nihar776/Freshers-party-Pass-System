"""
migrate_add_discount_codes.py
One-time migration: creates `discount_codes` table and adds `discount_code_id`
to the existing `students` table in SQLite.
"""
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./event_passes.db")

if DB_URL.startswith("sqlite:///"):
    db_path = DB_URL.replace("sqlite:///", "")
    if db_path.startswith("./"):
        db_path = db_path[2:]
else:
    print("This script only works with SQLite databases.")
    exit(1)

print(f"Migrating database: {db_path}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check existing columns in students
cursor.execute("PRAGMA table_info(students)")
existing_columns = {row[1] for row in cursor.fetchall()}

# Create discount_codes table if not exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS discount_codes (
    id INTEGER PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    discount_type VARCHAR(16) NOT NULL,
    discount_value FLOAT NOT NULL,
    max_uses INTEGER,
    times_used INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_by_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by_id) REFERENCES users(id)
)
""")
print("  + Checked/Created discount_codes table")

cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_discount_codes_code ON discount_codes(code)")

if "discount_code_id" not in existing_columns:
    cursor.execute("ALTER TABLE students ADD COLUMN discount_code_id INTEGER REFERENCES discount_codes(id)")
    print("  + Added discount_code_id to students")
else:
    print("  - discount_code_id already exists in students")

conn.commit()
conn.close()
print("Migration complete!")
