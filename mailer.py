"""
mailer.py
Sends the event pass email with the QR code attached inline (CID) so it
renders directly in the email body in most clients, with a PNG attachment
as a fallback for clients that block inline images.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from io import BytesIO

from config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASS,
    SMTP_FROM_NAME,
    SMTP_USE_STARTTLS,
    EVENT_NAME,
    EVENT_VENUE,
    EVENT_DATE,
)

CID = "qr_pass_image"


def _build_html(student_name: str, sap_id: str) -> str:
    return f"""\
<html>
  <body style="margin:0;padding:0;background:#0f1117;font-family:Segoe UI,Arial,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;padding:32px 0;">
      <tr>
        <td align="center">
          <table width="480" cellpadding="0" cellspacing="0"
                 style="background:#171a23;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="background:#5b2ce6;padding:24px 28px;">
                <p style="margin:0;color:#e8e3ff;font-size:13px;letter-spacing:.04em;">
                  YOUR ENTRY PASS
                </p>
                <h1 style="margin:6px 0 0;color:#ffffff;font-size:22px;">{EVENT_NAME}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px 8px;color:#e6e6ea;">
                <p style="margin:0 0 12px;font-size:15px;">Hi {student_name},</p>
                <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#b7b7c2;">
                  You're confirmed for {EVENT_NAME}. Show the QR code below at the
                  entry gate - a volunteer will scan it and hand you your wristband.
                  Each code works once, so don't share a screenshot with anyone else.
                </p>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:8px 28px 24px;">
                <img src="cid:{CID}" width="220" height="220"
                     alt="Entry QR code" style="display:block;border-radius:8px;" />
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 24px;color:#b7b7c2;font-size:13px;line-height:1.7;">
                <p style="margin:0 0 4px;"><strong style="color:#e6e6ea;">Venue:</strong> {EVENT_VENUE}</p>
                <p style="margin:0 0 4px;"><strong style="color:#e6e6ea;">Date:</strong> {EVENT_DATE}</p>
                <p style="margin:0;"><strong style="color:#e6e6ea;">SAP ID:</strong> {sap_id}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 28px 24px;border-top:1px solid #262a38;">
                <p style="margin:0;color:#7c7f8c;font-size:12px;line-height:1.6;">
                  Keep this email private - the QR code is your only entry pass and
                  cannot be reissued if forwarded or leaked to someone else.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def send_pass_email(
    recipient_email: str,
    student_name: str,
    qr_image_bytes: BytesIO,
    sap_id: str = "",
) -> None:
    """
    Sends the pass email via SMTP (Gmail or SendGrid SMTP relay both work
    with these settings - see .env.example). Raises on failure so the
    caller (the /register endpoint) can surface a clear error instead of
    silently losing the pass.
    """
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError(
            "SMTP_USER / SMTP_PASS are not configured. Set them in your "
            "environment (see .env.example) before sending pass emails."
        )

    msg = MIMEMultipart("related")
    msg["Subject"] = f"Your entry pass - {EVENT_NAME}"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = recipient_email

    alt = MIMEMultipart("alternative")
    msg.attach(alt)

    text_fallback = (
        f"Hi {student_name},\n\n"
        f"You're confirmed for {EVENT_NAME} at {EVENT_VENUE} on {EVENT_DATE}.\n"
        f"Your entry pass QR code is attached as a PNG - show it at the gate "
        f"for your wristband. SAP ID: {sap_id}\n"
    )
    alt.attach(MIMEText(text_fallback, "plain"))
    alt.attach(MIMEText(_build_html(student_name, sap_id), "html"))

    qr_image_bytes.seek(0)
    qr_bytes = qr_image_bytes.read()

    inline_img = MIMEImage(qr_bytes, name="entry_pass_qr.png")
    inline_img.add_header("Content-ID", f"<{CID}>")
    inline_img.add_header("Content-Disposition", "inline", filename="entry_pass_qr.png")
    msg.attach(inline_img)

    attachment_img = MIMEImage(qr_bytes, name="entry_pass_qr.png")
    attachment_img.add_header(
        "Content-Disposition", "attachment", filename="entry_pass_qr.png"
    )
    msg.attach(attachment_img)

    max_retries = 2
    for attempt in range(max_retries):
        try:
            if SMTP_USE_STARTTLS:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_USER, [recipient_email], msg.as_string())
            else:
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_USER, [recipient_email], msg.as_string())
            break
        except Exception as e:
            if attempt < max_retries - 1:
                import time
                time.sleep(2)
            else:
                raise e
