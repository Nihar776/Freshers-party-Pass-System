import codecs
import re

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/admin.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add Phone input to edit-modal
target_email = """            <div class="form-group">
                <label class="form-label">Email Address</label>
                <input type="email" id="edit-email" class="form-control" placeholder="Student Email">
            </div>"""
replacement_email = """            <div class="form-group">
                <label class="form-label">Email Address</label>
                <input type="email" id="edit-email" class="form-control" placeholder="Student Email">
            </div>
            <div class="form-group">
                <label class="form-label">Phone Number</label>
                <input type="tel" id="edit-phone" class="form-control" placeholder="10-digit number">
            </div>"""
html = html.replace(target_email, replacement_email)

# 2. Update openEditModal definition
target_func = "function openEditModal(id, currentStatus, currentUsed, paymentMode, foodPref, currentEmail) {"
replacement_func = "function openEditModal(id, currentStatus, currentUsed, paymentMode, foodPref, currentEmail, currentPhone) {"
html = html.replace(target_func, replacement_func)

target_assign = "document.getElementById('edit-email').value = currentEmail || '';"
replacement_assign = """document.getElementById('edit-email').value = currentEmail || '';
            document.getElementById('edit-phone').value = currentPhone || '';"""
html = html.replace(target_assign, replacement_assign)

# 3. Update saveStudentEdit function
target_save_email = "const email = document.getElementById('edit-email').value.trim();"
replacement_save_email = """const email = document.getElementById('edit-email').value.trim();
            const phone = document.getElementById('edit-phone').value.trim();"""
html = html.replace(target_save_email, replacement_save_email)

target_append_email = "formData.append('email', email);"
replacement_append_email = """formData.append('email', email);
            if (phone) formData.append('phone', phone);"""
html = html.replace(target_append_email, replacement_append_email)

# 4. Update the openEditModal call in loadStudents
target_call = "onclick=\"openEditModal(${s.id}, '${s.payment_status}', ${s.is_used}, '${s.payment_mode}', '${s.food_preference}', '${s.email || ''}')\">Edit</button>"
replacement_call = "onclick=\"openEditModal(${s.id}, '${s.payment_status}', ${s.is_used}, '${s.payment_mode}', '${s.food_preference}', '${s.email || ''}', '${s.phone || ''}')\">Edit</button>"
html = html.replace(target_call, replacement_call)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/admin.html', 'w', encoding='utf-8') as f:
    f.write(html)
