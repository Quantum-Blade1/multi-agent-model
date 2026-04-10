import streamlit as st
import pandas as pd
import os
import sys
curr_dir = os.path.dirname(__file__)
root_dir = os.path.abspath(os.path.join(curr_dir, "..", ".."))
frontend_dir = os.path.abspath(os.path.join(curr_dir, ".."))
if root_dir not in sys.path:
    sys.path.append(root_dir)
if frontend_dir not in sys.path:
    sys.path.append(frontend_dir)

from style_utils import inject_custom_css

st.set_page_config(page_title="Manager Dashboard | ComplianceLoop", layout="wide")

inject_custom_css()

st.markdown("<h1>Access Control Matrix</h1>", unsafe_allow_html=True)
st.divider()

# Initialize session state
if "is_unlocked" not in st.session_state:
    st.session_state.is_unlocked = False

# Initialize session state for logs if not exists
if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = pd.DataFrame([
        {"Manifest ID": "SYS-001", "Action": "Approved Facility", "Auditor": "Roni"},
        {"Manifest ID": "SYS-002", "Action": "Rejected KYC Payload", "Auditor": "Alex"},
    ])

c1, c2 = st.columns([1, 2])

with c1:
    with st.container():
        st.markdown("### Authentication")
        with st.form("auth", border=False):
            key = st.text_input("Sudo Execution Key", type="password")
            if st.form_submit_button("Authenticate Node"):
                if key == "hdfc15":
                    st.session_state.is_unlocked = True
                    st.success("Access Granted. Write mode engaged.")
                else:
                    st.session_state.is_unlocked = False
                    st.error("Authentication Rejected. Logged to immutable trace.")

with c2:
    with st.container():
        st.markdown("### Audit Logs Archive")
        if not st.session_state.is_unlocked:
            st.dataframe(st.session_state.audit_logs, use_container_width=True, hide_index=True)
        else:
            # Fully dynamic CRUD editor
            st.session_state.audit_logs = st.data_editor(
                st.session_state.audit_logs, 
                use_container_width=True, 
                hide_index=True,
                num_rows="dynamic",
                key="audit_editor"
            )

st.markdown("<br>", unsafe_allow_html=True)

with st.container():
    st.markdown("### Matrix Manipulation")
    if not st.session_state.is_unlocked:
        st.warning("Data is immutable (Read-only mode). Authenticate to unlock write operations.")
    else:
        st.info("Write Mode Engaged: You can now double-click cells in the table above to mutate data. Click the empty row at the bottom to append, or select rows and press 'Delete' to drop payloads.")

