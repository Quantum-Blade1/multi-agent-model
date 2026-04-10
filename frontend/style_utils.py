import streamlit as st

def inject_custom_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* Base Styles */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}

.stApp {
    background-color: #000000 !important;
    background-image: none !important;
}

h1, h2, h3, h4, h5, h6 {
    font-weight: 600 !important;
    color: #FAFAFA !important;
    letter-spacing: -0.5px !important;
}

p, span, div, li {
    color: #A1A1AA;
}

hr {
    border-color: rgba(255, 255, 255, 0.05) !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #050505 !important;
    border-right: 1px solid rgba(255, 255, 255, 0.05) !important;
}

/* Form Inputs */
.stTextInput input, .stTextArea textarea, .stSelectbox select, .stNumberInput input {
    background-color: #090909 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 6px !important;
    color: #FAFAFA !important;
    padding: 10px 14px !important;
    transition: all 0.2s ease !important;
}

.stTextInput input:focus, .stTextArea textarea:focus, .stSelectbox select:focus, .stNumberInput input:focus {
    border-color: #39FF14 !important;
    box-shadow: 0 0 0 1px #39FF14 !important;
}

/* Buttons */
.stButton > button, .stFormSubmitButton > button {
    background: #090909 !important;
    color: #FAFAFA !important;
    font-weight: 600 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 6px !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover, .stFormSubmitButton > button:hover {
    background: #262626 !important;
    color: #FFFFFF !important;
    border-color: #39FF14 !important;
}

.stButton > button:focus, .stFormSubmitButton > button:focus {
    box-shadow: 0 0 0 2px rgba(212, 175, 55, 0.4) !important;
}

[data-testid="stFormSubmitButton"] > button {
    background-color: #39FF14 !important;
    color: #000000 !important;
    border: 1px solid #39FF14 !important;
}

[data-testid="stFormSubmitButton"] > button:hover {
    background-color: #FDE047 !important;
    border-color: #FDE047 !important;
    color: #000000 !important;
}

/* Metrics */
[data-testid="stMetric"] {
    background-color: #050505 !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
    padding: 1.2rem !important;
    border-radius: 8px !important;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3) !important;
    border-top: 2px solid #52525B !important;
}

[data-testid="stMetricValue"] {
    font-size: 2rem !important;
    font-weight: 700 !important;
    color: #FAFAFA !important;
}

[data-testid="stMetricLabel"] {
    color: #A1A1AA !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 0.75rem !important;
}

/* Tabs */
[data-testid="stTabs"] button {
    border-bottom: 2px solid transparent !important;
    transition: all 0.2s ease;
    font-weight: 500 !important;
    color: #A1A1AA !important;
    background: transparent !important;
}

[data-testid="stTabs"] button[aria-selected="true"] {
    border-bottom: 2px solid #39FF14 !important;
    color: #39FF14 !important;
    font-weight: 600 !important;
}

/* Custom Panel Classes / Fake Cards */
.custom-card {
    background-color: #050505;
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
}

.custom-card h4 {
    margin-top: 0;
    color: #39FF14 !important;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
}

.panel-row {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255,255,255,0.02);
}

.panel-row:last-child {
    border-bottom: none;
}

.panel-label {
    color: #A1A1AA;
    font-size: 0.9rem;
    font-weight: 500;
}

.panel-value {
    color: #FAFAFA;
    font-size: 0.9rem;
    font-weight: 600;
}

/* Badges */
.badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

.badge-approved { background: rgba(16, 185, 129, 0.1); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.3); }
.badge-rejected { background: rgba(239, 68, 68, 0.1); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.3); }
.badge-review { background: rgba(212, 175, 55, 0.1); color: #39FF14; border: 1px solid rgba(212, 175, 55, 0.3); }
.badge-neutral { background: rgba(161, 161, 170, 0.1); color: #A1A1AA; border: 1px solid rgba(161, 161, 170, 0.3); }

/* Tables Raw HTML styling */
div.stMarkdown table {
    border-collapse: collapse;
    width: 100%;
    margin-top: 0.5rem;
    background-color: #050505;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.05);
}
div.stMarkdown th {
    background-color: rgba(255, 255, 255, 0.02);
    color: #A1A1AA;
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 1px;
    padding: 12px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    font-weight: 600;
    text-align: left;
}
div.stMarkdown td {
    padding: 12px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.02);
    color: #FAFAFA;
    font-weight: 500;
    font-size: 0.85rem;
}
div.stMarkdown tr:hover {
    background-color: rgba(255, 255, 255, 0.02);
}

/* Dataframe Overrides */
[data-testid="stDataFrame"] {
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 8px !important;
}

/* Warnings / Info Blocks */
[data-testid="stAlert"] {
    background-color: #203B37 !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    color: #E6F2EF !important;
}

[data-testid="stAlert"] p {
    color: #E6F2EF !important;
}
</style>
    """, unsafe_allow_html=True)

def get_badge_html(status: str) -> str:
    status_upper = str(status).upper()
    if status_upper in ["APPROVED", "HEALTHY", "READY"]:
        cls = "badge-approved"
    elif status_upper in ["REJECTED", "DEGRADED", "UNCALIBRATED"]:
        cls = "badge-rejected"
    elif status_upper in ["REVIEW", "STALE"]:
        cls = "badge-review"
    else:
        cls = "badge-neutral"
    
    return f'<span class="badge {cls}">{status_upper}</span>'
