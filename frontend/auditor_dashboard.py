import streamlit as st
import pandas as pd
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api_client import ComplianceAPI

st.set_page_config(page_title="Auditor Dashboard | ComplianceLoop", page_icon="⚙️", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}

.stApp {
    background-color: #090A0F;
    background-image: radial-gradient(circle at 50% -20%, #1e1e24 0%, #090A0F 60%);
}

.gradient-text-alt {
    background: linear-gradient(135deg, #39FF14 0%, #F3D270 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
}

/* Metric Cards */
[data-testid="stMetric"] {
    background: rgba(18, 20, 29, 0.6) !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
    padding: 1.5rem !important;
    border-radius: 12px !important;
    backdrop-filter: blur(12px) !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2) !important;
}

[data-testid="stMetric"]:hover {
    border-color: rgba(212, 175, 55, 0.4) !important;
    box-shadow: 0 8px 30px rgba(212, 175, 55, 0.15) !important;
    transform: translateY(-4px) !important;
}

[data-testid="stMetricValue"] {
    font-size: 2.5rem !important;
    font-weight: 800 !important;
    color: #FFFFFF !important;
    letter-spacing: -1px;
}

[data-testid="stMetricLabel"] {
    color: #8B949E !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.8rem !important;
}

/* Tabs styling */
[data-testid="stTabs"] button {
    border-bottom: 2px solid transparent !important;
    transition: all 0.3s ease;
    font-weight: 500 !important;
    color: #8B949E !important;
    background: transparent !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    border-bottom: 2px solid #39FF14 !important;
    color: #39FF14 !important;
    font-weight: 700 !important;
}

/* Header Text */
h1, h2, h3, h4, h5, h6 {
    font-weight: 600 !important;
    letter-spacing: -0.5px !important;
}

hr {
    border-color: rgba(255, 255, 255, 0.05) !important;
}

/* Badges CSS injected into markdown */
div.stMarkdown table {
    border-collapse: collapse;
    width: 100%;
    margin-top: 1rem;
    background: rgba(18, 20, 29, 0.4);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.05);
}
div.stMarkdown th {
    background: rgba(255, 255, 255, 0.03);
    color: #8B949E;
    text-transform: uppercase;
    font-size: 0.8rem;
    letter-spacing: 1px;
    padding: 16px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    font-weight: 600;
}
div.stMarkdown td {
    padding: 16px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    color: #E2E8F0;
    font-weight: 500;
}
div.stMarkdown tr:hover {
    background: rgba(255, 255, 255, 0.02);
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #39FF14 0%, #A28220 100%) !important;
    color: #000000 !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 8px !important;
    transition: all 0.3s ease !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(212, 175, 55, 0.3) !important;
}

/* Inputs */
.stTextInput input, .stTextArea textarea, .stSelectbox select {
    background: rgba(18, 20, 29, 0.8) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    color: #fff !important;
    padding: 10px 14px !important;
    transition: all 0.3s ease !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #39FF14 !important;
    box-shadow: 0 0 0 1px #39FF14 !important;
}
</style>
""", unsafe_allow_html=True)


if not st.session_state.get("auth_status", False):
    st.error("🚨 Access Denied! Please authenticate on the Landing Page using your Auditor API Key.")
    st.stop()

# Initialize API Client
api_key = st.session_state.get("api_key", "")
api = ComplianceAPI(api_key=api_key)

st.markdown("<h1 style='font-size: 3.2rem;'>⚙️ Auditor <span class='gradient-text-alt'>Dashboard</span></h1>", unsafe_allow_html=True)
st.markdown("---")

t1, t2, t3, t4, t5, t6, t7 = st.tabs([
    "Overview", 
    "Audit Explorer", 
    "Overrides", 
    "Rules Management", 
    "Feedback", 
    "Calibration Center", 
    "Operations Panel"
])

def render_badge(status):
    if status == "APPROVED":
        return "<span style='background: rgba(46, 235, 114, 0.1); color: #2eeb72; border: 1px solid rgba(46, 235, 114, 0.2); padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem;'>APPROVED</span>"
    elif status == "REJECTED":
        return "<span style='background: rgba(235, 46, 46, 0.1); color: #eb2e2e; border: 1px solid rgba(235, 46, 46, 0.2); padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem;'>REJECTED</span>"
    elif status in ["REVIEW", "STALE"]:
        return f"<span style='background: rgba(235, 209, 46, 0.1); color: #ebd12e; border: 1px solid rgba(235, 209, 46, 0.2); padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem;'>{status}</span>"
    elif status in ["HEALTHY", "READY"]:
        return "<span style='background: rgba(46, 235, 114, 0.1); color: #2eeb72; border: 1px solid rgba(46, 235, 114, 0.2); padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem;'>HEALTHY</span>"
    else:
        return f"<span style='background: rgba(255, 255, 255, 0.1); color: #ccc; border: 1px solid rgba(255, 255, 255, 0.2); padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem;'>{status}</span>"

with t1:
    st.markdown("### System Health & Topology")
    st.write("")
    with st.spinner("Synchronizing states..."):
        c1, c2, c3, c4, c5 = st.columns(5)
        
        health = api.get("/health")
        c1.metric("API Core", health.get("status", "UNKNOWN"))
        
        ready = api.get("/ready")
        c2.metric("Subsystems", ready.get("status", "UNKNOWN"))
        
        stats = api.get("/audit/stats")
        c3.metric("Scanned Txs", stats.get("total_requests", 0))
        
        verify = api.get("/audit/chain/verify")
        verify_status = "VERIFIED" if verify.get("verified") else "TAMPERED"
        c4.metric("Chain Status", verify_status)
        
        calib = api.get("/calibration/latest")
        c5.metric("Model F1", calib.get("f1_score", 0.0))

    st.markdown("---")
    st.markdown("### Active Rule Horizons")
    rules = api.get("/rules")
    if "error" not in rules:
        html_table = "<table><tr><th>Rule ID</th><th>Threshold Name</th><th>Governance Status</th><th>Activation Weight</th></tr>"
        for r in rules:
            html_table += f"<tr><td><code style='color:#39FF14; background:transparent;'>{r['id']}</code></td><td>{r['name']}</td><td>{render_badge(r['status'])}</td><td>{r['weight']}</td></tr>"
        html_table += "</table>"
        st.markdown(html_table, unsafe_allow_html=True)

with t2:
    st.markdown("### Audit Explorer")
    records = api.get("/audit/records")
    if "error" in records:
        st.error(records["error"])
    else:
        df_records = pd.DataFrame(records)
        st.dataframe(df_records, use_container_width=True)
        
        st.markdown("#### Cryptographic Record Investigation")
        req_id = st.text_input("Execute deep extraction index by Request ID (e.g., REQ_990):")
        if req_id:
            with st.spinner("Extracting..."):
                detail = api.get(f"/audit/record/{req_id}")
                st.json(detail)

with t3:
    st.markdown("### Executive Overrides")
    st.warning("All overrides bypass autonomous model execution and inject directly into the retraining queue.")
    
    # Custom form container padding isn't native, but we can do our best
    with st.form("override_form", border=False):
        req_id = st.text_input("Request ID")
        justification = st.text_area("Cryptographic Justification Payload (Min 20 chars)")
        submitted = st.form_submit_button("Force Override")
        
        if submitted:
            if len(justification) < 20:
                st.error("Insufficient entropy. Provide extensive auditor reasoning.")
            elif not req_id:
                st.error("Provide a valid Request ID.")
            else:
                with st.spinner("Hashing payload..."):
                    res = api.post(f"/audit/record/{req_id}/override", data={"justification": justification})
                    st.success("Override successful. Hash safely embedded into ledger.")
                    st.json(res)

with t4:
    st.markdown("### Rules Management")
    rules = api.get("/rules")
    if "error" not in rules:
        st.table(rules)
    else:
        st.error("Failed to load rules.")
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Topology Scaling")
        with st.expander("Update Horizons"):
            r_id = st.text_input("Rule ID")
            new_weight = st.slider("New Weight Limitation", 0.0, 1.0, 0.5)
            if st.button("Update Configuration"):
                with st.spinner():
                    res = api.put(f"/rules/{r_id}", data={"weight": new_weight})
                    st.success(f"Rule {r_id} Updated successfully")
    with c2:
        st.markdown("#### Fallback Trigger")
        with st.expander("Nuclear Reset"):
            r_id_reset = st.text_input("Rule ID to wipe")
            if st.button("Reset Rule", type="primary"):
                with st.spinner():
                    res = api.post(f"/rules/reset/{r_id_reset}")
                    st.success("Rule Reset Applied")
    
    st.markdown("#### Execution Ledger")
    cl = api.get("/rules/changelog")
    st.table(cl)

with t5:
    st.markdown("### Human-In-The-Loop Feedback")
    with st.form("feedback_form", border=False):
        req_id = st.text_input("Transaction Request ID")
        verdict = st.selectbox("Auditor Verdict", ["APPROVED", "REJECTED", "REVIEW"])
        comments = st.text_area("Audit Log Comments")
        
        if st.form_submit_button("Write to Store"):
            with st.spinner("Injecting feedback into datastore..."):
                res = api.post("/feedback", data={"request_id": req_id, "verdict": verdict, "comments": comments})
                st.success("Feedback registered safely.")
                
    st.markdown("---")
    fc1, fc2 = st.columns(2)
    with fc1:
        st.markdown("#### Calibration Yield")
        st.json(api.get("/feedback/summary"))
    with fc2:
        st.markdown("#### Ground Truth Shape")
        st.json(api.get("/feedback/calibration-dataset"))

with t6:
    st.markdown("### Model Calibration")
    cc1, cc2, cc3 = st.columns(3)
    latest = api.get("/calibration/latest")
    cc1.metric("Last Epoch", latest.get("last_run", "Unknown"))
    cc2.metric("Eval F1", latest.get("f1_score", 0.0))
    calib_health = api.get("/calibration/health")
    
    health_status = calib_health.get("status", "Unknown")
    cc3.markdown(f"<div style='margin-top:10px; font-weight:600; color:#8B949E;'>SYSTEM READINESS</div><div style='margin-top:10px;'>{render_badge(health_status)}</div>", unsafe_allow_html=True)
    
    st.write("")
    if st.button("🚀 Trigger Re-Calibration Sequence"):
        with st.spinner("Re-aligning gradient boundaries... this operation consumes high VRAM."):
            res = api.post("/calibration/run")
            st.success("Sequence executed. Background workers engaged.")
            
    st.markdown("#### Epoch History")
    history = api.get("/calibration/history")
    if "error" not in history:
        st.table(history)

with t7:
    st.markdown("### Low-Level Diagnostics")
    st.info("Raw telemetry exports for core infrastructure pipelines.")
    
    with st.expander("GET /health : Network Discovery"):
        st.json(api.get("/health"))
    with st.expander("GET /ready : Broker Availability"):
        st.json(api.get("/ready"))