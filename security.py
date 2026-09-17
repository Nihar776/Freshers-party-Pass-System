"""
security.py
Password hashing via bcrypt directly. Never store or compare plaintext
passwords anywhere in the app.
"""
import bcrypt

_MAX_BCRYPT_BYTES = 72  # bcrypt silently ignores anything past this - reject upfront instead


def hash_password(plain_password: str) -> str:
    pw_bytes = plain_password.encode("utf-8")
    if len(pw_bytes) > _MAX_BCRYPT_BYTES:
        raise ValueError("Password too long (max 72 bytes)")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
