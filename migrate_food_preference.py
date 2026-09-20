import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def run():
    print(f"Connecting to {DATABASE_URL}...")
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute("CREATE TYPE foodpreference AS ENUM ('veg', 'jain');")
        print("Created Enum foodpreference")
    except psycopg2.errors.DuplicateObject:
        conn.rollback()
        print("Enum foodpreference already exists.")

    try:
        cur.execute("ALTER TABLE students ADD COLUMN food_preference foodpreference NOT NULL DEFAULT 'veg';")
        print("Added food_preference to students table")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
        print("Column food_preference already exists.")

    conn.commit()
    cur.close()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    run()
