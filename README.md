# Event Pass & QR Verification System (V2)

A complete, end-to-end self-service portal for college events. Students can buy passes online or through distributors, admins can track sales and stats in real-time, and volunteers can scan secure QR codes at the gate using their mobile phones.

## Features

1. **Student Portal:** Students can login, purchase passes online (uploading UPI screenshots), or claim early bird discounts.
2. **Distributor System:** Offline student distributors can sell passes for cash, hand over the cash digitally to the treasurer, and issue passes.
3. **Admin & Treasurer Dashboard:** Live stats, user management, online payment verification, and dynamic configuration (e.g., turning off ticket sales, changing prices).
4. **Volunteer Gate Scanner:** A web-based QR scanner for volunteers to check in students at the gate.
5. **Dynamic Discount Engine:** Configurable early bird, group, and promo-code based discounts.
6. **Anti-Fraud & Audit Logging:** Tamper-proof QR codes signed with JWTs, atomic check-ins to prevent double entry, and a cryptographically secure audit log for all financial transactions.

## Project Structure

```text
event-pass-system/
├── main.py              # FastAPI app entry point
├── core/                # Configuration, authentication, and security logic
├── db/                  # Database connections and SQLAlchemy models (schema_v2)
├── routers/             # FastAPI endpoints (student, admin, distributor, pages)
├── services/            # Standalone services (SMTP mailer, tamper-evident audit logging)
├── scripts/             # Helper scripts for seeding mock data during development
├── templates/           # HTML templates for the UI pages (Admin, Student, Scanner)
├── static/              # CSS styles and client-side JavaScript
├── requirements.txt     # Python dependencies
└── .env.example         # Example environment variables
```

## 1. Install & Configure

```bash
# 1. Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Setup your environment variables
cp .env.example .env
```

Edit your `.env` file with the required secrets:
- Generate a `SECRET_KEY` using: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- Generate a `SESSION_SECRET_KEY` using the same command.
- Set up your `SMTP_USER` and `SMTP_PASS` (e.g., a Gmail App Password) to send the QR codes via email.

## 2. Run the Application

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Once running, you can access the various portals:
- **Login Portal:** http://localhost:8000/login-page
- **Student Dashboard:** http://localhost:8000/buy-pass
- **Admin Dashboard:** http://localhost:8000/admin-page
- **Gate Scanner:** http://localhost:8000/scanner
- **API Documentation:** http://localhost:8000/docs

*Note: On first run, the SQLite database (`event_passes.db`) is created automatically.*

## 3. Initial Setup (First Admin)

To prevent anyone from taking over an empty system, you must bootstrap the first administrator account:
1. Ensure `BOOTSTRAP_SECRET` is set in your `.env` file.
2. Visit `http://localhost:8000/bootstrap-admin-page?secret=YOUR_SECRET`
3. Create your admin account. Once the first admin is created, this endpoint permanently locks itself.

## 4. Test the scanner locally

**On your laptop webcam:** open `http://localhost:8000/scanner` in Chrome. Point it at a QR pass sent to an email.

**On an actual phone at the gate:** Phones require HTTPS for camera access in the browser. For a real trial run, expose your dev server over HTTPS with a tunnel:
```bash
npx ngrok http 8000
```
Then open the `https://...ngrok.../scanner` URL on the phone. For production, host the app on a proper domain with an SSL certificate.

## Security Architecture

- **Signature, not encryption:** The QR code contains a JWT payload. It is not encrypted, but it is cryptographically signed. Anyone can read the student's name from it, but they **cannot** edit it or forge a new pass without the server's `SECRET_KEY`.
- **Opaque Pass IDs:** Tokens carry a random `pass_id` UUID, not a sequential database integer, preventing attackers from guessing other valid pass IDs.
- **Race-safe Check-in:** The used/unused flip happens in one atomic SQL transaction, so simultaneous scans at two gates can't both succeed on the same pass.
- **Tamper-Evident Logs:** Every time a distributor collects cash or a treasurer approves a handover, a hash-chained audit log is written (similar to a blockchain) ensuring financial records cannot be secretly altered in the database without breaking the hash chain.
