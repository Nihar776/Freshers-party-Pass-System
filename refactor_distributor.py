import codecs

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/distributor.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Insert modal HTML before <script>
modal_html = """
    <!-- Friend Verify Modal -->
    <div id="friend-verify-modal" class="hidden"
        style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); z-index:9999; display:flex; align-items:center; justify-content:center; padding:16px;">
        <div class="step-panel" style="width:100%; max-width:400px; box-sizing:border-box;">
            <h3 style="margin:0 0 8px 0; font-size: 20px;">Verify Student</h3>
            <p id="friend-verify-desc" style="font-size:14px; color:var(--text-muted); margin-bottom:16px;">We don't
                have contact info for this student.</p>

            <div id="friend-email-step">
                <div class="form-group" style="margin-bottom:12px;">
                    <label class="form-label">Email Address <span style="color:var(--danger)">*</span></label>
                    <input type="email" id="friendEmailInput" class="form-control" placeholder="student@gmail.com">
                </div>
                <div class="form-group" style="margin-bottom:20px;">
                    <label class="form-label">Phone Number <span style="color:var(--danger)">*</span></label>
                    <input type="tel" id="friendPhoneInput" class="form-control" placeholder="10-digit number">
                </div>
                <div style="display:flex; justify-content:flex-end; gap:8px;">
                    <button class="btn btn-secondary" onclick="closeFriendVerify()">Cancel</button>
                    <button class="btn btn-primary" id="btn-friend-send-otp" onclick="sendFriendOtp()">Send OTP</button>
                </div>
            </div>

            <div id="friend-otp-step" style="display:none;">
                <div class="form-group" style="margin-bottom:20px;">
                    <label class="form-label">Enter 6-digit OTP</label>
                    <input type="text" id="friendOtpInput" class="form-control" placeholder="• • • • • •" maxlength="6">
                </div>
                <div style="display:flex; justify-content:flex-end; gap:8px;">
                    <button class="btn btn-secondary" onclick="closeFriendVerify()">Cancel</button>
                    <button class="btn btn-primary" id="btn-friend-verify-otp" onclick="verifyFriendOtp()">Verify & Add</button>
                </div>
            </div>
        </div>
    </div>
"""
html = html.replace("    <script>", modal_html + "\n    <script>")

# 2. Add config fetch and friend modal logic right after `let appliedPromo = null;`
js_additions = """
        let foodEnabled = false;
        async function fetchConfig() {
            try {
                const r = await fetch('/admin/config');
                const c = await r.json();
                foodEnabled = c.food_enabled;
            } catch (e) { console.error("Error fetching config", e); }
        }

        let pendingFriend = null;
        let pendingFriendEmail = '';
        let pendingFriendPhone = '';

        function openFriendVerify() {
            document.getElementById('friend-verify-desc').innerHTML = `We don't have contact info for <b>${pendingFriend.name}</b>. Please provide it so we can send an OTP.`;
            document.getElementById('friendEmailInput').value = '';
            document.getElementById('friendPhoneInput').value = '';
            document.getElementById('friendOtpInput').value = '';
            document.getElementById('friend-email-step').style.display = 'block';
            document.getElementById('friend-otp-step').style.display = 'none';
            document.getElementById('friend-verify-modal').classList.remove('hidden');
        }

        function closeFriendVerify() {
            pendingFriend = null;
            document.getElementById('friend-verify-modal').classList.add('hidden');
        }

        async function sendFriendOtp() {
            const email = document.getElementById('friendEmailInput').value.trim();
            const phone = document.getElementById('friendPhoneInput').value.trim();
            if (!email || !email.includes('@') || !email.includes('.')) return showToast('Please enter a valid email', 'error');
            if (!phone || phone.length < 10) return showToast('Please enter a valid phone number', 'error');

            const btn = document.getElementById('btn-friend-send-otp');
            btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Sending…';
            try {
                const res = await fetch('/api/student/send-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sap_id: pendingFriend.sap_id, email: email, phone: phone })
                });
                if (!res.ok) {
                    const d = await res.json();
                    showToast(d.detail || 'Could not send OTP', 'error');
                } else {
                    pendingFriendEmail = email;
                    pendingFriendPhone = phone;
                    document.getElementById('friend-email-step').style.display = 'none';
                    document.getElementById('friend-otp-step').style.display = 'block';
                    document.getElementById('friend-verify-desc').innerHTML = `OTP sent to <b>${email}</b>.`;
                    showToast('OTP sent successfully');
                }
            } catch (e) { showToast('Network error', 'error'); }
            btn.disabled = false; btn.textContent = 'Send OTP';
        }

        async function verifyFriendOtp() {
            const otp = document.getElementById('friendOtpInput').value.trim();
            if (otp.length !== 6) return showToast('Enter 6-digit OTP', 'warning');

            const btn = document.getElementById('btn-friend-verify-otp');
            btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Verifying…';
            try {
                const res = await fetch('/api/student/verify-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sap_id: pendingFriend.sap_id, otp: otp })
                });
                if (!res.ok) {
                    const d = await res.json();
                    showToast(d.detail || 'Invalid OTP', 'error');
                } else {
                    showToast('Student verified!');
                    pendingFriend.email = pendingFriendEmail;
                    pendingFriend.phone = pendingFriendPhone;
                    finalizeAddToCart(pendingFriend);
                    closeFriendVerify();
                }
            } catch (e) { showToast('Network error', 'error'); }
            btn.disabled = false; btn.textContent = 'Verify & Add';
        }

        function setStudentPhone(sap_id, val) {
            const item = cart.find(c => c.sap_id === sap_id);
            if (item) item.phone = val;
        }
"""
html = html.replace("        let appliedPromo = null;", "        let appliedPromo = null;\n" + js_additions)

# 3. Replace addToCart
add_to_cart_old = """
        function addToCart(student) {
            if (cart.length === 0) {
                student.is_payer = true; // First person defaults to payer
            } else {
                student.is_payer = false;
            }
            student.food_pref = 'veg'; // Default
            cart.push(student);
            document.getElementById('search').value = '';
            document.getElementById('results').innerHTML = '';
            updateCartUI();
        }"""
add_to_cart_new = """
        function addToCart(student) {
            if (!student.email) {
                pendingFriend = student;
                openFriendVerify();
                return;
            }
            finalizeAddToCart(student);
        }

        function finalizeAddToCart(student) {
            if (cart.length === 0) {
                student.is_payer = true; // First person defaults to payer
            } else {
                student.is_payer = false;
            }
            student.food_pref = 'veg'; // Default
            cart.push(student);
            document.getElementById('search').value = '';
            document.getElementById('results').innerHTML = '';
            updateCartUI();
        }"""
html = html.replace(add_to_cart_old, add_to_cart_new)

# 4. Modify init
init_old = """
        async function init() {
            const res = await fetch('/me');
            if (!res.ok) return window.location.href = '/login-page';
            const me = await res.json();
            if (me.role !== 'distributor' && me.role !== 'admin') return window.location.href = '/login-page';
            document.getElementById('user-name').textContent = me.full_name;
            loadStats();
        }"""
init_new = """
        async function init() {
            const res = await fetch('/me');
            if (!res.ok) return window.location.href = '/login-page';
            const me = await res.json();
            if (me.role !== 'distributor' && me.role !== 'admin') return window.location.href = '/login-page';
            document.getElementById('user-name').textContent = me.full_name;
            await fetchConfig();
            loadStats();
        }"""
html = html.replace(init_old, init_new)

# 5. Modify Checkout (building formData)
checkout_old = """
            if (cart.length === 1) {
                // Single sale
                formData.append('sap_id', cart[0].sap_id);
                formData.append('food_preference', cart[0].food_pref);
                formData.append('payment_mode', mode);
            } else {
                // Group sale
                cart.forEach(c => {
                    formData.append('sap_ids', c.sap_id);
                    formData.append('food_preferences', c.food_pref);
                });
                formData.append('payer_sap_id', payer.sap_id);
                formData.append('payment_mode', mode);
            }

            const emailInput = document.getElementById('payer-email').value.trim();
            if (emailInput) formData.append('email', emailInput);
            const phoneInput = document.getElementById('payer-phone').value.trim();
            if (phoneInput) formData.append('phone', phoneInput);"""

checkout_new = """
            for (let c of cart) {
                if (!c.phone || c.phone.length < 10) {
                    showToast(`Phone number is required for ${c.name}.`, 'warning');
                    btn.disabled = false; btn.textContent = 'Confirm Sale';
                    return;
                }
            }

            if (cart.length === 1) {
                // Single sale
                formData.append('sap_id', cart[0].sap_id);
                if(foodEnabled) formData.append('food_preference', cart[0].food_pref);
                formData.append('payment_mode', mode);
                formData.append('phone', cart[0].phone); // overrides payer-phone
            } else {
                // Group sale
                cart.forEach(c => {
                    formData.append('sap_ids', c.sap_id);
                    if(foodEnabled) formData.append('food_preferences', c.food_pref);
                    formData.append('phones', c.phone);
                });
                formData.append('payer_sap_id', payer.sap_id);
                formData.append('payment_mode', mode);
            }

            const emailInput = document.getElementById('payer-email').value.trim();
            if (emailInput) formData.append('email', emailInput);"""
            
html = html.replace(checkout_old, checkout_new)

with open('d:/_Programming/pass-distribution-system/Freshers-party-Pass-System/templates/distributor.html', 'w', encoding='utf-8') as f:
    f.write(html)
