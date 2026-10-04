import os
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db.schema_v2 import DiscountRule, DiscountRuleType, PricingEffect, Combinator, ActivationCondition, ConditionType
from core.settings_manager import get_settings, save_settings

def seed_online_sales():
    db: Session = SessionLocal()
    
    # 1. Early Bird
    early_bird = db.query(DiscountRule).filter_by(name="Early Bird").first()
    if not early_bird:
        early_bird = DiscountRule(
            name="Early Bird",
            type=DiscountRuleType.EARLY_BIRD,
            is_enabled=True,
            usage_cap=50,
            priority=100,
            pricing_effect=PricingEffect.FIXED,
            discount_value=300, # Assuming 300 is the early bird price. We'll set it here.
            auto_applied=True,
            condition_combinator=Combinator.AND
        )
        db.add(early_bird)
        db.commit()
        db.refresh(early_bird)
        print("Created Early Bird Rule")
    
    # 2. Group Discount
    group_discount = db.query(DiscountRule).filter_by(name="Group Discount").first()
    if not group_discount:
        group_discount = DiscountRule(
            name="Group Discount",
            type=DiscountRuleType.GROUP,
            is_enabled=True,
            group_size=8,
            group_total_price=2200,
            per_person_price=275,
            priority=50,
            pricing_effect=PricingEffect.FIXED,
            auto_applied=True,
            condition_combinator=Combinator.AND
        )
        db.add(group_discount)
        db.commit()
        db.refresh(group_discount)
        
        # Add condition: active after 50 participants have enrolled
        condition = ActivationCondition(
            rule_id=group_discount.id,
            condition_type=ConditionType.AFTER_N,
            val_n=50
        )
        db.add(condition)
        db.commit()
        print("Created Group Discount Rule and Condition")
        
    db.close()
    
    # 3. Settings
    settings = get_settings()
    settings["food_enabled"] = False
    settings["food_types"] = ["Veg", "Jain"]
    settings["food_default"] = "Veg"
    settings["hold_time_minutes"] = 30
    settings["count_distributor_passes"] = True
    save_settings(settings)
    print("Updated settings.json with food and hold time defaults")

if __name__ == "__main__":
    seed_online_sales()
