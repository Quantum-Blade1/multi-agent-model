import streamlit as st

st.title("🔐 Manager Dashboard")

# Initialize session state
if "is_unlocked" not in st.session_state:
    st.session_state.is_unlocked = False

if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = [
        {"id": 1, "user": "Roni", "loan_amount_asked": 100000, "emi": 2500, "kyc_proper": "Yes"},
        {"id": 2, "user": "Alex", "loan_amount_asked": 50000, "emi": 1200, "kyc_proper": "No"},
    ]

if "show_add_form" not in st.session_state:
    st.session_state.show_add_form = False

# 🔑 Unlock section
st.subheader("Access Control")

key = st.text_input("Enter Manager Key", type="password")

if st.button("Unlock"):
    if key == "hdfc15":
        st.session_state.is_unlocked = True
        st.success("Access Granted ✅")
    else:
        st.error("Invalid Key ❌")

# 📊 Audit List
st.subheader("📋 Audit Logs")

for log in st.session_state.audit_logs:
    st.write(log)

# 🔒 Immutable Notice
if not st.session_state.is_unlocked:
    st.warning("🔒 Data is immutable (Read-only mode)")
else:
    st.success("✏️ Edit Mode Enabled")

    if st.button("Add Record"):
        st.session_state.show_add_form = not st.session_state.show_add_form

    if st.session_state.show_add_form:
        st.markdown("---")
        st.subheader("Add New Loan Record")

        with st.form("add_record_form"):
            record_id = st.number_input("ID", min_value=1, step=1, value=1)
            user_name = st.text_input("User")
            loan_amount = st.number_input("Loan amount asked", min_value=0.0, value=0.0, step=1000.0, format="%f")
            emi = st.number_input("EMI", min_value=0.0, value=0.0, step=100.0, format="%f")
            kyc_proper = st.selectbox("KYC proper or not", ["Yes", "No"])
            submit_add = st.form_submit_button("Submit")

            if submit_add:
                existing_ids = [log["id"] for log in st.session_state.audit_logs]
                if record_id in existing_ids:
                    st.error(f"A record with ID {record_id} already exists. Choose a different ID.")
                elif not user_name:
                    st.error("Please enter a user name.")
                else:
                    st.session_state.audit_logs.append(
                        {
                            "id": int(record_id),
                            "user": user_name,
                            "loan_amount_asked": float(loan_amount),
                            "emi": float(emi),
                            "kyc_proper": kyc_proper,
                        }
                    )
                    st.session_state.show_add_form = False
                    st.success("Record added successfully ✅")
                    st.experimental_rerun()

    if st.button("Delete Record"):
        st.write("Delete logic here")

    if st.button("Modify Record"):
        st.write("Modify logic here")
