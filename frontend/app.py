import streamlit as st
import os
from style_utils import inject_custom_css

# Define pages with custom titles (matching the user's request)
pg1 = st.Page("home_page.py", title="Home", icon="🏠", default=True)
pg2 = st.Page("pages/1_Operation_Dashboard.py", title="Admin", icon="⚙️")
pg3 = st.Page("pages/2_User_Workspace.py", title="Customer", icon="👤")
pg4 = st.Page("pages/3_manager_dashboard.py", title="Manager", icon="📈")

pg = st.navigation([pg1, pg2, pg3, pg4])

st.set_page_config(page_title="ComplianceLoop", layout="wide")
inject_custom_css()

# Global Auth State
if "api_key" not in st.session_state:
    st.session_state["api_key"] = ""
if "auth_status" not in st.session_state:
    st.session_state["auth_status"] = False

with st.sidebar:
    st.markdown("### Secure Login")
    api_key_input = st.text_input("Auditor Key", type="password")
    if st.button("Authenticate", use_container_width=True):
        if api_key_input:
            st.session_state["api_key"] = api_key_input
            if len(api_key_input) >= 3:
                st.session_state["auth_status"] = True
                st.success("Authenticated successfully!")
            else:
                st.session_state["auth_status"] = False
                st.error("Invalid API Key.")
        else:
            st.warning("Please enter a key.")

# Run the routed page
pg.run()
