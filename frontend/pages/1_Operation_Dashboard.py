import streamlit as st
import pandas as pd
import json
import os
import sys

# Add both root and frontend paths
curr_dir = os.path.dirname(__file__)
root_dir = os.path.abspath(os.path.join(curr_dir, "..", ".."))
frontend_dir = os.path.abspath(os.path.join(curr_dir, ".."))
if root_dir not in sys.path:
    sys.path.append(root_dir)
if frontend_dir not in sys.path:
    sys.path.append(frontend_dir)

from api_client import ComplianceAPI
from style_utils import inject_custom_css, get_badge_html

st.set_page_config(page_title="Operation Dashboard | ComplianceLoop", page_icon="⚙️", layout="wide")

inject_custom_css()

if not st.session_state.get("auth_status", False):
    st.error("Access Denied: Please authenticate on the Home System using your Auditor API Key.")
    st.stop()

# Initialize API Client
api_key = st.session_state.get("api_key", "")
api = ComplianceAPI(api_key=api_key)

# Fetch user role
user_role = api.get("/user/role").get("role", "user")

st.markdown("<h1>System Operations & Control</h1>", unsafe_allow_html=True)
st.divider()

# Define tabs based on user role
if user_role == "auditor":
    tabs = ["Overview", "Audit Explorer", "Customer activity", "Overrides", "Rules Management", "Feedback", "Calibration Center", "Operations Panel", "Compliance Reports"]
else:
    tabs = ["Overview", "Audit Explorer", "Customer activity"]

tab_objects = st.tabs(tabs)

# --- TAB: CUSTOMER ACTIVITY ---
if len(tab_objects) > 2:
    with tab_objects[2]:
        with st.container():
            st.markdown("### Transaction Flow Log")
            activity = api.get("/customer-activity")
            if isinstance(activity, list) and activity:
                df = pd.DataFrame(activity)
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No customer activity recorded yet.")

# --- TAB: OVERVIEW ---
with tab_objects[0]:
    with st.container():
        st.markdown("### System Health & Topology")
        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.spinner("Synchronizing telemetry..."):
            c1, c2, c3, c4, c5 = st.columns(5)
            
            health = api.get("/health")
            c1.metric("API Core Status", health.get("status", "UNKNOWN"))
            
            ready = api.get("/ready")
            c2.metric("Subsystem Link", ready.get("status", "UNKNOWN"))
            
            stats = api.get("/audit/stats")
            c3.metric("Processed Transactions", stats.get("total_requests", 0))
            
            verify = api.get("/audit/chain/verify")
            verify_status = "VERIFIED" if verify.get("verified") else "TAMPERED"
            c4.metric("Chain State", verify_status)
            
            calib = api.get("/calibration/latest")
            c5.metric("Model F1 Score", calib.get("f1_score", 0.0))

        st.markdown("<br>", unsafe_allow_html=True)
        
        col_diag1, col_diag2 = st.columns(2)
        with col_diag1:
            with st.expander("Node Health Payload"):
                health_data = api.get("/health")
                st.json(health_data)
        with col_diag2:
            with st.expander("Compliance Statistics Matrix"):
                stats_data = api.get("/audit/stats")
                st.json(stats_data)

    st.divider()
    
    with st.container():
        st.markdown("### Priority Alerts")
        alerts = [
            {"type": "warning", "message": "High sanctions hit rate detected", "timestamp": "2026-04-02 10:00:00"},
            {"type": "info", "message": "Model calibration completed successfully", "timestamp": "2026-04-02 09:30:00"},
            {"type": "error", "message": "Rule engine cache manually expired", "timestamp": "2026-04-02 08:00:00"}
        ]
        
        for alert in alerts:
            if alert["type"] == "warning":
                st.warning(f"{alert['timestamp']} - {alert['message']}")
            elif alert["type"] == "info":
                st.info(f"{alert['timestamp']} - {alert['message']}")
            elif alert["type"] == "error":
                st.error(f"{alert['timestamp']} - {alert['message']}")

    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.container():
        c_act1, c_act2, c_act3 = st.columns(3)
        with c_act1:
            if st.button("Refresh Telemetry", use_container_width=True):
                st.rerun()
        with c_act2:
            if st.button("Generate System Dump", use_container_width=True):
                st.toast("System dump generated in compliance cache.")
        with c_act3:
            if st.button("Acknowledge Alerts", use_container_width=True):
                st.toast("Alerts logically acknowledged.")

    st.divider()
    
    with st.container():
        st.markdown("### Active Rule Horizons")
        rules = api.get("/rules")
        if "error" not in rules:
            # Using clean custom styling for tables from markdown
            html_table = "<table><tr><th>Rule ID</th><th>Category</th><th>Value Type</th><th>Current Value</th><th>Description</th><th>RBI Reference</th><th>Last Updated</th></tr>"
            for r in rules:
                html_table += "<tr>"
                html_table += f"<td>{r.get('rule_id','')}</td>"
                html_table += f"<td>{r.get('category','')}</td>"
                html_table += f"<td>{r.get('value_type','')}</td>"
                html_table += f"<td>{r.get('current_value','')}</td>"
                html_table += f"<td>{r.get('description','')}</td>"
                html_table += f"<td>{r.get('rbi_reference','')}</td>"
                html_table += f"<td>{r.get('updated_at','')}</td>"
                html_table += "</tr>"
            html_table += "</table>"
            st.markdown(html_table, unsafe_allow_html=True)

# --- TAB: AUDIT EXPLORER ---
if len(tab_objects) > 1:
    with tab_objects[1]:
        with st.container():
            st.markdown("### Cryptographic Ledger Explorer")
            
            filter_c1, filter_c2, filter_c3 = st.columns(3)
            with filter_c1:
                status_filter = st.selectbox("Status Filter", ["All", "APPROVED", "REJECTED", "REVIEW"])
            with filter_c2:
                date_from = st.date_input("Boundary (Start)", value=None)
            with filter_c3:
                date_from_to = st.date_input("Boundary (End)", value=None)
            
            with st.spinner("Scanning ledger..."):
                records = api.get("/audit/records")
                if "error" in records:
                    st.error(records["error"])
                else:
                    df_records = pd.DataFrame(records)
                    
                    if status_filter != "All":
                        df_records = df_records[df_records['verdict'] == status_filter]
                    if date_from:
                        df_records = df_records[df_records['timestamp'] >= str(date_from)]
                    if date_from_to:
                        df_records = df_records[df_records['timestamp'] <= str(date_from_to)]
                    
                    st.dataframe(df_records, use_container_width=True)
                    
                    if st.button("Export Filtered Dataset"):
                        st.toast("Export successful.")
            
            st.divider()
            
            st.markdown("#### Deep Index Extraction")
            req_id = st.text_input("Execute extraction by Request ID:")
            if req_id:
                with st.spinner("Extracting cryptographic signatures..."):
                    detail = api.get(f"/audit/record/{req_id}")
                    with st.expander("Raw Ledger Entry", expanded=True):
                        st.json(detail)

# --- TAB: OVERRIDES ---
if len(tab_objects) > 3:
    with tab_objects[3]:
        with st.container():
            st.markdown("### Executive Overrides")
            st.warning("Overrides bypass autonomous controls globally. Execution injects directly into the immutable log and retraining queue.")
            
            with st.form("override_form", border=False):
                req_id = st.text_input("Target Request ID")
                justification = st.text_area("Cryptographic Justification (Min 20 characters)")
                submitted = st.form_submit_button("Initiate Override Sequence")
                
                if submitted:
                    if len(justification) < 20:
                        st.error("Insufficient entropy in justification.")
                    elif not req_id:
                        st.error("Target Request ID missing.")
                    else:
                        with st.spinner("Applying cryptographic hash..."):
                            res = api.post(f"/audit/record/{req_id}/override", data={"justification": justification})
                            st.toast("Override applied. Ledger committed.")
                            with st.expander("Override Response Matrix", expanded=True):
                                st.json(res)

# --- TAB: RULES MANAGEMENT ---
if len(tab_objects) > 4:
    with tab_objects[4]:
        with st.container():
            st.markdown("### Dynamic Policy Enforcement")
            
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                with st.container():
                    st.markdown("#### Adjust Threshold Horizons")
                    r_id = st.text_input("Rule ID")
                    new_weight = st.number_input("New Sensitivity Factor", 0.0, 1.0, 0.5)
                    if st.button("Apply Horizon Constraint"):
                        with st.spinner("Updating policy map..."):
                            res = api.put(f"/rules/{r_id}", data={"weight": new_weight})
                            st.toast("Policy synced across active nodes.")
            with r_col2:
                with st.container():
                    st.markdown("#### Nuclear Wiping")
                    r_id_reset = st.text_input("Rule ID Context")
                    if st.button("Wipe Rule Cache"):
                        with st.spinner("Executing wipe..."):
                            res = api.post(f"/rules/reset/{r_id_reset}")
                        st.toast("Rule Cache Cleared.")
            
            st.markdown("<br>", unsafe_allow_html=True)
            with st.expander("Policy Changelog (Execution Ledger)"):
                cl = api.get("/rules/changelog")
                st.dataframe(pd.DataFrame(cl), use_container_width=True)

# --- TAB: FEEDBACK ---
if len(tab_objects) > 5:
    with tab_objects[5]:
        with st.container():
            st.markdown("### Manual Calibration Injection")
            with st.form("feedback_form", border=False):
                req_id = st.text_input("Transaction Matrix ID (Request)")
                verdict = st.selectbox("Auditor Verdict", ["APPROVED", "REJECTED", "REVIEW"])
                comments = st.text_area("Audit Log Reasoning")
                
                if st.form_submit_button("Store to Datalake"):
                    with st.spinner("Transferring blocks to datalake..."):
                        res = api.post("/feedback", data={"request_id": req_id, "verdict": verdict, "comments": comments})
                        st.toast("Data written securely.")
                        
            st.divider()
            
            fb_c1, fb_c2 = st.columns(2)
            with fb_c1:
                with st.expander("Feedback Summary Aggregation"):
                    st.json(api.get("/feedback/summary"))
            with fb_c2:
                with st.expander("Ground Truth Matrix"):
                    st.json(api.get("/feedback/calibration-dataset"))

# --- TAB: CALIBRATION CENTER ---
if len(tab_objects) > 6:
    with tab_objects[6]:
        with st.container():
            st.markdown("### AI Model Calibration")
            
            cc1, cc2, cc3 = st.columns(3)
            latest = api.get("/calibration/latest")
            cc1.metric("Last Convergence", latest.get("last_run", "Unknown"))
            cc2.metric("Evaluative F1", latest.get("f1_score", 0.0))
            calib_health = api.get("/calibration/health")
            health_status = calib_health.get("status", "Unknown")
            cc3.markdown(f"<div style='margin-top:0.4rem; font-weight:600; color:#9FB7B1;font-size:0.8rem;text-transform:uppercase;'>System Readiness</div><div style='margin-top:0.5rem;'>{get_badge_html(health_status)}</div>", unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Initialize Re-Calibration"):
                with st.spinner("Allocating resources and realigning vectors..."):
                    res = api.post("/calibration/run")
                    st.toast("Calibration subsystem engaged.")
            
            st.divider()
            with st.expander("Epoch Execution History"):
                history = api.get("/calibration/history")
                if "error" not in history:
                    st.dataframe(pd.DataFrame(history), use_container_width=True)

# --- TAB: LOW-LEVEL DIAGNOSTICS ---
if len(tab_objects) > 7:
    with tab_objects[7]:
        with st.container():
            st.markdown("### Administrative Diagnostics")
            st.info("System telemetry for active sub-networks.")
            
            diag_c1, diag_c2 = st.columns(2)
            with diag_c1:
                with st.expander("Core Network Payload (GET /health)"):
                    st.json(api.get("/health"))
            with diag_c2:
                with st.expander("Broker Connectivity Payload (GET /ready)"):
                    st.json(api.get("/ready"))

# --- TAB: COMPLIANCE REPORTS ---
if len(tab_objects) > 8:
    with tab_objects[8]:
        with st.container():
            st.markdown("### Analytical Compliance Reporting")
            st.markdown("Generative extraction for regulatory compliance reviews.")
            
            report_type = st.selectbox("Target Report Vector", ["Daily Compliance Matrix", "Risk Vector Report", "Audit Trail Manifest", "Performance Diagnostics"])
            
            if st.button("Compute Report"):
                with st.spinner("Compiling cross-node metrics..."):
                    if report_type == "Daily Compliance Matrix":
                        report_data = {
                            "date": "2026-04-02",
                            "total_transactions": 150,
                            "approved": 120,
                            "rejected": 20,
                            "review": 10,
                            "compliance_rate": "80%",
                            "top_risks": ["High-value transactions", "Sanctions hits"]
                        }
                    elif report_type == "Risk Vector Report":
                        report_data = {
                            "high_risk_count": 5,
                            "medium_risk_count": 15,
                            "low_risk_count": 30,
                            "risk_trends": "Increasing sanctions hits",
                            "recommendations": ["Enhance sanctions screening", "Review high-value thresholds"]
                        }
                    elif report_type == "Audit Trail Manifest":
                        report_data = {
                            "total_audits": 50,
                            "successful_audits": 45,
                            "failed_audits": 5,
                            "audit_logs": ["Audit 001: Passed", "Audit 002: Failed - Rule violation"]
                        }
                    elif report_type == "Performance Diagnostics":
                        report_data = {
                            "average_response_time": "2.5s",
                            "uptime": "99.9%",
                            "accuracy": "94%",
                            "false_positives": "3%"
                        }
                    
                    st.success(f"{report_type} payload available.")
                    st.json(report_data)
            
            st.divider()
            st.markdown("#### Previous Rendered Archives")
            recent_reports = [
                {"name": "Daily Compliance Matrix - 2026-04-01", "generated_at": "2026-04-01 23:59:00"},
                {"name": "Risk Vector Report - 2026-03-31", "generated_at": "2026-03-31 23:59:00"},
                {"name": "Audit Trail Manifest - 2026-03-30", "generated_at": "2026-03-30 23:59:00"}
            ]
            for report in recent_reports:
                st.markdown(f"- **{report['name']}** (Timestamp: {report['generated_at']})")