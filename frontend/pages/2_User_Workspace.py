import streamlit as st
import pandas as pd
import json
from datetime import datetime

import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from api_client import ComplianceAPI

st.set_page_config(page_title="User Workspace | ComplianceLoop", layout="wide")

# Connect to our global mock API
api = ComplianceAPI()

# --- Top 1% Obsidian Theme & CSS ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
.stApp {
    background-color: #050508;
    background-image: radial-gradient(circle at 15% 50%, rgba(212, 175, 55, 0.03), transparent 25%),
                      radial-gradient(circle at 85% 30%, rgba(255, 255, 255, 0.02), transparent 25%);
}
h1, h2, h3 { font-weight: 600 !important; color: #F8FAFC !important; letter-spacing: -0.5px; }

/* Metric Cards */
.metric-card {
    background: linear-gradient(180deg, rgba(20, 22, 28, 0.4) 0%, rgba(12, 14, 18, 0.6) 100%);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-top: 3px solid #D4AF37;
    border-radius: 12px;
    padding: 20px 24px;
    backdrop-filter: blur(20px);
    transition: transform 0.3s ease;
}
.metric-card:hover { transform: translateY(-3px); border-color: rgba(212, 175, 55, 0.3); }
.metric-card .label { font-size: 0.85rem; font-weight: 600; text-transform: uppercase; color: #94A3B8; letter-spacing: 0.05em; }
.metric-card .value { font-size: 2rem; font-weight: 700; color: #F8FAFC; margin-top: 8px; }

/* Bento Info Panels */
.info-panel {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 1rem;
}
.kv-row { display: flex; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.05); padding: 10px 0; }
.kv-row:last-child { border-bottom: none; }
.kv-key { color: #94A3B8; font-weight: 500; font-size: 0.95rem; }
.kv-val { color: #F8FAFC; font-weight: 600; font-size: 0.95rem; }

/* Stylish Badges */
.badge {
    display: inline-block; padding: 4px 10px; border-radius: 20px;
    font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
}
.badge-approved { background: rgba(34, 197, 94, 0.1); color: #4ADE80; border: 1px solid rgba(34, 197, 94, 0.3); }
.badge-rejected { background: rgba(239, 68, 68, 0.1); color: #F87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.badge-review { background: rgba(234, 179, 8, 0.1); color: #FACC15; border: 1px solid rgba(234, 179, 8, 0.3); }

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #D4AF37 0%, #A28220 100%) !important;
    color: #000000 !important; font-weight: 600 !important; border: none !important;
    border-radius: 8px !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(212, 175, 55, 0.3) !important;
}
</style>
""", unsafe_allow_html=True)

def status_badge(status):
    status_upper = str(status).upper()
    cls = "badge-review"
    if status_upper in ["APPROVED", "HEALTHY"]: cls = "badge-approved"
    elif status_upper in ["REJECTED", "DEGRADED", "UNCALIBRATED"]: cls = "badge-rejected"
    return f'<span class="badge {cls}">{status_upper}</span>'

def metric_card(label, value):
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
    </div>
    """, unsafe_allow_html=True)

# ----------------- HEADER -----------------
st.markdown("<h1 style='font-size: 3rem;'>User Workspace</h1>", unsafe_allow_html=True)
st.markdown("<p style='color:#94A3B8; font-size:1.1rem;'>Submit applications, run batch reviews, and track AI compliance evaluations.</p>", unsafe_allow_html=True)
st.divider()

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Dashboard Overview", 
    "⚡ New Compliance Check", 
    "📂 Batch Review", 
    "📜 Request History"
])

# ----------------- TAB 1: Dashboard Overview -----------------
with tab1:
    st.markdown("### Real-time Compliance Activity")
    health_data = api.get("/health")
    stats_data = api.get("/audit/stats")
    
    st.markdown(f"**System Status:** {status_badge(health_data.get('status', 'HEALTHY'))}", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Total Checks", stats_data.get("total_requests", "—"))
    with c2: metric_card("Approved", stats_data.get("approved", "—"))
    with c3: metric_card("Rejected", stats_data.get("rejected", "—"))
    with c4: metric_card("Manual Review", stats_data.get("review", "—"))
    
    st.markdown("<br><h4>Recent Activity Feed</h4>", unsafe_allow_html=True)
    records = api.get("/audit/records")
    if records and isinstance(records, list):
        df = pd.DataFrame(records[:8])
        st.dataframe(df, use_container_width=True, hide_index=True)

# ----------------- TAB 2: New Compliance Check -----------------
with tab2:
    st.markdown("### Process Applicant via AI Evaluator")
    
    with st.form("compliance_check_form", clear_on_submit=False):
        st.markdown("##### Applicant Details")
        c1, c2 = st.columns(2)
        # Pretyped names with custom option
        pretyped_names = ["Rohan", "Sharma", "Virat", "Rahul Sharma", "Custom..."]
        selected_name = c1.selectbox("Choose Name", pretyped_names, index=3)
        if selected_name == "Custom...":
            name = c1.text_input("Full Name", value="")
        else:
            name = selected_name

        pan_number = c2.text_input("PAN Number", value="ABCDE1234F")
        income = c1.number_input("Monthly Income (₹)", value=75000, step=1000)
        existing_emi = c2.number_input("Existing EMI (₹)", value=8000, step=500)

        st.markdown("##### Loan Details")
        c3, c4 = st.columns(2)
        loan_amount = c3.number_input("Loan Amount (₹)", value=500000, step=10000)
        tenure_months = c4.number_input("Tenure (months)", value=36, step=6)

        st.markdown("##### AI Query Instructions")
        query = st.text_area("Compliance Objective", value="Assess loan eligibility and flag any KYC or income discrepancies based on NBFC policy.")

        submitted = st.form_submit_button("▶ Run Compliance Engine")

    if submitted:
        # PAN validation
        if len(pan_number) < 10:
            st.error("Wrong PAN number: PAN must be at least 10 characters.")
        else:
            # Income-based logic
            if income > 100000:
                status = "APPROVED"
                reason = "Income above 1,00,000. Auto-approved."
            elif 50000 < income <= 100000:
                # Always show preview/review for this income range
                status = "REVIEW"
                reason = "Income between 50,000 and 1,00,000. Sent for preview/review."
            else:
                status = "REJECTED"
                reason = "Income below 50,000. Application rejected."

            payload = {
                "name": name, "pan_number": pan_number,
                "income": income, "existing_emi": existing_emi,
                "loan_amount": loan_amount, "tenure_months": tenure_months,
                "query": query,
            }
            with st.spinner("AI Agents interpreting policy and cross-referencing metrics..."):
                result = api.post("/ai/process", data=payload)
                # Override status and reason based on logic
                result["status"] = status
                result["reason"] = reason

            st.markdown("---")
            st.markdown("### ✅ Evaluation Result")
            rid = result.get("request_id", "REQ_AI_UNKNOWN")
            st.markdown(f"**Request ID:** `{rid}` &nbsp;&nbsp; {status_badge(result.get('status', 'APPROVED'))}", unsafe_allow_html=True)
            
            ic1, ic2 = st.columns(2)
            with ic1:
                st.markdown(f"""
                <div class="info-panel">
                    <div class="kv-row"><span class="kv-key">Status</span><span class="kv-val">{result.get('status', '—')}</span></div>
                    <div class="kv-row"><span class="kv-key">Confidence</span><span class="kv-val">{result.get('confidence', '—')}</span></div>
                    <div class="kv-row"><span class="kv-key">Adjustment</span><span class="kv-val">{result.get('confidence_adjustment', '—')}</span></div>
                    <div class="kv-row"><span class="kv-key">Rules Applied</span><span class="kv-val">{', '.join(result.get('rules_used', []))}</span></div>
                </div>
                """, unsafe_allow_html=True)
            with ic2:
                st.markdown(f"""
                <div class="info-panel" style="background: rgba(212, 175, 55, 0.05); border-color: rgba(212, 175, 55, 0.2);">
                    <div class="kv-row" style="flex-direction:column;gap:8px;border:none;">
                        <span class="kv-key" style="color:#D4AF37;">AI Reasoning</span>
                        <span class="kv-val" style="font-weight:400;color:#CBD5E1;line-height:1.6;">{result.get('reason', '—')}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            if result.get("clauses"):
                st.markdown("**Applicable Regulatory Clauses:**", unsafe_allow_html=True)
                for c in result["clauses"]:
                    st.markdown(f"- `<span style='color:#94A3B8;'>{c}</span>`", unsafe_allow_html=True)
                    
        # Save to session history dynamically
        if "user_request_history" not in st.session_state:
            st.session_state.user_request_history = []
        st.session_state.user_request_history.insert(0, {**result, "name": name, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")})
        # Also store activity for Operation Dashboard
        activity_payload = {
            "name": name,
            "pan_number": pan_number,
            "income": income,
            "existing_emi": existing_emi,
            "loan_amount": loan_amount,
            "tenure_months": tenure_months,
            "status": status,
            "reason": reason,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        api.post("/customer-activity", data=activity_payload)

# ----------------- TAB 3: Batch Review -----------------
with tab3:
    st.markdown("### Bulk Submission Pipeline")
    
    st.markdown("<p style='color:#94A3B8;'>Paste a JSON array of applications to process them simultaneously using the API.</p>", unsafe_allow_html=True)
    raw = st.text_area("JSON Array", height=200, value='[\n  {"name": "Priya Mehta", "pan_number": "FGHIJ5678K", "income": 60000, "loan_amount": 300000, "tenure_months": 24, "existing_emi": 5000}\n]')
    
    if st.button("▶ Execute Batch Pipeline"):
        try:
            payload = json.loads(raw)
            with st.spinner(f"Processing {len(payload)} applications via batch API..."):
                results = api.post("/ai/process/batch", data=payload)
            if results and isinstance(results, list):
                st.success(f"Batch execution complete — {len(results)} outputs generated.")
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
            else:
                st.error("Batch processing returned an unexpected format.")
        except json.JSONDecodeError:
            st.error("Invalid JSON format provided. Please check syntax.")
