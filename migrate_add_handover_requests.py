import sqlite3
import os

DB_PATH = "event_passes.db"

def run_migration():
    if not os.path.exists(DB_PATH):
        print(f"Error: {DB_PATH} not found.")
        return

    print("Connecting to database...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Create cash_handover_requests table
        print("Creating cash_handover_requests table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cash_handover_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                distributor_id INTEGER NOT NULL,
                amount FLOAT NOT NULL,
                status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
                created_at DATETIME NOT NULL,
                resolved_at DATETIME,
                resolved_by_id INTEGER,
                FOREIGN KEY(distributor_id) REFERENCES users(id),
                FOREIGN KEY(resolved_by_id) REFERENCES users(id)
            )
        """)
        conn.commit()
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
