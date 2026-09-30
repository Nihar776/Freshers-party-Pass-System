import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
url = os.getenv('DATABASE_URL')
conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()

try:
    cur.execute("ALTER TYPE paymentstatus ADD VALUE 'RESERVED'")
    print("Added RESERVED")
except Exception as e:
    print("RESERVED Error:", e)

try:
    cur.execute("ALTER TYPE paymentstatus ADD VALUE 'EXPIRED'")
    print("Added EXPIRED")
except Exception as e:
    print("EXPIRED Error:", e)

cur.close()
conn.close()
