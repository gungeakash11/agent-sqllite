import streamlit as st
import requests
import time
import uuid
import datetime

# Setup page config
st.set_page_config(
    page_title="VDD Multi-Agent Assistant Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium CSS styling
st.markdown("""
<style>
    /* Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
    
    /* Global Overrides */
    * {
        font-family: 'Outfit', sans-serif;
    }
    h1, h2, h3, h4 {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    
    /* Header styling */
    .header-container {
        padding: 20px 0px;
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        border-radius: 12px;
        color: white;
        text-align: center;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .header-title {
        font-size: 2.2rem;
        margin: 0;
        font-weight: 700;
    }
    .header-subtitle {
        font-size: 1.1rem;
        opacity: 0.9;
        margin-top: 5px;
    }
    
    /* Premium Cards */
    .agent-card {
        background: #fdfdfd;
        border: 1px solid #eef2f6;
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.03);
        transition: all 0.3s ease;
        margin-bottom: 15px;
    }
    .agent-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.06);
    }
    
    /* Agent status colors */
    .status-badge {
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .status-running {
        background-color: #e3f2fd;
        color: #0d47a1;
        border: 1px solid #bbdefb;
    }
    .status-completed {
        background-color: #e8f5e9;
        color: #1b5e20;
        border: 1px solid #c8e6c9;
    }
    .status-failed {
        background-color: #ffebee;
        color: #c62828;
        border: 1px solid #ffcdd2;
    }
    .status-pending {
        background-color: #f5f5f5;
        color: #616161;
        border: 1px solid #e0e0e0;
    }
    
    /* Finding categories */
    .finding-risk {
        border-left: 5px solid #d32f2f;
        background-color: #fff9f9;
        padding: 12px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 10px;
    }
    .finding-gap {
        border-left: 5px solid #f57c00;
        background-color: #fffbf5;
        padding: 12px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 10px;
    }
    .finding-contradiction {
        border-left: 5px solid #7b1fa2;
        background-color: #faf5ff;
        padding: 12px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# Initialization of Session States
if "api_url" not in st.session_state:
    st.session_state.api_url = "http://localhost:8000"
if "token" not in st.session_state:
    st.session_state.token = None
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "selected_review_id" not in st.session_state:
    st.session_state.selected_review_id = None
if "qa_chat_history" not in st.session_state:
    st.session_state.qa_chat_history = []

def get_headers():
    headers = {}
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    return headers

# ── Sidebar Authentication and Controls ──────────────────────────────────────
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/8649/8649607.png", width=70)
    st.markdown("### VDD Agent Controller")
    
    # Connection Check / Settings
    st.session_state.api_url = st.text_input("Backend API URL", st.session_state.api_url)
    
    # Login / Status Info
    if not st.session_state.token:
        st.markdown("---")
        st.markdown("#### Reviewer Login")
        login_tab, signup_tab = st.tabs(["Login", "Sign Up"])
        
        with login_tab:
            email = st.text_input("Email", "prisonershaggy@gmail.com", key="login_email")
            password = st.text_input("Password", "postgresql", type="password", key="login_pass")
            if st.button("Authenticate", use_container_width=True):
                try:
                    res = requests.post(
                        f"{st.session_state.api_url}/api/v1/auth/login",
                        data={"username": email, "password": password}
                    )
                    if res.status_code == 200:
                        data = res.json()
                        st.session_state.token = data["access_token"]
                        
                        # Get user details
                        user_res = requests.get(
                            f"{st.session_state.api_url}/api/v1/auth/me",
                            headers={"Authorization": f"Bearer {st.session_state.token}"}
                        )
                        if user_res.status_code == 200:
                            st.session_state.current_user = user_res.json()
                        
                        st.success("Successfully logged in!")
                        st.rerun()
                    else:
                        st.error(f"Login failed: {res.json().get('detail', 'Unknown error')}")
                except Exception as e:
                    st.error(f"Connection error: {e}")
                    
        with signup_tab:
            new_email = st.text_input("Email", "new_reviewer@test.com", key="signup_email")
            new_name = st.text_input("Full Name", "New Reviewer", key="signup_name")
            new_password = st.text_input("Password", "TestPass123!", type="password", key="signup_pass")
            if st.button("Sign Up", use_container_width=True):
                try:
                    res = requests.post(
                        f"{st.session_state.api_url}/api/v1/auth/signup",
                        json={"email": new_email, "full_name": new_name, "password": new_password}
                    )
                    if res.status_code == 200:
                        st.success("Account created! You can now log in.")
                    else:
                        st.error(f"Signup failed: {res.json().get('detail', 'Unknown error')}")
                except Exception as e:
                    st.error(f"Connection error: {e}")
    else:
        # Authenticated UI
        user = st.session_state.current_user or {}
        st.markdown(f"**User**: {user.get('full_name', 'Reviewer')} ({user.get('role', 'USER')})")
        if st.button("Log Out", use_container_width=True):
            st.session_state.token = None
            st.session_state.current_user = None
            st.session_state.selected_review_id = None
            st.session_state.qa_chat_history = []
            st.rerun()

        st.markdown("---")
        st.markdown("### Active Review Jobs")
        
        # Load reviews list
        try:
            res = requests.get(
                f"{st.session_state.api_url}/api/v1/reviews",
                headers=get_headers()
            )
            if res.status_code == 200:
                reviews = res.json()
                if reviews:
                    review_opts = {f"{r['vendor_name']} ({r['status'].upper()})": r['id'] for r in reviews}
                    selected_opt = st.selectbox(
                        "Switch Review Job",
                        options=list(review_opts.keys()),
                        index=0 if st.session_state.selected_review_id not in review_opts.values() else list(review_opts.values()).index(st.session_state.selected_review_id)
                    )
                    st.session_state.selected_review_id = review_opts[selected_opt]
                else:
                    st.info("No reviews found. Create a new one below.")
                    st.session_state.selected_review_id = None
            else:
                st.error("Failed to load reviews list")
        except Exception as e:
            st.error(f"Could not connect: {e}")

# ── Main Content Area ────────────────────────────────────────────────────────
st.markdown("""
<div class="header-container">
    <div class="header-title">🤖 Vendor Due Diligence Assistant</div>
    <div class="header-subtitle">Multi-Agent Review Pipeline & Interactive Orchestration Panel</div>
</div>
""", unsafe_allow_html=True)

if not st.session_state.token:
    st.warning("👈 Please authenticate in the sidebar to access the Due Diligence assistant.")
    st.stop()

# Layout tabs: Active Job View vs New Job Initiation
view_tab, create_tab = st.tabs(["🔍 Active Review Job", "🚀 Start New Review"])

# ── CREATE TAB ───────────────────────────────────────────────────────────────
with create_tab:
    st.markdown("### Launch a New Vendor Assessment")
    with st.form("create_review_form"):
        vendor_name = st.text_input("Vendor Name", placeholder="e.g., Acme Cloud Corp")
        review_context = st.text_area("Review Context / Objective", placeholder="Due diligence for high-risk vendor storage solution.")
        
        col1, col2 = st.columns(2)
        with col1:
            analysis_depth = st.selectbox("Analysis Depth", ["quick", "standard", "deep"], index=1)
        with col2:
            focus_areas = st.multiselect(
                "Focus Areas (Agent Scope)",
                options=["mfa", "encryption", "retention", "disaster_recovery", "soc_checks"],
                default=["mfa", "encryption", "retention"]
            )
            
        uploaded_files = st.file_uploader(
            "Upload Vendor Materials (Questionnaires, DPA, SOC, etc.)", 
            accept_multiple_files=True, 
            type=["txt", "pdf", "docx"]
        )
        
        submit_btn = st.form_submit_button("Initiate Assessment Pipeline")
        
        if submit_btn:
            if not vendor_name:
                st.error("Vendor Name is required.")
            elif not uploaded_files:
                st.error("At least one document is required for analysis.")
            else:
                with st.spinner("Creating review job..."):
                    try:
                        # 1. Create Job
                        create_res = requests.post(
                            f"{st.session_state.api_url}/api/v1/reviews",
                            json={
                                "vendor_name": vendor_name,
                                "review_context": review_context,
                                "analysis_depth": analysis_depth,
                                "enabled_checks": focus_areas
                            },
                            headers=get_headers()
                        )
                        if create_res.status_code == 201:
                            new_job = create_res.json()
                            job_id = new_job["id"]
                            st.session_state.selected_review_id = job_id
                            
                            # 2. Upload Documents
                            files_payload = []
                            for file in uploaded_files:
                                files_payload.append(
                                    ("files", (file.name, file.getvalue(), file.type))
                                )
                            
                            upload_res = requests.post(
                                f"{st.session_state.api_url}/api/v1/reviews/{job_id}/documents",
                                files=files_payload,
                                headers=get_headers()
                            )
                            
                            if upload_res.status_code == 201:
                                upload_summary = upload_res.json()
                                st.success(f"Review created successfully! Preprocessing kicked off for {len(upload_summary['accepted'])} files.")
                                st.rerun()
                            else:
                                st.error("Failed to upload documents.")
                        else:
                            st.error(f"Failed to create review: {create_res.json().get('detail', 'Unknown error')}")
                    except Exception as e:
                        st.error(f"Error starting review: {e}")

# ── VIEW TAB ─────────────────────────────────────────────────────────────────
with view_tab:
    if not st.session_state.selected_review_id:
        st.info("No active review job selected. Please create one or switch in the sidebar.")
    else:
        # Fetch detailed active job state
        review_id = st.session_state.selected_review_id
        try:
            res = requests.get(f"{st.session_state.api_url}/api/v1/reviews/{review_id}", headers=get_headers())
            progress_res = requests.get(f"{st.session_state.api_url}/api/v1/reviews/{review_id}/progress", headers=get_headers())
            runs_res = requests.get(f"{st.session_state.api_url}/api/v1/reviews/{review_id}/runs", headers=get_headers())
            findings_res = requests.get(f"{st.session_state.api_url}/api/v1/reviews/{review_id}/findings", headers=get_headers())
            
            if res.status_code == 200:
                job = res.json()
                prog_data = progress_res.json() if progress_res.status_code == 200 else {}
                runs_list = runs_res.json() if runs_res.status_code == 200 else []
                findings_list = findings_res.json() if findings_res.status_code == 200 else []
                
                # Active Job Layout
                col_left, col_right = st.columns([2, 1])
                
                with col_left:
                    # Job Summary Title
                    st.markdown(f"## Vendor: **{job['vendor_name']}**")
                    st.caption(f"ID: `{job['id']}` | Started: {job['created_at'][:19].replace('T', ' ')}")
                    
                    # Status Summary Banner
                    status = job["status"].upper()
                    status_col, stage_col, pct_col = st.columns([1, 2, 1])
                    with status_col:
                        st.markdown(f"**Status:**")
                        if status == "PREPROCESSING":
                            st.markdown("🟡 **PREPROCESSING**")
                        elif status == "ANALYZING":
                            st.markdown("🔵 **ANALYZING**")
                        elif status == "PAUSED":
                            st.markdown("🟠 **PAUSED**")
                        elif status == "COMPLETED":
                            st.markdown("🟢 **COMPLETED**")
                        else:
                            st.markdown("🔴 **FAILED**")
                    with stage_col:
                        st.markdown(f"**Current Stage:**\n`{job.get('current_stage') or 'Idle'}`")
                    with pct_col:
                        st.markdown(f"**Progress:**\n`{job.get('progress_pct', 0)}%`")
                    st.progress(job.get("progress_pct", 0) / 100.0)
                    
                    st.markdown("---")
                    
                    # ── Live Preprocessing / Analysis Timeline ──────────────────────
                    st.markdown("### Agent Orchestration Flow (LangGraph)")
                    
                    # Defined Agent Pipeline Sequence
                    agents_sequence = ["classifier", "retrieval", "risk_review", "gap_detection", "contradiction", "summary"]
                    
                    # Build visual nodes map
                    agent_cols = st.columns(len(agents_sequence))
                    
                    # Create lookup dict of runs
                    runs_map = {r["agent_name"].lower(): r for r in runs_list}
                    
                    current_node = job.get("current_node")
                    
                    for idx, agent in enumerate(agents_sequence):
                        with agent_cols[idx]:
                            run_info = runs_map.get(agent)
                            a_title = agent.replace('_', ' ').title()
                            
                            # Determine visual style
                            if status == "FAILED" and current_node == agent:
                                a_status = "FAILED"
                                css_class = "status-failed"
                            elif status == "PAUSED" and current_node == agent:
                                a_status = "PAUSED"
                                css_class = "status-running"
                            elif run_info and run_info["status"] == "completed":
                                a_status = "COMPLETED"
                                css_class = "status-completed"
                            elif run_info and run_info["status"] == "running":
                                a_status = "RUNNING"
                                css_class = "status-running"
                            elif current_node == agent and status == "ANALYZING":
                                a_status = "RUNNING"
                                css_class = "status-running"
                            else:
                                a_status = "PENDING"
                                css_class = "status-pending"
                                
                            st.markdown(f"""
                            <div class="agent-card">
                                <div style="font-weight:600; font-size:0.95rem; margin-bottom:8px;">{a_title}</div>
                                <span class="status-badge {css_class}">{a_status.lower()}</span>
                                <div style="font-size:0.8rem; margin-top:8px; color:#555;">
                                    Tokens: {run_info['tokens_used'] if run_info else 0}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                    st.markdown("---")
                    
                    # ── Control Panel (Milestone 5) ───────────────────────────────
                    st.markdown("### Interactive Control Panel")
                    control_col1, control_col2, control_col3 = st.columns(3)
                    
                    with control_col1:
                        if status == "ANALYZING":
                            if st.button("⏸️ Pause Analysis", use_container_width=True, type="secondary"):
                                requests.post(f"{st.session_state.api_url}/api/v1/reviews/{review_id}/pause", headers=get_headers())
                                st.rerun()
                        elif status == "PAUSED":
                            if st.button("▶️ Resume Analysis", use_container_width=True, type="primary"):
                                requests.post(f"{st.session_state.api_url}/api/v1/reviews/{review_id}/resume", headers=get_headers())
                                st.rerun()
                        elif status in ("COMPLETED", "FAILED", "READY"):
                            if st.button("🚀 Run Agent Analysis", use_container_width=True, type="primary"):
                                requests.post(f"{st.session_state.api_url}/api/v1/reviews/{review_id}/analyze", headers=get_headers())
                                st.rerun()
                                
                    with control_col2:
                        # Preprocessing Wait state helper
                        if status == "PREPROCESSING":
                            st.info("Ingesting uploaded files. Waiting to finish...")
                            if st.button("🔄 Refresh Preprocessing", use_container_width=True):
                                st.rerun()
                        else:
                            st.caption("Press Refresh to fetch latest agent executions")
                            if st.button("🔄 Refresh Data", use_container_width=True):
                                st.rerun()
                                
                    # Custom Instructions Injector
                    st.markdown("#### Mid-Review Guidance / Custom Instructions")
                    custom_instr = st.text_area(
                        "Inject specific constraints, rules, or guidance for the agents:",
                        value=job.get("custom_instructions") or "",
                        placeholder="e.g. Verify if backup processes are fully automated or require manual admin action.",
                        key="custom_instructions_field"
                    )
                    
                    if st.button("Update Custom Instructions", use_container_width=True):
                        inst_res = requests.post(
                            f"{st.session_state.api_url}/api/v1/reviews/{review_id}/instructions",
                            json={"custom_instructions": custom_instr},
                            headers=get_headers()
                        )
                        if inst_res.status_code == 200:
                            st.success("Instructions updated! Agents will incorporate this instruction on execution.")
                            st.rerun()
                        else:
                            st.error("Failed to update instructions.")

                    st.markdown("---")
                    
                    # ── Findings Summary Report ───────────────────────────────────
                    st.markdown("### Findings & Assessment Summary")
                    if findings_list:
                        risks = [f for f in findings_list if f["finding_type"] == "risk"]
                        gaps = [f for f in findings_list if f["finding_type"] == "gap"]
                        contras = [f for f in findings_list if f["finding_type"] == "contradiction"]
                        
                        finding_tabs = st.tabs([
                            f"Risks ({len(risks)})", 
                            f"Gaps / Missing Info ({len(gaps)})", 
                            f"Contradictions ({len(contras)})"
                        ])
                        
                        with finding_tabs[0]:
                            if risks:
                                for r in risks:
                                    st.markdown(f"""
                                    <div class="finding-risk">
                                        <strong>Risk Profile:</strong> {r['description']}<br/>
                                        <small style='color:gray;'>Confidence: {r['confidence']*100:.0f}%</small>
                                    </div>
                                    """, unsafe_allow_html=True)
                            else:
                                st.info("No security risks identified so far.")
                                
                        with finding_tabs[1]:
                            if gaps:
                                for g in gaps:
                                    st.markdown(f"""
                                    <div class="finding-gap">
                                        <strong>Coverage Gap:</strong> {g['description']}<br/>
                                        <small style='color:gray;'>Confidence: {g['confidence']*100:.0f}%</small>
                                    </div>
                                    """, unsafe_allow_html=True)
                            else:
                                st.info("No missing evidence or gaps identified.")
                                
                        with finding_tabs[2]:
                            if contras:
                                for c in contras:
                                    st.markdown(f"""
                                    <div class="finding-contradiction">
                                        <strong>Document Conflict:</strong> {c['description']}<br/>
                                        <small style='color:gray;'>Confidence: {c['confidence']*100:.0f}%</small>
                                    </div>
                                    """, unsafe_allow_html=True)
                            else:
                                st.info("No logical contradictions detected.")
                    else:
                        st.info("No findings generated yet. Run the agent pipeline to populate findings.")
                        
                with col_right:
                    # ── Side Panel Q&A Deck ────────────────────────────────────────
                    st.markdown("### Interactive In-Flight Q&A")
                    st.caption("Ask questions about findings, policies, and files.")
                    
                    if status != "PAUSED" and status != "COMPLETED":
                        st.info("ℹ️ Q&A panel is active when the analysis is PAUSED or COMPLETED.")
                        
                    # Chat Q&A Input Box
                    qa_question = st.text_input("Ask a question about the vendor materials:")
                    if st.button("Submit Question", use_container_width=True, disabled=(status not in ("PAUSED", "COMPLETED"))):
                        if qa_question:
                            with st.spinner("Sifting through documents..."):
                                ask_res = requests.post(
                                    f"{st.session_state.api_url}/api/v1/reviews/{review_id}/ask",
                                    json={"question": qa_question},
                                    headers=get_headers()
                                )
                                if ask_res.status_code == 200:
                                    qa_data = ask_res.json()
                                    st.session_state.qa_chat_history.insert(0, {
                                        "q": qa_question,
                                        "a": qa_data["answer"],
                                        "cites": [c["description"] for c in qa_data.get("cited_findings", [])]
                                    })
                                else:
                                    st.error("Failed to fetch grounded answer.")
                                    
                    # Render Chat History
                    if st.session_state.qa_chat_history:
                        st.markdown("#### QA History")
                        for item in st.session_state.qa_chat_history:
                            with st.expander(f"Q: {item['q']}", expanded=True):
                                st.markdown(f"**A:** {item['a']}")
                                if item["cites"]:
                                    st.markdown("**Cited Context:**")
                                    for cite in item["cites"][:3]:
                                        st.caption(f"- {cite}")
                                        
                    st.markdown("---")
                    
                    # Documents and Logs Info
                    st.markdown("### Ingested Documents")
                    try:
                        docs_res = requests.get(f"{st.session_state.api_url}/api/v1/reviews/{review_id}/documents", headers=get_headers())
                        if docs_res.status_code == 200:
                            docs = docs_res.json()
                            for d in docs:
                                status_emoji = "✅" if d["status"] == "INGESTED" else "⏳"
                                st.markdown(f"{status_emoji} **{d['original_filename']}**")
                                st.caption(f"Type: `{d.get('document_type') or 'Unknown'}` | Size: {d['file_size_bytes']/1024:.1f} KB")
                        else:
                            st.error("Failed to load documents list")
                    except Exception as e:
                        st.error(f"Error loading docs: {e}")
                        
                    st.markdown("---")
                    
                    # Live Event Logs
                    st.markdown("### Activity Feed Logs")
                    if prog_data and prog_data.get("events"):
                        for event in reversed(prog_data["events"]):
                            ev_time = event["timestamp"][11:19]
                            st.caption(f"[{ev_time}] **{event['event_type'].upper()}**: {event['message']}")
                    else:
                        st.caption("No events logged yet.")
                        
            else:
                st.error("Could not fetch active review job details. Try switching selected job.")
        except Exception as e:
            st.error(f"Error rendering dashboard: {e}")
