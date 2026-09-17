"""
auth.py
Signs and verifies pass tokens (JWT / HS256) and renders them as QR images.

Security notes:
- The QR code never contains the student's raw SAP ID in the clear to a
  casual observer of the *image*... well actually it does, JWT payloads are
  base64-encoded, not encrypted, so anyone who scans the QR can decode the
  JSON payload. What they CANNOT do is forge or modify it: PyJWT verifies
  the HMAC signature against SECRET_KEY (kept only on the server), so any
  tampered token is rejected. If you need the SAP ID to be unreadable even
  to someone who scans the raw QR, encrypt the payload (e.g. with
  `cryptography.fernet.Fernet`) before/around the JWT step - see the note
  at the bottom of this file.
- pass_id in the token is the internal pass's `pass_uuid` (opaque, random),
  not the DB auto-increment integer, so a leaked token doesn't reveal how
  many passes exist or let anyone guess neighboring IDs.
"""
import time
from io import BytesIO

import jwt
import qrcode
from qrcode.image.pil import PilImage

from config import SECRET_KEY, JWT_ALGORITHM, EVENT_ID, PASS_TOKEN_TTL_HOURS


class InvalidPassToken(Exception):
    """Raised when a token fails signature verification or is malformed/expired."""


def generate_pass_token(sap_id: str, pass_uuid: str, event_id: str = EVENT_ID) -> str:
    """
    Create a signed JWT for one pass. Payload intentionally minimal:
    {sap_id, pass_id, event_id, iat[, exp]}.
    """
    payload = {
        "sap_id": sap_id,
        "pass_id": pass_uuid,
        "event_id": event_id,
        "iat": int(time.time()),
    }
    if PASS_TOKEN_TTL_HOURS:
        payload["exp"] = int(time.time()) + PASS_TOKEN_TTL_HOURS * 3600

    token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)
    # PyJWT >= 2.0 returns a str already; older versions return bytes.
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def verify_pass_token(token: str) -> dict:
    """
    Decode + verify a token's signature (and expiry, if TTL is configured).
    Raises InvalidPassToken on any failure. Never trust an unverified token.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidPassToken("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidPassToken("Invalid or tampered token") from exc

    for field in ("sap_id", "pass_id", "event_id"):
        if field not in payload:
            raise InvalidPassToken(f"Token missing required field: {field}")

    return payload


def generate_qr_image(token: str) -> BytesIO:
    """
    Render the signed token as a PNG QR code in memory (no disk writes).
    """
    qr = qrcode.QRCode(
        version=None,  # auto-size to fit the payload
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(token)
    qr.make(fit=True)

    img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Optional hardening: encrypt the JWT payload so a raw QR scan (outside your
# /verify endpoint) can't reveal the SAP ID at all. Uncomment and wire in if
# you need that extra layer - requires `pip install cryptography` and a
# separate FERNET_KEY env var (Fernet.generate_key()).
#
# from cryptography.fernet import Fernet
# from config import FERNET_KEY
# _fernet = Fernet(FERNET_KEY)
#
# def generate_pass_token(...):
#     ...
#     return _fernet.encrypt(token.encode()).decode()
#
# def verify_pass_token(token: str) -> dict:
#     try:
#         token = _fernet.decrypt(token.encode()).decode()
#     except Exception as exc:
#         raise InvalidPassToken("Invalid or tampered token") from exc
#     ...
# ---------------------------------------------------------------------------
