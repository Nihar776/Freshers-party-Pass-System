import codecs
import re

# 1. Update admin_routes.py with DELETE /discount-codes/{code_id}
with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/admin_routes.py', 'r', encoding='utf-8') as f:
    admin_routes_code = f.read()

delete_dc_endpoint = """@router.patch("/discount-codes/{code_id}/toggle")
def toggle_discount_code(
    code_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    dc = db.query(DiscountCode).filter(DiscountCode.id == code_id).first()
    if not dc:
        raise HTTPException(status_code=404, detail="Discount code not found")
    
    dc.is_active = not dc.is_active
    db.commit()
    return {"message": "Toggled", "is_active": dc.is_active}

@router.delete("/discount-codes/{code_id}")
def delete_discount_code(
    code_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    from sqlalchemy.exc import IntegrityError
    dc = db.query(DiscountCode).filter(DiscountCode.id == code_id).first()
    if not dc:
        raise HTTPException(status_code=404, detail="Discount code not found")
    
    try:
        db.delete(dc)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot delete this discount code because it has already been used.")
    return {"message": "Discount code deleted"}
"""

admin_routes_code = admin_routes_code.replace("""@router.patch("/discount-codes/{code_id}/toggle")
def toggle_discount_code(
    code_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*ADMIN_ONLY)),
):
    dc = db.query(DiscountCode).filter(DiscountCode.id == code_id).first()
    if not dc:
        raise HTTPException(status_code=404, detail="Discount code not found")
    
    dc.is_active = not dc.is_active
    db.commit()
    return {"message": "Toggled", "is_active": dc.is_active}""", delete_dc_endpoint)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/admin_routes.py', 'w', encoding='utf-8') as f:
    f.write(admin_routes_code)

# 2. Update admin.html with delete button
with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/admin.html', 'r', encoding='utf-8') as f:
    admin_html = f.read()

target_tr = """                        <td>
                            <button class="btn btn-sm ${c.is_active ? 'btn-danger' : 'btn-primary'}" onclick="toggleDiscountCode(${c.id})">
                                ${c.is_active ? 'Deactivate' : 'Activate'}
                            </button>
                        </td>"""
replacement_tr = """                        <td>
                            <button class="btn btn-sm ${c.is_active ? 'btn-danger' : 'btn-primary'}" onclick="toggleDiscountCode(${c.id})">
                                ${c.is_active ? 'Deactivate' : 'Activate'}
                            </button>
                            <button class="btn btn-sm btn-danger" onclick="deleteDiscountCode(${c.id})">Delete</button>
                        </td>"""
admin_html = admin_html.replace(target_tr, replacement_tr)

target_js = """        async function toggleDiscountCode(id) {"""
replacement_js = """        async function deleteDiscountCode(id) {
            if (!confirm('Are you sure you want to delete this discount code?')) return;
            try {
                const res = await fetch(`/admin/discount-codes/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    showToast('Discount code deleted successfully');
                    loadDiscountCodes();
                } else {
                    const data = await res.json();
                    showToast(data.detail || 'Failed to delete discount code', 'error');
                }
            } catch (err) {
                showToast('Network error', 'error');
            }
        }

        async function toggleDiscountCode(id) {"""
admin_html = admin_html.replace(target_js, replacement_js)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(admin_html)

# 3. Update distributor.html with 10-digit validation
with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/distributor.html', 'r', encoding='utf-8') as f:
    dist_html = f.read()

target_dist = """            for (let c of cart) {
                if (!c.phone || c.phone.length < 10) {
                    showToast(`Phone number is required for ${c.name}.`, 'warning');
                    btn.disabled = false; btn.textContent = 'Confirm Sale';
                    return;
                }
            }"""

replacement_dist = """            for (let c of cart) {
                if (!c.phone || !/^\d{10}$/.test(c.phone)) {
                    showToast(`A valid 10-digit phone number is required for ${c.name}.`, 'warning');
                    btn.disabled = false; btn.textContent = 'Confirm Sale';
                    return;
                }
            }"""
dist_html = dist_html.replace(target_dist, replacement_dist)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/distributor.html', 'w', encoding='utf-8') as f:
    f.write(dist_html)
