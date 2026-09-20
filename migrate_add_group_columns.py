"""
migrate_add_group_columns.py
One-time migration: adds `group_id` and `is_group_payer` columns to the
existing `students` table in SQLite. Safe to run multiple times.
"""
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./event_passes.db")

# Extract file path from sqlite URL
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

# Check existing columns
cursor.execute("PRAGMA table_info(students)")
existing_columns = {row[1] for row in cursor.fetchall()}
print(f"Existing columns: {sorted(existing_columns)}")

migrations = []

if "group_id" not in existing_columns:
    migrations.append("ALTER TABLE students ADD COLUMN group_id VARCHAR(32)")
    print("  + Adding group_id")

if "is_group_payer" not in existing_columns:
    migrations.append("ALTER TABLE students ADD COLUMN is_group_payer BOOLEAN DEFAULT 0 NOT NULL")
    print("  + Adding is_group_payer")

if not migrations:
    print("✅ No migration needed — all columns already exist.")
else:
    for sql in migrations:
        cursor.execute(sql)
    conn.commit()
    print(f"✅ Migration complete! Added {len(migrations)} column(s).")

conn.close()
