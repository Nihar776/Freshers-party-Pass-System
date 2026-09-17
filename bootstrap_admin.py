"""
bootstrap_admin.py
One-time script to create the FIRST admin account. Every account after
this gets created through the app itself (an admin logs in and uses
POST /admin/users) - this script exists only because you can't log in to
create the first admin without already having one.

Run locally (same DATABASE_URL / .env as the real app) BEFORE the app goes
live, or against the production DB via its connection string:

    python bootstrap_admin.py
"""
import getpass
import sys

from database import Base, engine, SessionLocal
import schema_v2
from schema_v2 import User, UserRole
from security import hash_password


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    existing_admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    if existing_admin:
        print(f"An admin account already exists: '{existing_admin.username}'.")
        confirm = input("Create ANOTHER admin anyway? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    username = input("Admin username: ").strip()
    if not username:
        print("Username cannot be empty."); sys.exit(1)

    if db.query(User).filter(User.username == username).first():
        print(f"Username '{username}' already exists."); sys.exit(1)

    full_name = input("Admin full name: ").strip()
    password = getpass.getpass("Admin password: ")
    confirm_pw = getpass.getpass("Confirm password: ")
    if password != confirm_pw:
        print("Passwords didn't match."); sys.exit(1)
    if len(password) < 8:
        print("Use at least 8 characters."); sys.exit(1)

    admin = User(
        username=username,
        password_hash=hash_password(password),
        full_name=full_name or username,
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.commit()
    print(f"\nAdmin account '{username}' created. Log in at /login-page with this account,")
    print("then use it to create your treasurer, distributor, and volunteer accounts.")


if __name__ == "__main__":
    main()
