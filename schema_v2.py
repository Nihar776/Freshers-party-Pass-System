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


class HandoverRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


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


class DiscountType(str, enum.Enum):
    PERCENTAGE = "percentage"
    FLAT = "flat"
    FIXED = "fixed"


class PassType(str, enum.Enum):
    FULL = "full"
    NO_FOOD = "no_food"


class FoodPreference(str, enum.Enum):
    VEG = "veg"
    JAIN = "jain"


class PaymentStatus(str, enum.Enum):
    NOT_PURCHASED = "not_purchased"        # roster row, no sale yet
    RESERVED = "reserved"                  # online portal: pending OTP/payment
    PENDING_VERIFICATION = "pending_verification"  # UPI sale, awaiting treasurer (PENDING_APPROVAL)
    VERIFIED = "verified"                  # cash: instant. UPI: after treasurer approval
    REJECTED = "rejected"                  # treasurer rejected - SAP unlocks for resale
    EXPIRED = "expired"                    # online portal: reservation hold timed out


class DiscountRuleType(str, enum.Enum):
    EARLY_BIRD = "EARLY_BIRD"
    FLASH_SALE = "FLASH_SALE"
    GROUP = "GROUP"
    GENERAL = "GENERAL"
    CODE = "CODE"


class PricingEffect(str, enum.Enum):
    FIXED = "FIXED"
    FLAT_OFF = "FLAT_OFF"
    PERCENT_OFF = "PERCENT_OFF"


class ConditionType(str, enum.Enum):
    AFTER_N = "AFTER_N"
    BEFORE_N = "BEFORE_N"
    BETWEEN_N_M = "BETWEEN_N_M"
    AFTER_T = "AFTER_T"
    BEFORE_T = "BEFORE_T"
    BETWEEN_T = "BETWEEN_T"
    DAILY_SLOT = "DAILY_SLOT"
    AFTER_RULE_USED = "AFTER_RULE_USED"
    AFTER_RULE_EXHAUSTED = "AFTER_RULE_EXHAUSTED"


class Combinator(str, enum.Enum):
    AND = "AND"
    OR = "OR"


class DiscountRule(Base):
    __tablename__ = "discount_rules"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    type = Column(Enum(DiscountRuleType), nullable=False)
    is_enabled = Column(Boolean, default=False, nullable=False)
    usage_cap = Column(Integer, nullable=True)
    
    group_size = Column(Integer, nullable=True)
    group_total_price = Column(Float, nullable=True)
    per_person_price = Column(Float, nullable=True)
    
    priority = Column(Integer, default=0, nullable=False)
    pricing_effect = Column(Enum(PricingEffect), nullable=False)
    discount_value = Column(Float, nullable=True) # Could be flat off or percent off. For fixed price, we use per_person_price/group_total_price or discount_value as fixed
    auto_applied = Column(Boolean, default=True, nullable=False)
    condition_combinator = Column(Enum(Combinator), default=Combinator.AND, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ActivationCondition(Base):
    __tablename__ = "activation_conditions"

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("discount_rules.id"), nullable=False)
    condition_type = Column(Enum(ConditionType), nullable=False)
    
    val_n = Column(Integer, nullable=True)
    val_m = Column(Integer, nullable=True)
    time_t1 = Column(DateTime, nullable=True)
    time_t2 = Column(DateTime, nullable=True)
    time_slot_start = Column(String(5), nullable=True) # HH:MM
    time_slot_end = Column(String(5), nullable=True)   # HH:MM
    target_rule_id = Column(Integer, ForeignKey("discount_rules.id"), nullable=True)
    
    rule = relationship("DiscountRule", foreign_keys=[rule_id], backref="conditions")
    target_rule = relationship("DiscountRule", foreign_keys=[target_rule_id])


class UpiQrCode(Base):
    __tablename__ = "upi_qr_codes"

    id = Column(Integer, primary_key=True)
    label = Column(String(120), nullable=False)
    upi_id = Column(String(120), nullable=False)
    payee_name = Column(String(120), nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SaleChannel(str, enum.Enum):
    DISTRIBUTOR = "distributor"
    ONLINE = "online"


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True)
    pass_uuid = Column(String(32), unique=True, index=True, default=_uuid, nullable=False)

    # --- Roster data (pre-loaded, read-only to distributors) ---
    sap_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(120), nullable=False)
    branch = Column(String(64), nullable=False, index=True)
    year = Column(String(20), nullable=True, index=True)
    gender = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)  # can be filled at sale time if roster lacks it
    phone = Column(String(20), nullable=True)   # added for online portal if it wasn't there

    # --- Sale data (filled by distributor at point of sale) ---
    pass_type = Column(Enum(PassType), default=PassType.FULL, nullable=False)
    food_preference = Column(String(50), default="veg", nullable=True) # changed to String to support dynamic foods
    payment_mode = Column(Enum(PaymentMode), nullable=True)
    amount = Column(Float, nullable=True)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.NOT_PURCHASED,
                             nullable=False, index=True)
    sale_channel = Column(Enum(SaleChannel), nullable=True) # DISTRIBUTOR or ONLINE

    distributor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sold_at = Column(DateTime, nullable=True)

    # --- Group Sale data ---
    group_id = Column(String(32), nullable=True, index=True)
    is_group_payer = Column(Boolean, default=False, nullable=False)
    discount_code_id = Column(Integer, ForeignKey("discount_codes.id"), nullable=True)

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
    
    # --- Food check-in ---
    food_received = Column(Boolean, default=False, nullable=False, index=True)
    food_received_at = Column(DateTime, nullable=True)
    food_scanned_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)  # roster import time
    
    # --- Transient OTP Session (Only active session fields) ---
    otp_hash = Column(String(255), nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)
    otp_attempts = Column(Integer, default=0, nullable=False)
    otp_last_sent_at = Column(DateTime, nullable=True)

    distributor = relationship("User", foreign_keys=[distributor_id])
    verified_by = relationship("User", foreign_keys=[verified_by_id])
    scanned_by = relationship("User", foreign_keys=[scanned_by_id])
    food_scanned_by = relationship("User", foreign_keys=[food_scanned_by_id])
    discount_code = relationship("DiscountCode", foreign_keys=[discount_code_id])

class OnlineOrder(Base):
    __tablename__ = "online_orders"

    id = Column(Integer, primary_key=True)
    order_reference = Column(String(32), unique=True, index=True, default=_uuid, nullable=False)
    leader_sap_id = Column(String(64), ForeignKey("students.sap_id"), nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.RESERVED, nullable=False)
    
    locked_total_price = Column(Float, nullable=False)
    applied_rule_id = Column(Integer, ForeignKey("discount_rules.id"), nullable=True)
    discount_code_id = Column(Integer, ForeignKey("discount_codes.id"), nullable=True)
    upi_qr_shown_id = Column(Integer, ForeignKey("upi_qr_codes.id"), nullable=True)
    
    utr_number = Column(String(32), nullable=True)
    payment_screenshot = Column(Text, nullable=True)
    screenshot_phash = Column(String(64), nullable=True)
    
    rejection_reason = Column(String(255), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reservation_expires_at = Column(DateTime, nullable=True)
    
    leader = relationship("Student", foreign_keys=[leader_sap_id])
    applied_rule = relationship("DiscountRule", foreign_keys=[applied_rule_id])
    discount_code = relationship("DiscountCode", foreign_keys=[discount_code_id])
    upi_qr_shown = relationship("UpiQrCode", foreign_keys=[upi_qr_shown_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    members = relationship("OrderMember", back_populates="order", cascade="all, delete-orphan")


class OrderMember(Base):
    __tablename__ = "order_members"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("online_orders.id"), nullable=False)
    sap_id = Column(String(64), ForeignKey("students.sap_id"), nullable=False)
    food_preference = Column(String(50), nullable=True)
    locked_price = Column(Float, nullable=False)
    
    order = relationship("OnlineOrder", back_populates="members")
    student = relationship("Student", foreign_keys=[sap_id])


# ---------------------------------------------------------------------------
# Discount Codes
# ---------------------------------------------------------------------------
class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, index=True, nullable=False)
    discount_type = Column(Enum(DiscountType), nullable=False)
    discount_value = Column(Float, nullable=False)
    max_uses = Column(Integer, nullable=True)
    times_used = Column(Integer, default=0, nullable=False)
    required_group_size = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    created_by = relationship("User")


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

class CashHandoverRequest(Base):
    __tablename__ = "cash_handover_requests"

    id = Column(Integer, primary_key=True)
    distributor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(Enum(HandoverRequestStatus), default=HandoverRequestStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    distributor = relationship("User", foreign_keys=[distributor_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])


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
