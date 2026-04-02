import streamlit as st

st.title("🔐 Manager Dashboard")

# Initialize session state
if "is_unlocked" not in st.session_state:
    st.session_state.is_unlocked = False

# 🔑 Unlock section
st.subheader("Access Control")

key = st.text_input("Enter Manager Key", type="password")

if st.button("Unlock"):
    if key == "hdfc15":
        st.session_state.is_unlocked = True
        st.success("Access Granted ✅")
    else:
        st.error("Invalid Key ❌")

# 📊 Audit List (Dummy Data)
st.subheader("📋 Audit Logs")

audit_logs = [
    {"id": 1, "action": "Approved Loan", "user": "Roni"},
    {"id": 2, "action": "Rejected KYC", "user": "Alex"},
]

for log in audit_logs:
    st.write(log)

# 🔒 Immutable Notice
if not st.session_state.is_unlocked:
    st.warning("🔒 Data is immutable (Read-only mode)")
else:
    st.success("✏️ Edit Mode Enabled")

    # ➕ Add
    if st.button("Add Record"):
        st.write("Add logic here")

    # ❌ Delete
    if st.button("Delete Record"):
        st.write("Delete logic here")

    # ✏️ Modify
    if st.button("Modify Record"):
        st.write("Modify logic here")