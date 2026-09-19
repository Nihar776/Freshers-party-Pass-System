"""
schema_v2.py
Full database schema for the extended system: roster + pass sales,
role-based auth, cash custody tracking, treasurer verification,
expenses/budget, and a tamper-evident audit log.

This is a design document expressed as SQLAlchemy models - not yet wired
into the existing app. Review the shape first; we'll migrate main.py,
auth.py etc. to use this once you're happy with it.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Enum, Text, JSON
)
from sqlalchemy.orm import relationship

from database import Base  # shared Base/metadata - same registry as the rest of the app


def _uuid() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Users & roles (admins, treasurer, distributors all live in one table)
# ---------------------------------------------------------------------------
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TREASURER = "treasurer"
    DISTRIBUTOR = "distributor"
    VOLUNTEER = "volunteer"  # gate-night QR scanning only


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # bcrypt, never plaintext
    full_name = Column(String(120), nullable=False)
    role = Column(Enum(UserRole), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)  # admin can disable instead of delete
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # which admin added them


# ---------------------------------------------------------------------------
# Students / Passes - one row per student, pre-loaded from your roster.
# "Buying a pass" is an UPDATE to this row, never a new insert.
# ---------------------------------------------------------------------------
class PaymentMode(str, enum.Enum):
    CASH = "cash"
    UPI = "upi"


class FundType(str, enum.Enum):
    CASH = "cash"
    UPI = "upi"


class PassType(str, enum.Enum):
    FULL = "full"
    NO_FOOD = "no_food"


class PaymentStatus(str, enum.Enum):
    NOT_PURCHASED = "not_purchased"        # roster row, no sale yet
    PENDING_VERIFICATION = "pending_verification"  # UPI sale, awaiting treasurer
    VERIFIED = "verified"                  # cash: instant. UPI: after treasurer approval
    REJECTED = "rejected"                  # treasurer rejected - SAP unlocks for resale


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True)
    pass_uuid = Column(String(32), unique=True, index=True, default=_uuid, nullable=False)

    # --- Roster data (pre-loaded, read-only to distributors) ---
    sap_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(120), nullable=False)
    branch = Column(String(64), nullable=False, index=True)
    gender = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)  # can be filled at sale time if roster lacks it

    # --- Sale data (filled by distributor at point of sale) ---
    pass_type = Column(Enum(PassType), default=PassType.FULL, nullable=False)
    payment_mode = Column(Enum(PaymentMode), nullable=True)
    amount = Column(Float, nullable=True)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.NOT_PURCHASED,
                             nullable=False, index=True)

    distributor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sold_at = Column(DateTime, nullable=True)

    # --- UPI-specific verification fields ---
    utr_number = Column(String(32), nullable=True)          # student/distributor-entered UTR
    payment_screenshot = Column(Text, nullable=True)         # base64 or file path
    screenshot_phash = Column(String(64), nullable=True)     # perceptual hash, for reuse detection
    verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # treasurer
    verified_at = Column(DateTime, nullable=True)
    rejection_reason = Column(String(255), nullable=True)

    # --- Gate check-in ---
    is_used = Column(Boolean, default=False, nullable=False, index=True)
    entered_at = Column(DateTime, nullable=True)
    scanned_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # which volunteer scanned them

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)  # roster import time

    distributor = relationship("User", foreign_keys=[distributor_id])
    verified_by = relationship("User", foreign_keys=[verified_by_id])
    scanned_by = relationship("User", foreign_keys=[scanned_by_id])


# ---------------------------------------------------------------------------
# Cash custody - separate ledger, NOT the same thing as pass verification.
# Cash sales are trusted immediately (pass issued), but the physical money
# stays "with the distributor" until a handover event clears it.
# ---------------------------------------------------------------------------
class CashHandover(Base):
    __tablename__ = "cash_handovers"

    id = Column(Integer, primary_key=True)
    distributor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    treasurer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    handed_over_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(String(255), nullable=True)  # e.g. discrepancy notes if counted amount differed

    distributor = relationship("User", foreign_keys=[distributor_id])
    treasurer = relationship("User", foreign_keys=[treasurer_id])

# Outstanding cash with a distributor is NOT a stored column - it's computed:
#   sum(Student.amount where distributor_id=X, payment_mode=CASH, payment_status=VERIFIED)
#   minus sum(CashHandover.amount where distributor_id=X)
# Computing it live avoids the value ever drifting out of sync with reality.


# ---------------------------------------------------------------------------
# Finance - expenses and budget allocation (treasurer-managed)
# ---------------------------------------------------------------------------
class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    description = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False, index=True)  # e.g. "Food", "Decor", "DJ"
    fund_type = Column(Enum(FundType), nullable=False)
    amount = Column(Float, nullable=False)
    spent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receipt_image = Column(Text, nullable=True)  # base64 or file path, optional

    recorded_by = relationship("User")


class BudgetAllocation(Base):
    __tablename__ = "budget_allocations"

    id = Column(Integer, primary_key=True)
    category = Column(String(64), nullable=False) # Removed unique=True because a category can have CASH and UPI allocations
    fund_type = Column(Enum(FundType), nullable=False)
    allocated_amount = Column(Float, nullable=False)
    set_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    set_by = relationship("User")

# Derived, per category:
#   spent      = sum(Expense.amount where category=X)
#   allocated  = BudgetAllocation.allocated_amount for X
#   unused     = allocated - spent   (can go negative -> over budget, worth flagging)


# ---------------------------------------------------------------------------
# Audit log - append-only, hash-chained for tamper evidence.
# See the chat explanation for why this lives in the SAME database rather
# than a separate one, and how the hash chain makes tampering detectable.
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)  # sequential - order matters for the hash chain
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # null for system actions
    action = Column(String(64), nullable=False, index=True)
    # e.g. "sale_created", "payment_verified", "payment_rejected",
    #      "cash_handover", "expense_added", "student_edited",
    #      "distributor_created", "distributor_disabled", "gate_checkin"

    table_name = Column(String(64), nullable=False)
    record_id = Column(Integer, nullable=False)
    old_value = Column(JSON, nullable=True)   # snapshot before change (null on create)
    new_value = Column(JSON, nullable=True)   # snapshot after change (null on delete)

    prev_hash = Column(String(64), nullable=False)  # hash of the previous row in the chain
    entry_hash = Column(String(64), nullable=False, unique=True)  # hash of THIS row's content + prev_hash

    user = relationship("User")

# NOTE: this table gets INSERT-only permissions at the DB level (see chat) -
# no UPDATE, no DELETE, enforced by database user grants, not just app code.
