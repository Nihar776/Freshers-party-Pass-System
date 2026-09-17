# Event Pass & QR Verification System

Digital entry passes for the freshers' party: students get a signed QR code
by email, volunteers scan it at the gate from a phone/tablet browser, and
each pass can only ever be used once.

## How it works

1. `POST /register` saves the student in SQLite and signs a JWT containing
   `{sap_id, pass_id, event_id}` — `pass_id` is an opaque random UUID, **not**
   the database row number, so a leaked token can't be used to guess other
   students' passes. The JWT is rendered as a QR PNG and emailed.
2. At the gate, a volunteer opens `/scanner` on their phone. It scans QR
   codes with `html5-qrcode` and POSTs the raw token to `POST /verify`.
3. `/verify` checks the signature (rejects tampering instantly), looks up
   the pass, and **atomically** flips `is_used` from `False` to `True` in a
   single `UPDATE ... WHERE is_used = False` — so two volunteers scanning
   the same pass at the same instant can't both get a green light.
4. `GET /stats` gives live totals for the organizing team.

```
event-pass-system/
├── main.py              # FastAPI app & endpoints
├── models.py             # SQLAlchemy Pass model
├── auth.py                # JWT signing/verification + QR generation
├── mailer.py               # SMTP email with inline QR
├── database.py              # SQLAlchemy engine/session
├── config.py                 # env-var driven settings
├── bulk_register.py           # optional CSV bulk-registration helper
├── templates/
│   └── scanner.html             # mobile gate-scanner UI
├── requirements.txt
└── .env.example
```

## 1. Install

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
```

Then edit `.env`:

- `SECRET_KEY` — generate one with:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- `SMTP_USER` / `SMTP_PASS` — for Gmail, create a 16-character
  [App Password](https://myaccount.google.com/apppasswords) (your normal
  Gmail password will not work with `smtplib`). For SendGrid, set
  `SMTP_HOST=smtp.sendgrid.net`, `SMTP_USER=apikey`, `SMTP_PASS=<your API key>`.
- `EVENT_ID`, `EVENT_NAME`, `EVENT_VENUE`, `EVENT_DATE` — shown in the email
  and scanner header.

The app reads `.env` automatically (via `python-dotenv`) — no need to
`export` variables manually for local runs.

## 3. Run the API

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API docs (Swagger UI): http://localhost:8000/docs
- Gate scanner: http://localhost:8000/scanner

SQLite file `event_passes.db` is created automatically on first run in the
project directory.

## 4. Register students

One at a time, via Swagger UI (`/docs`) or curl:

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"sap_id":"60012345","student_name":"Asha Rao","email":"asha@example.com"}'
```

Or in bulk from a CSV with columns `sap_id,student_name,email`:

```bash
pip install requests
python bulk_register.py students.csv --base-url http://localhost:8000
```

Each successful call emails the student their QR pass.

## 5. Test the scanner locally

**On your laptop webcam:** open `http://localhost:8000/scanner` in Chrome —
it will ask for camera permission and start scanning immediately. Point it
at a QR pass shown on another screen (e.g. open the emailed PNG on your
phone).

**On an actual phone at the gate:** phones require HTTPS (or `localhost`)
for camera access in the browser, so for a real trial run:

- Simplest: expose your dev server over HTTPS with a tunnel, e.g.
  ```bash
  npx ngrok http 8000
  ```
  then open the `https://...ngrok...` URL + `/scanner` on the phone.
- For the real event, deploy behind any HTTPS reverse proxy (nginx +
  Let's Encrypt, or a platform like Render/Railway/Fly.io) and point
  volunteers' phones at `https://your-domain/scanner`.

If a phone camera fails or a QR won't scan (glare, cracked screen), use the
"Trouble scanning? Enter code manually" box on the scanner page — paste the
raw token and it verifies the same way.

## 6. Verify the anti-fraud behavior

1. Register a student, get their emailed QR, scan it once at `/scanner` →
   green **ENTRY ALLOWED**.
2. Scan the *same* QR again (or paste the same token manually) → red
   **ENTRY DENIED — Pass already used at ...**.
3. Edit even one character of a valid token and submit it via the manual
   box → red **ENTRY DENIED — Counterfeit pass: Invalid or tampered token**
   (the HMAC signature check fails).

## 7. Post-event reporting

```bash
curl http://localhost:8000/stats
```

```json
{"event_id": "FRESHERS_2026", "total_passes": 812, "total_entered": 640, "pending_entry": 172}
```

For deeper analytics (no-show lists, entry-time histograms), query
`event_passes.db` directly with any SQLite tool — every check-in records
`entered_at`, so you can chart arrival patterns after the event.

## Security notes

- **Signature, not encryption:** the JWT payload is base64-encoded, not
  secret — anyone who scans a QR can decode the JSON and read `sap_id`.
  What they *cannot* do is forge or edit it without invalidating the HMAC
  signature (`SECRET_KEY` never leaves the server). If you need the SAP ID
  hidden even from someone inspecting the raw QR bytes, see the commented
  Fernet-encryption wrapper at the bottom of `auth.py`.
- **Opaque pass IDs:** tokens carry a random `pass_uuid`, not the database's
  auto-increment integer, so a leaked/expired token doesn't reveal how many
  passes exist or let anyone guess adjacent IDs.
- **Race-safe check-in:** the used/unused flip happens in one atomic SQL
  `UPDATE` with a `WHERE is_used = False` guard, so simultaneous scans at
  two gates can't both succeed on the same pass.
- **Keep `SECRET_KEY` and `.env` out of version control** — add `.env` to
  `.gitignore`. Rotating `SECRET_KEY` after the event invalidates all
  passes, which is a reasonable thing to do once the party is over.
- Optionally set `PASS_TOKEN_TTL_HOURS` in `.env` so passes stop being
  scannable a fixed number of hours after issuance, independent of the
  `is_used` check.
