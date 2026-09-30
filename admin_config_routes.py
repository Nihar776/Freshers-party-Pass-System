from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from schema_v2 import User, UserRole, DiscountRule, DiscountRuleType, PricingEffect, Combinator, ConditionType, ActivationCondition, UpiQrCode
from session_auth import require_role
from settings_manager import get_settings, save_settings

router = APIRouter(prefix="/admin", tags=["admin-rules"])

ADMIN_ONLY = (UserRole.ADMIN,)

# ---------------------------------------------------------------------------
# Discount Rules
# ---------------------------------------------------------------------------

class ConditionCreate(BaseModel):
    condition_type: ConditionType
    threshold: Optional[int] = None
    threshold_max: Optional[int] = None
    threshold_time: Optional[str] = None
    threshold_time_max: Optional[str] = None
    dependent_rule_id: Optional[int] = None

class RuleCreate(BaseModel):
    name: str
    type: DiscountRuleType
    is_enabled: bool = True
    usage_cap: Optional[int] = None
    group_size: Optional[int] = None
    group_total_price: Optional[float] = None
    per_person_price: Optional[float] = None
    priority: int = 1
    pricing_effect: PricingEffect
    discount_value: float
    auto_applied: bool = True
    condition_combinator: Combinator = Combinator.AND
    conditions: List[ConditionCreate] = []

@router.get("/rules")
def get_rules(db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    rules = db.query(DiscountRule).order_by(DiscountRule.priority.desc()).all()
    result = []
    for r in rules:
        result.append({
            "id": r.id,
            "name": r.name,
            "type": r.type.value,
            "is_enabled": r.is_enabled,
            "usage_cap": r.usage_cap,
            "group_size": r.group_size,
            "group_total_price": r.group_total_price,
            "per_person_price": r.per_person_price,
            "pricing_effect": r.pricing_effect.value,
            "discount_value": r.discount_value,
            "priority": r.priority,
            "auto_applied": r.auto_applied,
            "combinator": r.condition_combinator.value,
            "conditions": [{
                "id": c.id,
                "type": c.condition_type.value,
                "threshold": c.val_n,
                "threshold_max": c.val_m,
                "threshold_time": c.time_t1.isoformat() if c.time_t1 else None,
                "threshold_time_max": c.time_t2.isoformat() if c.time_t2 else None
            } for c in r.conditions]
        })
    return result

@router.post("/rules")
def create_rule(payload: RuleCreate, db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    rule = DiscountRule(
        name=payload.name,
        type=payload.type,
        is_enabled=payload.is_enabled,
        usage_cap=payload.usage_cap,
        group_size=payload.group_size,
        group_total_price=payload.group_total_price,
        per_person_price=payload.per_person_price,
        priority=payload.priority,
        pricing_effect=payload.pricing_effect,
        discount_value=payload.discount_value,
        auto_applied=payload.auto_applied,
        condition_combinator=payload.condition_combinator
    )
    db.add(rule)
    db.flush()
    
    from datetime import datetime
    for c in payload.conditions:
        tt = datetime.fromisoformat(c.threshold_time.replace("Z", "+00:00")) if c.threshold_time else None
        tt_max = datetime.fromisoformat(c.threshold_time_max.replace("Z", "+00:00")) if c.threshold_time_max else None
        cond = ActivationCondition(
            rule_id=rule.id,
            condition_type=c.condition_type,
            val_n=c.threshold,
            val_m=c.threshold_max,
            time_t1=tt,
            time_t2=tt_max,
            target_rule_id=c.dependent_rule_id
        )
        db.add(cond)
        
    # Automatically generate DiscountCode if not GROUP
    import re
    if rule.type.value != "GROUP":
        base_code = re.sub(r'[^A-Z0-9]', '', rule.name.upper())
        if not base_code:
            base_code = f"RULE{rule.id}"
            
        from schema_v2 import DiscountCode, DiscountType
        existing = db.query(DiscountCode).filter(DiscountCode.code == base_code).first()
        suffix = 1
        final_code = base_code
        while existing:
            final_code = f"{base_code}{suffix}"
            existing = db.query(DiscountCode).filter(DiscountCode.code == final_code).first()
            suffix += 1
            
        dtype = DiscountType.FLAT if rule.pricing_effect.value == "FLAT_OFF" else DiscountType.PERCENTAGE
        if rule.pricing_effect.value == "FIXED":
            dtype = DiscountType.FIXED
            
        dc = DiscountCode(
            code=final_code,
            discount_type=dtype,
            discount_value=rule.discount_value if rule.pricing_effect.value != "FIXED" else rule.per_person_price,
            max_uses=rule.usage_cap,
            required_group_size=rule.group_size,
            is_active=rule.is_enabled,
            created_by_id=admin.id
        )
        db.add(dc)

    db.commit()
    return {"message": "Rule created", "id": rule.id}

@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleCreate, db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    rule = db.query(DiscountRule).filter(DiscountRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
        
    rule.name = payload.name
    rule.type = payload.type
    rule.is_enabled = payload.is_enabled
    rule.usage_cap = payload.usage_cap
    rule.group_size = payload.group_size
    rule.group_total_price = payload.group_total_price
    rule.per_person_price = payload.per_person_price
    rule.priority = payload.priority
    rule.pricing_effect = payload.pricing_effect
    rule.discount_value = payload.discount_value
    rule.auto_applied = payload.auto_applied
    rule.condition_combinator = payload.condition_combinator
    
    db.query(ActivationCondition).filter(ActivationCondition.rule_id == rule.id).delete()
    
    from datetime import datetime
    for c in payload.conditions:
        tt = datetime.fromisoformat(c.threshold_time.replace("Z", "+00:00")) if c.threshold_time else None
        tt_max = datetime.fromisoformat(c.threshold_time_max.replace("Z", "+00:00")) if c.threshold_time_max else None
        cond = ActivationCondition(
            rule_id=rule.id,
            condition_type=c.condition_type,
            val_n=c.threshold,
            val_m=c.threshold_max,
            time_t1=tt,
            time_t2=tt_max,
            target_rule_id=c.dependent_rule_id
        )
        db.add(cond)
        
    db.commit()
    return {"message": "Rule updated"}

from sqlalchemy.exc import IntegrityError

@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    rule = db.query(DiscountRule).filter(DiscountRule.id == rule_id).first()
    if not rule: raise HTTPException(status_code=404)
    
    # Manually delete conditions since DB cascade isn't fully set up for this relationship
    db.query(ActivationCondition).filter(ActivationCondition.rule_id == rule.id).delete()
    
    try:
        db.delete(rule)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot delete this rule because it has already been used by student orders. Please toggle it off instead.")
        
    return {"message": "Deleted"}

@router.patch("/rules/{rule_id}/toggle")
def toggle_rule(rule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    rule = db.query(DiscountRule).filter(DiscountRule.id == rule_id).first()
    if not rule: raise HTTPException(status_code=404)
    rule.is_enabled = not rule.is_enabled
    db.commit()
    return {"is_enabled": rule.is_enabled}

# ---------------------------------------------------------------------------
# UPI QRs
# ---------------------------------------------------------------------------
class QrCreate(BaseModel):
    label: str
    upi_id: str
    payee_name: str
    is_active: bool = True

@router.get("/upi-qrs/active")
def get_active_qr(db: Session = Depends(get_db)):
    """Public endpoint — returns the single active UPI QR shown to students during payment."""
    qr = db.query(UpiQrCode).filter(UpiQrCode.is_active == True).first()
    if not qr:
        raise HTTPException(status_code=404, detail="No active UPI QR configured")
    return {"id": qr.id, "label": qr.label, "upi_id": qr.upi_id, "payee_name": qr.payee_name}

@router.get("/upi-qrs")
def get_qrs(db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    qrs = db.query(UpiQrCode).order_by(UpiQrCode.id).all()
    return [{"id": q.id, "label": q.label, "upi_id": q.upi_id, "payee_name": q.payee_name, "is_active": q.is_active} for q in qrs]

@router.post("/upi-qrs")
def create_qr(payload: QrCreate, db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    qr = UpiQrCode(**payload.model_dump())
    db.add(qr)
    db.commit()
    return {"message": "QR added", "id": qr.id}

@router.delete("/upi-qrs/{qr_id}")
def delete_qr(qr_id: int, db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    qr = db.query(UpiQrCode).filter(UpiQrCode.id == qr_id).first()
    if not qr: raise HTTPException(status_code=404)
    db.delete(qr)
    db.commit()
    return {"message": "Deleted"}

@router.patch("/upi-qrs/{qr_id}/toggle")
def toggle_qr(qr_id: int, db: Session = Depends(get_db), admin: User = Depends(require_role(*ADMIN_ONLY))):
    qr = db.query(UpiQrCode).filter(UpiQrCode.id == qr_id).first()
    if not qr: raise HTTPException(status_code=404)
    qr.is_active = not qr.is_active
    db.commit()
    return {"is_active": qr.is_active}

# ---------------------------------------------------------------------------
# Additional Config
# ---------------------------------------------------------------------------
class BasePriceConfig(BaseModel):
    base_price: float
    food_enabled: bool
    hold_time_minutes: Optional[int] = 30

@router.get("/config")
def get_admin_config(admin: User = Depends(require_role(*ADMIN_ONLY))):
    st = get_settings()
    return {
        "base_price": st.get("base_price", 500.0),
        "food_enabled": st.get("food_enabled", False),
        "hold_time_minutes": st.get("hold_time_minutes", 30)
    }

@router.post("/config")
def set_admin_config(payload: BasePriceConfig, admin: User = Depends(require_role(*ADMIN_ONLY))):
    st = get_settings()
    st["base_price"] = payload.base_price
    st["food_enabled"] = payload.food_enabled
    st["hold_time_minutes"] = payload.hold_time_minutes
    save_settings(st)
    return {"message": "Config updated"}
