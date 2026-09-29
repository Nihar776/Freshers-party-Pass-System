# Plan: Self-Service Pass Purchase Portal + Dynamic Discount Engine

## 1. Database Schema Additions & Modifications
We will create a new migration script using `alembic` or a custom python script (like the existing `migrate_*.py` files).

### New Models
*   **DiscountRule**: Replaces hardcoded group logic.
    *   Fields: `id`, `name`, `type` (EARLY_BIRD, GROUP, CODE, etc.), `is_enabled`, `usage_cap`, `group_size`, `group_total_price`, `per_person_price`, `priority`, `pricing_effect`, `discount_value`, `auto_applied`, `condition_combinator` (AND/OR).
*   **ActivationCondition**: One-to-many from `DiscountRule`.
    *   Fields: `id`, `rule_id`, `condition_type` (AFTER_N_ENROLLED, BEFORE_TIME, AFTER_RULE_EXHAUSTED, etc.), `val_n`, `val_m`, `time_t1`, `time_t2`, `time_slot_start`, `time_slot_end`, `target_rule_id`.
*   **UpiQrCode**:
    *   Fields: `id`, `label`, `upi_id`, `payee_name`, `is_active` (Boolean).

### Alterations to Existing Models
*   **Student**:
    *   Add `PaymentStatus.RESERVED` and `PaymentStatus.EXPIRED` to enums. (Map `PENDING_APPROVAL` to existing `PENDING_VERIFICATION`).
    *   Add OTP fields: `otp_hash`, `otp_expires_at`, `otp_attempts`.
    *   Add Reservation fields: `reservation_expires_at`, `locked_price`, `applied_rule_id`, `upi_qr_shown_id`.
    *   Change `food_preference` from Enum to `String` (to support dynamic admin addition/removal without schema changes).
    *   Add `payment_screenshot_mime` or similar if needed for robust validation, or just infer from content.
*   **Settings Storage**: Store new global settings (Hold time, Food Enable Toggle, Food Types List, Food Default) in the existing `settings.json` via `settings_manager.py`.

## 2. API Routes
Create a new file `student_routes.py` (mounted at `/api/student`) and new page in `page_routes.py` (`/buy-pass`).

**Public / Student API (`student_routes.py`):**
*   `GET /search`: Returns masked student info (rate-limited).
*   `POST /send-otp`: Generates 6-digit cryptographically secure OTP, hashes it, emails it.
*   `POST /verify-otp`: Validates OTP hash, returns a signed JWT or session cookie for this purchase.
*   `POST /reserve`: Calculates active rules transactionally, locks price, sets `reservation_expires_at`, creates `RESERVED` state. (Also handles group flow by reserving multiple SAP IDs at once).
*   `POST /upload-payment`: Accepts screenshot upload (validates MIME), transitions `RESERVED` -> `PENDING_VERIFICATION`.
*   `GET /status`: Checks current status (useful for polling or revisiting the page).

**Treasurer Additions (`treasurer_routes.py`):**
*   `GET /online-requests`: Fetch all online purchases (Pending, Approved, Rejected, Expired).
*   `POST /online-requests/approve`: Bulk or single approve (generates pass, sends email).
*   `POST /online-requests/reject`: Single reject with reason.

**Admin Additions (`admin_routes.py`):**
*   Endpoints for CRUD on `DiscountRule`, `ActivationCondition`, `UpiQrCode`.
*   Endpoints to update dynamic global settings (food preferences, hold times).
*   Simulate pricing endpoint (`POST /simulate-pricing`).

## 3. Discount Engine Logic (Lazy Expiry & Transactions)
*   **Enrolled Calculation**: Computed by summing students where status in `[RESERVED, PENDING_VERIFICATION, VERIFIED]` (excluding expired reservations). Distributor passes count based on global setting.
*   **Race Conditions**: Handled by doing an atomic check and update within a database transaction when assigning the `applied_rule_id`.
*   **Lazy Expiry**: No background cron needed. Any read of the cap or current rules will first logically ignore `RESERVED` passes whose `reservation_expires_at` is in the past. We will also run a fast `UPDATE ... SET status=EXPIRED WHERE status=RESERVED and reservation_expires_at < now()` upon every write to maintain DB cleanliness.

## 4. UI Changes
*   **New `templates/buy-pass.html`**: Mobile-first Vue/Vanilla JS app for the student flow (Search -> OTP -> Reserve -> Pay -> Status).
*   **`templates/admin.html`**: New tabs for "Discount Engine", "UPI QRs", and "Event Settings" (Food).
*   **`templates/treasurer.html`**: New tab for "Online Requests" with screenshot zooming and action buttons.
*   **`templates/distributor.html`**: Hide/show food based on the new global food toggle.

## 5. Food Settings Handling
*   If `Food Toggle == OFF`, any food preference field in the DB is ignored, UI hides the selector everywhere.
*   If `Food Toggle == ON`, the dynamic list from `settings.json` is used.

## What I need from you
Please review this plan. Are you okay with:
1.  Changing `Student.food_preference` to a pure string to handle dynamic choices, removing the SQLite native enum constraint for that column?
2.  Mapping your "PENDING_APPROVAL" state to the existing `PaymentStatus.PENDING_VERIFICATION`?
3.  Using `settings.json` for global settings like food types?

Let me know if I should proceed with the implementation.
