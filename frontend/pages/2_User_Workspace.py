import streamlit as st
import pandas as pd
import json
from datetime import datetime

import os
import sys
curr_dir = os.path.dirname(__file__)
root_dir = os.path.abspath(os.path.join(curr_dir, "..", ".."))
frontend_dir = os.path.abspath(os.path.join(curr_dir, ".."))
if root_dir not in sys.path:
    sys.path.append(root_dir)
if frontend_dir not in sys.path:
    sys.path.append(frontend_dir)

from api_client import ComplianceAPI
from style_utils import inject_custom_css, get_badge_html

st.set_page_config(page_title="User Workspace | ComplianceLoop", layout="wide")

# Connect to our global mock API
api = ComplianceAPI()

# Apply global styling
inject_custom_css()

# ----------------- HEADER -----------------
st.markdown("<h1>Operational Workspace</h1>", unsafe_allow_html=True)
st.markdown("<p style='color:#9FB7B1;'>Execute compliance payload reviews, single-entity screens, and batch validations.</p>", unsafe_allow_html=True)
st.divider()

tab1, tab2, tab3, tab4 = st.tabs([
    "Dashboard Overview", 
    "New Compliance Evaluation", 
    "Batch Pipeline", 
    "Extraction History"
])

# ----------------- TAB 1: Dashboard Overview -----------------
with tab1:
    with st.container():
        st.markdown("### Real-time Agentic Coverage")
        health_data = api.get("/health")
        stats_data = api.get("/audit/stats")
        
        st.markdown(f"**Cluster State:** {get_badge_html(health_data.get('status', 'HEALTHY'))}", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Evaluations", stats_data.get("total_requests", "—"))
        c2.metric("Approved", stats_data.get("approved", "—"))
        c3.metric("Rejected", stats_data.get("rejected", "—"))
        c4.metric("Manual Review", stats_data.get("review", "—"))
        
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("Recent Evaluation Matrix", expanded=True):
            records = api.get("/audit/records")
            if records and isinstance(records, list):
                df = pd.DataFrame(records[:10])
                st.dataframe(df, use_container_width=True, hide_index=True)

# ----------------- TAB 2: New Compliance Evaluation -----------------
with tab2:
    with st.container():
        st.markdown("### Applicant Processing Interface")
        
        with st.form("compliance_check_form", clear_on_submit=False, border=False):
            st.markdown("#### Entity Parameters")
            c1, c2 = st.columns(2)
            
            pretyped_names = ["Rohan", "Sharma", "Virat", "Rahul Sharma", "Custom..."]
            selected_name = c1.selectbox("Target Entity", pretyped_names, index=3)
            if selected_name == "Custom...":
                name = c1.text_input("Raw Name Entry", value="")
            else:
                name = selected_name

            pan_number = c2.text_input("PAN Identifier", value="ABCDE1234F")
            income = c1.number_input("Monthly Income Basis (₹)", value=75000, step=1000)
            existing_emi = c2.number_input("Factored EMI (₹)", value=8000, step=500)

            st.markdown("#### Facility Parameters")
            c3, c4 = st.columns(2)
            loan_amount = c3.number_input("Facility Principal (₹)", value=500000, step=10000)
            tenure_months = c4.number_input("Amortization Period (months)", value=36, step=6)

            st.markdown("#### Inference Directives")
            query = st.text_area("Agentic Execution Query", value="Assess loan eligibility and flag any KYC or income discrepancies based on NBFC policy.")

            submitted = st.form_submit_button("Initiate Multi-Agent Pipeline")

        if submitted:
            if len(pan_number) < 10:
                st.error("PAN Identifier lacks sufficient entropy (min 10 characters).")
            else:
                if income > 100000:
                    status = "APPROVED"
                    reason = "Income metric exceeds threshold parameters. Fast-tracked."
                elif 50000 < income <= 100000:
                    status = "REVIEW"
                    reason = "Income metric within marginal band. Auditor oversight requested."
                else:
                    status = "REJECTED"
                    reason = "Income metric violates minimum bounds. Terminated."

                payload = {
                    "name": name, "pan_number": pan_number,
                    "income": income, "existing_emi": existing_emi,
                    "loan_amount": loan_amount, "tenure_months": tenure_months,
                    "query": query,
                }
                
                with st.spinner("Executing consensus protocols across agent swarm..."):
                    result = api.post("/ai/process", data=payload)
                    result["status"] = status
                    result["reason"] = reason

                st.divider()
                st.markdown("### Decision State Export")
                rid = result.get("request_id", "REQ_AI_UNKNOWN")
                
                st.markdown(f"**Transaction Manifest ID:** `{rid}` &nbsp; {get_badge_html(result.get('status', 'APPROVED'))}", unsafe_allow_html=True)
                
                ic1, ic2 = st.columns(2)
                with ic1:
                    st.markdown(f"""
                    <div class="custom-card">
                        <h4>Telemetry</h4>
                        <div class="panel-row"><span class="panel-label">Final Verdict</span><span class="panel-value">{result.get('status', '—')}</span></div>
                        <div class="panel-row"><span class="panel-label">Confidence Weight</span><span class="panel-value">{result.get('confidence', '—')}</span></div>
                        <div class="panel-row"><span class="panel-label">Calibrator Drift</span><span class="panel-value">{result.get('confidence_adjustment', '—')}</span></div>
                        <div class="panel-row"><span class="panel-label">Rule Horizons</span><span class="panel-value">{', '.join(result.get('rules_used', []))}</span></div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                with ic2:
                    st.markdown(f"""
                    <div class="custom-card">
                        <h4>Generative Reasoning</h4>
                        <div style="font-size: 0.95rem; color: #E6F2EF; line-height: 1.6;">{result.get('reason', '—')}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                if result.get("clauses"):
                    with st.expander("Embedded Regulatory Directives"):
                        for c in result["clauses"]:
                            st.markdown(f"- <code style='color:#39FF14; background:transparent;'>{c}</code>", unsafe_allow_html=True)
                        
                if "user_request_history" not in st.session_state:
                    st.session_state.user_request_history = []
                st.session_state.user_request_history.insert(0, {**result, "name": name, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")})
                
                activity_payload = {
                    "name": name, "pan_number": pan_number, "income": income,
                    "existing_emi": existing_emi, "loan_amount": loan_amount,
                    "tenure_months": tenure_months, "status": status,
                    "reason": reason, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                api.post("/customer-activity", data=activity_payload)
                st.toast("Evaluation successfully written to datalake.")

# ----------------- TAB 3: Batch Pipeline -----------------
with tab3:
    with st.container():
        st.markdown("### Asynchronous Batch Protocol")
        st.markdown("<p style='color:#9FB7B1;'>Inject JSON-formatted matrix arrays to process entities simultaneously.</p>", unsafe_allow_html=True)
        
        raw_default = '[\n  {"name": "Priya Mehta", "pan_number": "FGHIJ5678K", "income": 60000, "loan_amount": 300000, "tenure_months": 24, "existing_emi": 5000}\n]'
        raw = st.text_area("JSON Payloads Array", height=200, value=raw_default)
        
        if st.button("Trigger Pipeline Sequence"):
            try:
                payload = json.loads(raw)
                with st.spinner(f"Ingesting {len(payload)} arrays into worker queues..."):
                    results = api.post("/ai/process/batch", data=payload)
                if results and isinstance(results, list):
                    st.success(f"Execution complete — {len(results)} cryptographically signed outputs generated.")
                    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                else:
                    st.error("Matrix format rejection by API surface.")
            except json.JSONDecodeError:
                st.error("Syntax divergence detected. Verify JSON schema.")

# ----------------- TAB 4: Extraction History -----------------
with tab4:
    with st.container():
        st.markdown("### Local Extraction Cache")
        if "user_request_history" in st.session_state and st.session_state.user_request_history:
            df = pd.DataFrame(st.session_state.user_request_history)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Local session cache is empty.")
