import streamlit as st
from style_utils import inject_custom_css

c1, c2, c3 = st.columns([1, 8, 1])

with c2:
    st.markdown("""
    <style>
    @keyframes typing {
        from { width: 0; }
        to { width: 100%; }
    }
    @keyframes blink-caret {
        from, to { border-color: transparent; }
        50% { border-color: #39FF14; }
    }
    @keyframes floatGraphic {
        0% { transform: translateY(0px) rotate(0deg); }
        50% { transform: translateY(-15px) rotate(1deg); }
        100% { transform: translateY(0px) rotate(0deg); }
    }
    @keyframes riseUp {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    .hero-graphic {
        display: block;
        margin: 0 auto 2rem auto;
        height: 220px;
        object-fit: contain;
        animation: floatGraphic 6s ease-in-out infinite, riseUp 1.2s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        filter: drop-shadow(0 15px 25px rgba(57, 255, 20,0.15));
    }
    .typing-container {
        display: flex;
        justify-content: center;
        width: 100%;
        margin-bottom: 0.5rem;
    }
    .fintech-gradient {
        background: linear-gradient(135deg, #39FF14 0%, #39FF14 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .typing-text {
        overflow: hidden;
        white-space: nowrap;
        border-right: 4px solid #39FF14;
        margin: 0;
        padding-right: 8px;
        animation: typing 2.2s steps(40, end) forwards, blink-caret .8s step-end infinite;
        font-size: 3.8rem;
        font-family: 'Georgia', serif; /* different elegant style */
        font-weight: 400;
        color: #FFFFFF !important;
        line-height: 1.2;
        letter-spacing: -1px;
    }
    .rise-text {
        text-align: center;
        font-size: 1.3rem;
        font-weight: 600;
        margin-bottom: 2rem;
        opacity: 0;
        animation: riseUp 1.2s cubic-bezier(0.16, 1, 0.3, 1) 1.5s forwards;
    }
    </style>
    
    <img src="https://i.postimg.cc/hcSHRD2P/b37b5896a527409cb4ac3ad6ba0904a2-removebg-preview.png" class="hero-graphic" alt="System Graphic" />
    <div class='typing-container'>
        <h1 class='typing-text'>Heapifying Compliance Intelligence</h1>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<p class='rise-text fintech-gradient'>Automated, authoritative compliance decisions using deterministic rules and LLM reasoning.</p>", unsafe_allow_html=True)

    st.divider()

    # encapsulated structural info
    st.markdown("""
    <style>
    @keyframes typingSub {
        from { width: 0; }
        to { width: 100%; }
    }
    .typing-sub-container {
        display: flex;
        justify-content: center;
        width: 100%;
        margin-bottom: 1rem;
        margin-top: 2rem;
    }
    .typing-text-sub {
        overflow: hidden;
        white-space: nowrap;
        border-right: 3px solid #39FF14;
        margin: 0;
        padding-right: 8px;
        animation: typingSub 1.5s steps(40, end) forwards, blink-caret .8s step-end infinite;
        font-size: 1.8rem;
        font-weight: 600;
        color: #FAFAFA;
    }
    .center-desc {
        text-align: center;
        color: #A1A1AA;
        font-size: 1.1rem;
        max-width: 800px;
        margin: 0 auto 1.5rem auto;
        line-height: 1.5;
    }
    .flow-container {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 2.5rem 0 1.5rem 0;
        width: 100%;
    }
    .flow-node {
        background: #050505;
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-top: 2px solid #52525B;
        padding: 1rem 1.2rem;
        border-radius: 8px;
        color: #FAFAFA;
        font-weight: 600;
        text-align: center;
        font-size: 0.85rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        z-index: 2;
        position: relative;
        transition: transform 0.3s ease, border-color 0.3s ease;
        flex: 1;
        max-width: 160px;
    }
    .flow-node:hover {
        transform: translateY(-3px);
        border-color: #39FF14;
    }
    .flow-node.highlight {
        border-top: 2px solid #39FF14;
        background: rgba(212, 175, 55, 0.05);
    }
    .flow-line {
        flex-grow: 1;
        height: 2px;
        background: rgba(255, 255, 255, 0.05);
        margin: 0 8px;
        position: relative;
        overflow: hidden;
        z-index: 1;
    }
    .flow-dot {
        position: absolute;
        top: 0;
        left: 0;
        width: 40px;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(212, 175, 55, 0.8), transparent);
        animation: flowAnim 2.5s infinite cubic-bezier(0.4, 0, 0.2, 1);
    }
    .dot-delay-1 { animation-delay: 0.8s; }
    .dot-delay-2 { animation-delay: 1.6s; }
    .dot-delay-3 { animation-delay: 2.4s; }
    
    @keyframes flowAnim {
        0% { left: -40px; }
        100% { left: 100%; }
    }
    </style>
    
    <div class='typing-sub-container'>
        <h2 class='typing-text-sub'>System Overview</h2>
    </div>
    <div class='center-desc'>
        ComplianceLoop is a regulatory-grade system designed for auditors and central bank governance.
        It systematically analyzes policies, enforces checks, and produces cryptographically verifiable audit trails.
    </div>
    
    <div class="flow-container">
        <div class="flow-node">Client Request</div>
        <div class="flow-line"><div class="flow-dot"></div></div>
        <div class="flow-node">Multi-Agent Swarm</div>
        <div class="flow-line"><div class="flow-dot dot-delay-1"></div></div>
        <div class="flow-node highlight">Decision Engine</div>
        <div class="flow-line"><div class="flow-dot dot-delay-2"></div></div>
        <div class="flow-node">Immutable Ledger</div>
        <div class="flow-line"><div class="flow-dot dot-delay-3"></div></div>
        <div class="flow-node">Calibration Sync</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <style>
    @keyframes smooth-reveal {
        0% { clip-path: polygon(0 0, 0 0, 0 100%, 0% 100%); opacity: 0; }
        10% { opacity: 1; }
        100% { clip-path: polygon(0 0, 100% 0, 100% 100%, 0 100%); opacity: 1;}
    }
    .typing-alt {
        display: inline-block;
        animation: smooth-reveal 2s cubic-bezier(0.65, 0, 0.076, 1) forwards;
        border-right: 3px solid #39FF14;
        padding-right: 5px;
    }
    
    .marquee-container {
        display: flex;
        overflow: hidden;
        position: relative;
        padding: 0.5rem 0;
        margin-bottom: 4rem;
        mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
        -webkit-mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
    }
    .marquee-content {
        display: flex;
        gap: 2rem;
        animation: scroll 25s linear infinite;
        min-width: 100%;
        padding-left: 2rem;
    }
    .marquee-content:hover {
        animation-play-state: paused;
    }
    @keyframes scroll {
        0% { transform: translateX(0); }
        100% { transform: translateX(-50%); } 
    }
    .stat-card {
        background: #050505;
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-top: 2px solid #39FF14;
        border-radius: 8px;
        padding: 1.5rem 2.5rem;
        min-width: 260px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.3s ease, background 0.3s ease;
    }
    .stat-card:hover {
        background: #090909;
        transform: translateY(-5px);
    }
    .stat-number {
        font-size: 2.5rem;
        font-weight: 800;
        color: #FAFAFA;
        margin-bottom: 0.2rem;
        letter-spacing: -1px;
    }
    .stat-label {
        font-size: 0.85rem;
        color: #A1A1AA;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        font-weight: 600;
    }
    .trusted-wrapper {
        text-align: center;
        margin-top: 3rem;
        margin-bottom: 1.5rem;
    }
    </style>
    
    <div class="trusted-wrapper">
        <h3 class='typing-alt' style="font-size: 1.8rem; font-weight: 600; color: #FAFAFA;">Trusted By :</h3>
    </div>
    
    <div class="marquee-container">
        <div class="marquee-content">
            <!-- Set 1 -->
            <div class="stat-card"><div class="stat-number">50M+</div><div class="stat-label">Transactions Processed</div></div>
            <div class="stat-card"><div class="stat-number">35+</div><div class="stat-label">Global Central Banks</div></div>
            <div class="stat-card"><div class="stat-number">$120B</div><div class="stat-label">Capital Monitored</div></div>
            <div class="stat-card"><div class="stat-number">99.9%</div><div class="stat-label">Audit Accuracy</div></div>
            <div class="stat-card"><div class="stat-number">10k+</div><div class="stat-label">Active Ledger Nodes</div></div>
            <!-- Set 2 -->
            <div class="stat-card"><div class="stat-number">50M+</div><div class="stat-label">Transactions Processed</div></div>
            <div class="stat-card"><div class="stat-number">35+</div><div class="stat-label">Global Central Banks</div></div>
            <div class="stat-card"><div class="stat-number">$120B</div><div class="stat-label">Capital Monitored</div></div>
            <div class="stat-card"><div class="stat-number">99.9%</div><div class="stat-label">Audit Accuracy</div></div>
            <div class="stat-card"><div class="stat-number">10k+</div><div class="stat-label">Active Ledger Nodes</div></div>
        </div>
    </div>
    
    <div class="trusted-wrapper" style="margin-top: 4rem;">
        <h3 class='typing-alt' style="font-size: 1.8rem; font-weight: 600; color: #39FF14; display: inline-block;">NBFC Association</h3>
    </div>
    
    <style>
    @keyframes scroll-right {
        0% { transform: translateX(-50%); }
        100% { transform: translateX(0%); } 
    }
    .marquee-container-right {
        display: flex;
        overflow: hidden;
        position: relative;
        padding: 1rem 0;
        margin-bottom: 4rem;
        mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
        -webkit-mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
    }
    .marquee-content-right {
        display: flex;
        gap: 2rem;
        animation: scroll-right 28s linear infinite;
        min-width: 200%;
    }
    .marquee-content-right:hover {
        animation-play-state: paused;
    }
    .atm-card {
        background: linear-gradient(135deg, #0A0A0A 0%, #000000 100%);
        border: 1px solid rgba(57, 255, 20, 0.4);
        border-radius: 12px;
        min-width: 300px;
        height: 180px;
        padding: 1.5rem;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        box-shadow: 0 10px 20px rgba(0,0,0,0.4);
        position: relative;
        overflow: hidden;
        transition: transform 0.3s ease, border-color 0.3s ease;
    }
    .atm-card:hover {
        transform: scale(1.05);
        border-color: #FAFAFA;
        z-index: 10;
    }
    .atm-card::after {
        content: '';
        position: absolute;
        top: 0; right: 0; bottom: 0; left: 0;
        background: linear-gradient(125deg, rgba(255,255,255,0.08) 0%, transparent 40%);
        pointer-events: none;
    }
    .atm-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
    }
    .atm-chip {
        width: 38px; height: 28px;
        background: linear-gradient(135deg, #66FF4D 0%, #9A7120 100%);
        border-radius: 4px;
        position: relative;
        overflow: hidden;
    }
    .atm-chip::after {
        content: ''; position: absolute; width: 100%; height: 1px; background: rgba(0,0,0,0.2); top: 50%;
    }
    .atm-chip::before {
        content: ''; position: absolute; width: 1px; height: 100%; background: rgba(0,0,0,0.2); left: 50%;
    }
    .atm-bank {
        font-size: 1.1rem;
        font-weight: 700;
        color: #FAFAFA;
        text-align: right;
        letter-spacing: 0.5px;
        font-family: 'Inter', sans-serif;
    }
    .atm-number {
        font-family: 'Courier New', monospace;
        font-size: 1.4rem;
        color: #E0E0E0;
        letter-spacing: 3px;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
    }
    .atm-footer {
        display: flex;
        justify-content: space-between;
        font-size: 0.75rem;
        color: #A1A1AA;
        text-transform: uppercase;
        font-family: 'Inter', sans-serif;
        letter-spacing: 1px;
    }
    .nfc-icon {
        font-size: 1.2rem;
        color: #A1A1AA;
    }
    </style>
    
    <div class="marquee-container-right">
        <div class="marquee-content-right">
            <!-- Set 1 -->
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Global Trust NBFC</div>
                </div>
                <div class="atm-number">**** **** **** 4092</div>
                <div class="atm-footer"><span>Valid Thru 12/28</span><span class="nfc-icon">)))</span></div>
            </div>
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Apex Finance</div>
                </div>
                <div class="atm-number">**** **** **** 8119</div>
                <div class="atm-footer"><span>Valid Thru 05/29</span><span class="nfc-icon">)))</span></div>
            </div>
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Vanguard Capital</div>
                </div>
                <div class="atm-number">**** **** **** 2201</div>
                <div class="atm-footer"><span>Valid Thru 08/27</span><span class="nfc-icon">)))</span></div>
            </div>
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Crest Financial</div>
                </div>
                <div class="atm-number">**** **** **** 7734</div>
                <div class="atm-footer"><span>Valid Thru 10/30</span><span class="nfc-icon">)))</span></div>
            </div>
            <!-- Set 2 (Duplicate for Seamless Scroll) -->
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Global Trust NBFC</div>
                </div>
                <div class="atm-number">**** **** **** 4092</div>
                <div class="atm-footer"><span>Valid Thru 12/28</span><span class="nfc-icon">)))</span></div>
            </div>
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Apex Finance</div>
                </div>
                <div class="atm-number">**** **** **** 8119</div>
                <div class="atm-footer"><span>Valid Thru 05/29</span><span class="nfc-icon">)))</span></div>
            </div>
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Vanguard Capital</div>
                </div>
                <div class="atm-number">**** **** **** 2201</div>
                <div class="atm-footer"><span>Valid Thru 08/27</span><span class="nfc-icon">)))</span></div>
            </div>
            <div class="atm-card">
                <div class="atm-header">
                    <div class="atm-chip"></div>
                    <div class="atm-bank">Crest Financial</div>
                </div>
                <div class="atm-number">**** **** **** 7734</div>
                <div class="atm-footer"><span>Valid Thru 10/30</span><span class="nfc-icon">)))</span></div>
            </div>
        </div>
    </div>
    
    <br>
    """, unsafe_allow_html=True)
    
    # "How It Works" as a horizontal card layout instead of a plain list
    st.markdown("""
    <style>
    @keyframes blur-in-expand {
        0% { filter: blur(12px); opacity: 0; transform: scale(0.95); }
        100% { filter: blur(0px); opacity: 1; transform: scale(1); }
    }
    .track-animation {
        animation: blur-in-expand 1.5s cubic-bezier(0.250, 0.460, 0.450, 0.940) both;
        font-size: 1.8rem;
        font-weight: 600;
        color: #FAFAFA;
        margin-bottom: 1.5rem;
        text-align: center;
    }
    @keyframes floatCardAnim {
        0%   { transform: translateY(0px); box-shadow: 0 8px 16px rgba(0,0,0,0.5); }
        50%  { transform: translateY(-8px); box-shadow: 0 16px 24px rgba(0,0,0,0.4); }
        100% { transform: translateY(0px); box-shadow: 0 8px 16px rgba(0,0,0,0.5); }
    }
    .wooden-card {
        background: linear-gradient(135deg, #1A1A1A 0%, #111111 100%);
        border: 1px solid rgba(57, 255, 20, 0.4);
        border-radius: 8px;
        padding: 1.5rem;
        color: #FAFAFA;
        height: 240px;
        display: flex;
        flex-direction: column;
        animation: floatCardAnim 5s ease-in-out infinite;
        box-shadow: 0 4px 15px rgba(57, 255, 20, 0.05);
    }
    .float-delay-1 { animation-delay: 0s; }
    .float-delay-2 { animation-delay: 1s; }
    .float-delay-3 { animation-delay: 2s; }
    .wooden-card h4 {
        color: #39FF14 !important;
        border-bottom: 1px solid rgba(57, 255, 20, 0.2);
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
        margin-top: 0;
        text-shadow: 0 1px 2px rgba(0,0,0,0.8);
    }
    .wooden-card .panel-label {
        font-size: 0.95rem;
        font-weight: 500;
        color: #D4D4D8;
        line-height: 1.5;
        text-shadow: 0 1px 1px rgba(0,0,0,0.5);
    }
    </style>
    <div class="track-animation" style="margin-bottom: 3rem;">Operational Pipeline</div>
    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 2rem; max-width: 1100px; margin: 0 auto;">
        <div class="wooden-card float-delay-1">
            <h4>1. RAG Extractor</h4>
            <div class="panel-label">Extracts regulatory knowledge securely from mandated guidelines securely cached in FAISS.</div>
        </div>
        <div class="wooden-card float-delay-2">
            <h4>2. Transaction Validation</h4>
            <div class="panel-label">Applies deterministic rule enforcement and evaluates sanctions checks.</div>
        </div>
        <div class="wooden-card float-delay-3">
            <h4>3. Executive Decision</h4>
            <div class="panel-label">Produces a final compliance verdict with an immutable, signed ledger entry.</div>
        </div>
    </div>
    <br>
    """, unsafe_allow_html=True)

    st.markdown("""
    <style>
    .mindmap-container {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 3rem;
        padding: 1rem 0;
        margin-bottom: 2rem;
    }
    .mindmap-col {
        display: flex;
        flex-direction: column;
        gap: 1.5rem;
        flex: 1;
    }
    .mindmap-col.left { align-items: flex-end; }
    .mindmap-col.right { align-items: flex-start; }
    
    .mindmap-center {
        flex: 0 0 130px;
        height: 130px;
        background: #050505;
        border: 2px solid #39FF14;
        border-radius: 50%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 1.1rem;
        color: #39FF14;
        box-shadow: 0 0 30px rgba(57, 255, 20,0.15);
        position: relative;
        z-index: 2;
        text-align: center;
        line-height: 1.2;
    }
    .mindmap-node {
        background: #090909;
        border: 1px solid rgba(255,255,255,0.05);
        padding: 1.2rem 1.5rem;
        border-radius: 8px;
        position: relative;
        font-size: 0.95rem;
        color: #A1A1AA;
        width: 100%;
        max-width: 320px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0,0,0,0.2);
    }
    .mindmap-node:hover {
        color: #FAFAFA;
        border-color: #39FF14;
        transform: scale(1.02);
    }
    .mindmap-col.left .mindmap-node { text-align: right; }
    .mindmap-col.left .mindmap-node::after {
        content: ''; position: absolute; right: -3rem; top: 50%; width: 3rem; height: 2px;
        background: rgba(255,255,255,0.1); z-index: -1; transition: background 0.3s;
    }
    .mindmap-col.right .mindmap-node::after {
        content: ''; position: absolute; left: -3rem; top: 50%; width: 3rem; height: 2px;
        background: rgba(255,255,255,0.1); z-index: -1; transition: background 0.3s;
    }
    .mindmap-node:hover::after {
        background: rgba(57, 255, 20,0.5) !important;
    }
    
    @keyframes textShimmer {
        to { background-position: -200% center; }
    }
    @keyframes slideUpReveal {
        0% { transform: translateY(30px) scale(0.9); opacity: 0; filter: blur(10px); }
        100% { transform: translateY(0) scale(1); opacity: 1; filter: blur(0px); }
    }
    .typo-anim {
        text-align: center;
        font-size: 2rem;
        font-weight: 800;
        margin-bottom: 2.5rem;
        text-transform: uppercase;
        letter-spacing: 2px;
        background: linear-gradient(110deg, #FAFAFA 30%, #39FF14 50%, #FAFAFA 70%);
        background-size: 200% auto;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: slideUpReveal 1.2s cubic-bezier(0.16, 1, 0.3, 1) forwards, textShimmer 4s linear infinite 1.2s;
    }
    </style>
    
    <h2 class='typo-anim'>Core Architecture Capabilities</h2>
    
    <div class="mindmap-container">
        <div class="mindmap-col left">
            <div class="mindmap-node">Dual-policy evaluation models</div>
            <div class="mindmap-node">Hybrid AI & deterministic rule execution</div>
            <div class="mindmap-node">Multi-agent pipeline reconciliation</div>
        </div>
        <div class="mindmap-center">
            <span>Core</span><br><span>Engine</span>
        </div>
        <div class="mindmap-col right">
            <div class="mindmap-node">Immutable ledger generation</div>
            <div class="mindmap-node">Real-time risk diagnostics</div>
            <div class="mindmap-node">Fully auditable AI explanations</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    st.info("System Ready. Please authenticate and use the sidebar to proceed to the Operational Dashboard.")

    st.markdown("""
    <style>
    .custom-footer {
        border-top: 1px solid rgba(255, 255, 255, 0.05);
        padding: 2.5rem 0 1rem 0;
        margin-top: 4rem;
        text-align: center;
        color: #A1A1AA;
        font-size: 0.85rem;
    }
    .custom-footer a {
        color: #39FF14;
        text-decoration: none;
        margin: 0 10px;
        transition: color 0.2s;
        font-weight: 500;
    }
    .custom-footer a:hover {
        color: #FAFAFA;
    }
    </style>
    <div class="custom-footer">
        <p>&copy; 2026 ComplianceLoop System. All rights reserved.</p>
        <p style="margin-top: 0.5rem;">
            <a href="#">Privacy Policy</a> | 
            <a href="#">Terms of Service</a> | 
            <a href="#">Regulatory Governance</a>
        </p>
    </div>
    """, unsafe_allow_html=True)