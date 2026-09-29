import threading
from fastapi.testclient import TestClient
from main import app
from database import SessionLocal, engine
from schema_v2 import Student, DiscountRule, DiscountRuleType, PricingEffect, Combinator, UpiQrCode, ActivationCondition, OnlineOrder, OrderMember
from settings_manager import save_settings
import secrets
import hashlib
import logging

engine.echo = True

client = TestClient(app)

def setup_db():
    # Clean DB and insert dummy data
    db = SessionLocal()
    
    # Enable portal, hold time
    save_settings({"portal_enabled": True, "hold_time_minutes": 30, "base_price": 500, "count_distributor_passes": True})
    
    # Setup QR
    qr = db.query(UpiQrCode).first()
    if not qr:
        qr = UpiQrCode(label="Test", upi_id="test@upi", payee_name="Test", is_active=True)
        db.add(qr)
        
    # Setup Early Bird Rule - cap of 1
    db.query(OrderMember).delete()
    db.query(OnlineOrder).delete()
    db.query(ActivationCondition).delete()
    db.query(DiscountRule).delete()
    rule = DiscountRule(
        name="Last Slot Test",
        type=DiscountRuleType.EARLY_BIRD,
        is_enabled=True,
        usage_cap=1,
        priority=100,
        pricing_effect=PricingEffect.FIXED,
        discount_value=300,
        auto_applied=True
    )
    db.add(rule)
    
    # 2 Students
    db.query(Student).delete()
    s1 = Student(sap_id="S1", name="S1", branch="CS", pass_uuid="uuid1", otp_hash="test", otp_expires_at="2099-01-01 00:00:00")
    s2 = Student(sap_id="S2", name="S2", branch="CS", pass_uuid="uuid2", otp_hash="test", otp_expires_at="2099-01-01 00:00:00")
    db.add_all([s1, s2])
    db.commit()
    db.close()

def test_concurrency_last_slot():
    setup_db()
    
    results = []
    
    def reserve_task(sap_id, pass_uuid):
        res = client.post("/api/student/reserve", json={
            "sap_id": sap_id,
            "pass_uuid": pass_uuid
        })
        results.append(res.json())

    t1 = threading.Thread(target=reserve_task, args=("S1", "uuid1"))
    t2 = threading.Thread(target=reserve_task, args=("S2", "uuid2"))
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    print("RESULTS:", results)
    
    prices = [r.get("locked_price") for r in results if "locked_price" in r]
    
    assert len(prices) == 2, "Both should succeed in making a reservation"
    assert 300.0 in prices, "One should get the early bird price"
    assert 500.0 in prices, "The other should get the base price"
    assert prices.count(300.0) == 1, "Exactly one winner for the last slot"

if __name__ == "__main__":
    test_concurrency_last_slot()
    print("Concurrency test passed!")
