from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    res = conn.execute(text("SELECT typname FROM pg_type WHERE typname IN ('paymentstatus', 'foodpreference', 'passtype', 'paymentmode')"))
    types = [r[0] for r in res]
    print("Enum types found:", types)
    for t in types:
        res = conn.execute(text(f"SELECT enumlabel FROM pg_enum WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = '{t}')"))
        print(f"Values for {t}:", [r[0] for r in res])
