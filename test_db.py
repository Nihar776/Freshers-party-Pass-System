import sys
from database import engine

def test_connection():
    try:
        with engine.connect() as conn:
            print("Successfully connected to the database!")
            print(f"Dialect: {engine.dialect.name}")
    except Exception as e:
        print(f"Failed to connect to the database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_connection()
