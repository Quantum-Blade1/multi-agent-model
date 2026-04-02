import streamlit as st
import os

st.set_page_config(
    page_title="ComplianceLoop",
    layout="wide"
)

# Custom CSS for "Top 1%" Design
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
.gradient-text {
    background: linear-gradient(135deg, #D4AF37 0%, #F3D270 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
}
[data-testid="stSidebar"] {
    background: rgba(18, 20, 29, 0.7) !important;
    backdrop-filter: blur(16px) !important;
    border-right: 1px solid rgba(255, 255, 255, 0.05);
}
.stButton > button {
    background: linear-gradient(135deg, #D4AF37 0%, #A28220 100%) !important;
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
.hero-box {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.05);
    padding: 2rem;
    border-radius: 12px;
    border-left: 4px solid #D4AF37;
    margin-bottom: 2rem;
    margin-top: 1rem;
    backdrop-filter: blur(12px);
    transition: transform 0.4s ease, box-shadow 0.4s ease;
}
.hero-box:hover {
    transform: translateY(-4px);
    box-shadow: 0 15px 35px rgba(0, 0, 0, 0.4), 0 0 15px rgba(212, 175, 55, 0.05);
}
h1, h2, h3 { font-weight: 600 !important; letter-spacing: -0.5px; }
hr { border-color: rgba(255, 255, 255, 0.05) !important; }

@keyframes typing {
    from { width: 0; }
    to { width: 100%; }
}
@keyframes blink-caret {
    from, to { border-color: transparent; }
    50% { border-color: #D4AF37; }
}
.typing-container {
    display: flex;
    justify-content: center;
    width: 100%;
}
.typing-text {
    overflow: hidden;
    white-space: nowrap;
    border-right: 3px solid #D4AF37;
    margin: 0;
    padding-right: 8px;
    animation: typing 2.2s steps(40, end) forwards, blink-caret .8s step-end infinite;
}
</style>
""", unsafe_allow_html=True)

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

c1, c2, c3 = st.columns([1, 8, 1])

with c2:
    st.markdown("""
    <div class='typing-container'>
        <h1 class='gradient-text typing-text' style='font-size:4rem;'>Heapifying the Compliance Intelligence</h1>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <h3 style='text-align:center; color:#8B949E; margin-bottom: 2rem;'>AI-Powered Regulatory Intelligence System</h3>
    <p style='text-align:center; font-size: 1.2rem; color:#A0AEC0;'>Automating compliance decisions using a multi-agent architecture combining <br>rule-based validation, risk detection, and LLM-driven reasoning.</p>
    """, unsafe_allow_html=True)

    st.divider()

    st.subheader("What is ComplianceLoop?")
    st.markdown("""
    ComplianceLoop is a regulatory-grade system designed to:
    
    - Analyze evolving compliance guidelines (e.g., RBI policies)
    - Compare historical vs updated regulations
    - Enforce transaction-level compliance checks
    - Provide auditable, explainable decisions
    
    Built for auditors, regulators, and financial systems.
    """)

    st.subheader("How It Works")
    st.markdown("""
    <div class="hero-box">
        <ol style="font-size: 1.1rem; line-height: 1.8; color: #E2E8F0; margin-bottom: 0;">
            <li><b>RAG Engine</b> extracts regulatory knowledge from multiple guideline documents</li>
            <li><b>Compliance Agent</b> merges and interprets rules using AI</li>
            <li><b>Transaction Engine</b> validates business logic deterministically</li>
            <li><b>Sanctions Agent</b> flags risky or suspicious entities</li>
            <li><b>Decision Engine</b> produces final compliance verdict with reasoning</li>
        </ol>
        <p style="margin-top: 1.5rem; color: #D4AF37; font-weight: 600; margin-bottom: 0;">Every decision is traceable and auditable.</p>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("Core Capabilities")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        - Dual-policy comparison (OLD vs NEW)
        - AI-assisted compliance reasoning
        - Risk scoring & fraud signals
        """)
    with col2:
        st.markdown("""
        - Full audit trail per request
        - Rule-based + AI hybrid system
        - Explainable decision outputs
        """)

    st.write("")

    st.subheader("Built For")
    st.markdown("""
    - Financial Institutions  
    - Regulatory Bodies (RBI-style governance)  
    - Internal Audit Teams  
    - Compliance Review Systems  
    """)

    st.write("")

    st.subheader("Trust & Governance")
    st.markdown("""
    ComplianceLoop ensures:
    
    - Deterministic rule enforcement before AI reasoning  
    - Full audit traceability of every decision  
    - Structured outputs aligned with regulatory expectations  
    
    Designed for high-stakes financial environments.
    """)

    st.divider()

    st.info("Navigate to the Auditor Dashboard from the sidebar to review system decisions and controls.")
