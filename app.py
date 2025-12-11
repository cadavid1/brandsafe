import streamlit as st
import json
import pandas as pd
import time
from datetime import datetime
from pathlib import Path

# Import new modules
from config import (
    MODELS, DEFAULT_MODEL, get_model_list, get_model_info,
    estimate_cost, format_cost, DEFAULT_SYSTEM_PROMPT, DRIVE_ENABLED,
    ANALYSIS_TIERS, PLATFORM_CONFIGS, DEFAULT_TIME_RANGE_DAYS
)
from video_processor import (
    validate_and_process_video, delete_video_file,
    format_duration, ensure_video_directory
)
from gemini_client import GeminiClient, GeminiAPIError, call_gemini_text
from storage import get_db
from auth import get_auth
from logger import (log_video_upload, log_analysis_start,
                    log_analysis_complete, log_analysis_error, log_export)
from creator_analyzer import CreatorAnalyzer, CreatorAnalysisError
from report_generator import ReportGenerator
from platform_clients import get_platform_client, PlatformClientError
from web_scraper import detect_platform_from_url, extract_handle_from_url

# Google Drive integration (optional)
try:
    from drive_client import (
        DriveClient, DriveAPIError, is_drive_authenticated,
        get_drive_client, handle_drive_oauth_callback, logout_drive
    )
    DRIVE_AVAILABLE = DRIVE_ENABLED
except ImportError:
    DRIVE_AVAILABLE = False
    print("Google Drive integration not available. Install google-api-python-client to enable.")

# --- CONFIGURATION & STATE ---
st.set_page_config(page_title="BrandSafe - Talent Analysis", page_icon="🎯", layout="wide")

# Initialize authentication
auth = get_auth()

# IMPORTANT: Handle Drive OAuth callback BEFORE auth check
# This allows the callback to restore authentication from the state token
if DRIVE_AVAILABLE:
    handle_drive_oauth_callback()

# Require authentication - show login/register if not logged in
if not auth.require_auth():
    st.stop()  # Stop execution if not authenticated

# Get current user ID for data isolation
user_id = auth.get_current_user_id()

# Demo mode banner
if auth.is_demo_mode():
    demo_banner = st.container()
    with demo_banner:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.warning("🎭 **Demo Mode** - You're trying out the app! Your data will NOT be saved after this session ends.")
        with col2:
            if st.button("Create Account", type="primary", use_container_width=True):
                # Clear demo session and show registration
                auth.logout()
                st.rerun()

# Ensure data directories exist
ensure_video_directory()

# Initialize database
db = get_db()

# Initialize Session State
if "cujs" not in st.session_state:
    # Load from database (skip for demo users)
    if auth.is_demo_mode():
        loaded_cujs = pd.DataFrame()
    else:
        loaded_cujs = db.get_cujs(user_id)

    # Clean up any corrupt entries with None/empty IDs before loading
    if not loaded_cujs.empty:
        has_corrupt = False
        for _, row in loaded_cujs.iterrows():
            row_id = row['id']
            if pd.isna(row_id) or not str(row_id).strip():
                has_corrupt = True
                try:
                    # Delete corrupt entry from database
                    conn = db._get_connection()
                    cursor = conn.cursor()
                    if pd.isna(row_id):
                        cursor.execute("DELETE FROM cujs WHERE id IS NULL OR id = '' AND user_id = ?", (user_id,))
                    else:
                        cursor.execute("DELETE FROM cujs WHERE id = ? AND user_id = ?", (row_id, user_id))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"Could not delete corrupt entry during init: {e}")

        if has_corrupt:
            # Reload after cleanup
            loaded_cujs = db.get_cujs(user_id)

    if loaded_cujs.empty:
        # Start with empty dataframe - don't populate with sample data
        st.session_state.cujs = pd.DataFrame(columns=['id', 'task', 'expectation'])
    else:
        # Filter out any remaining corrupt entries before loading into session state
        clean_cujs = loaded_cujs[
            loaded_cujs['id'].notna() &
            (loaded_cujs['id'].astype(str).str.strip() != '')
        ].copy()
        st.session_state.cujs = clean_cujs

if "videos" not in st.session_state:
    # Load from database (skip for demo users)
    if auth.is_demo_mode():
        loaded_videos = pd.DataFrame()
    else:
        loaded_videos = db.get_videos(user_id)
    if loaded_videos.empty:
        # Start with empty dataframe - don't populate with sample data
        st.session_state.videos = pd.DataFrame(columns=['id', 'name', 'status', 'file_path', 'duration', 'size_mb', 'description'])
    else:
        st.session_state.videos = loaded_videos

if "results" not in st.session_state:
    # Load latest results from database (skip for demo users)
    if auth.is_demo_mode():
        st.session_state.results = {}
    else:
        st.session_state.results = db.get_latest_results(user_id)

if "api_key" not in st.session_state:
    # Load from database settings (skip for demo users)
    if auth.is_demo_mode():
        saved_key = ""
    else:
        saved_key = db.get_setting(user_id, "api_key", "")
    st.session_state.api_key = saved_key

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = DEFAULT_SYSTEM_PROMPT

if "selected_model" not in st.session_state:
    # Load from database settings (skip for demo users)
    if auth.is_demo_mode():
        saved_model = DEFAULT_MODEL
    else:
        # Check for custom default first, then fall back to DEFAULT_MODEL
        user_default = db.get_setting(user_id, "default_model", DEFAULT_MODEL)
        saved_model = db.get_setting(user_id, "selected_model", user_default)
    st.session_state.selected_model = saved_model

if "db_synced" not in st.session_state:
    st.session_state.db_synced = True

# --- HELPER FUNCTIONS ---

def get_confidence_indicator(score):
    """Generate monochrome confidence indicator based on score (1-5)

    Returns filled/empty circles to avoid color theory confusion with Pass/Fail status.
    High confidence (4-5): ●●●●● or ●●●●○
    Medium confidence (3): ●●●○○
    Low confidence (1-2): ●○○○○ or ●●○○○
    """
    filled = "●"
    empty = "○"

    if score >= 5:
        return f"{filled * 5}"
    elif score == 4:
        return f"{filled * 4}{empty}"
    elif score == 3:
        return f"{filled * 3}{empty * 2}"
    elif score == 2:
        return f"{filled * 2}{empty * 3}"
    else:  # score 1
        return f"{filled}{empty * 4}"

def get_friction_label(friction_score):
    """Generate descriptive friction label

    Makes friction scores immediately understandable:
    1-2: Smooth/Minimal friction
    3: Moderate friction
    4-5: High friction/Blocker
    """
    if friction_score <= 2:
        return "Smooth"
    elif friction_score == 3:
        return "Moderate"
    else:  # 4-5
        return "High"

def check_first_time_user():
    """Show welcome message for first-time users"""
    if 'welcome_shown' not in st.session_state:
        stats = db.get_statistics(user_id)
        is_first_time = (
            stats['total_analyses'] == 0 and
            not st.session_state.api_key
        )
        if is_first_time:
            st.info("""
            👋 **Welcome to UXR CUJ Analysis!**

            This tool uses AI to analyze user session videos against Critical User Journeys (CUJs).

            **Quick Start:**
            1. Add your Gemini API key in System Setup
            2. Define CUJs (test scenarios) or generate with AI
            3. Upload session recording videos
            4. Run analysis to evaluate each session

            💡 Follow the Workflow Progress tracker in the sidebar →
            """)
        st.session_state.welcome_shown = True

def render_progress_stepper():
    """Render workflow progress stepper in sidebar"""
    has_api_key = bool(st.session_state.api_key)
    has_cujs = not st.session_state.cujs.empty
    valid_videos = st.session_state.videos[
        st.session_state.videos.get('file_path', pd.Series(dtype='object')).notna() &
        (st.session_state.videos.get('status', pd.Series(dtype='str')).str.lower() == 'ready')
    ]
    has_videos = not valid_videos.empty
    has_results = bool(st.session_state.results)

    st.sidebar.markdown("### Workflow Progress")

    steps = [
        ("Setup", has_api_key, "Configure API key & model"),
        ("CUJs", has_cujs, "Define test scenarios"),
        ("Videos", has_videos, "Upload recordings"),
        ("Analyze", has_results, "Run AI analysis")
    ]

    for i, (label, is_complete, description) in enumerate(steps, 1):
        if is_complete:
            st.sidebar.success(f"**{i}. ✓ {label}**")
        else:
            st.sidebar.info(f"**{i}. ○ {label}**")
        st.sidebar.caption(f"   {description}")

    st.sidebar.markdown("---")

def call_gemini(api_key, model_name, prompt, system_instruction, response_mime_type="application/json"):
    """Legacy function for text-only Gemini calls (CUJ generation, reports, etc.)"""
    result = call_gemini_text(api_key, model_name, prompt, system_instruction, response_mime_type)

    if result and "error" in result:
        st.error(f"Gemini API Error: {result['error']}")
        return None

    if response_mime_type == "application/json":
        return result
    return result.get("text") if result else None

# --- SIDEBAR ---

st.sidebar.title("🎯 BrandSafe")
st.sidebar.markdown("Talent Analysis Tool")
st.sidebar.markdown("---")

# Show user info in sidebar
auth.show_user_info_sidebar()

# Workflow Progress Stepper
render_progress_stepper()

# Enhanced Status Indicators
st.sidebar.markdown("### System Status")

# API Key status
if st.session_state.api_key:
    st.sidebar.success("🔑 API Key: Connected")
else:
    st.sidebar.error("🔑 API Key: Not Set")
    st.sidebar.caption("   → Go to System Setup tab")

# CUJ status
cuj_count = len(st.session_state.cujs)
if cuj_count > 0:
    st.sidebar.success(f"📋 CUJs: {cuj_count} defined")
else:
    st.sidebar.warning("📋 CUJs: None defined")
    st.sidebar.caption("   → Go to Define CUJs tab")

# Video status
valid_video_count = len(st.session_state.videos[
    st.session_state.videos.get('file_path', pd.Series(dtype='object')).notna() &
    (st.session_state.videos.get('status', pd.Series(dtype='str')).str.lower() == 'ready')
])
if valid_video_count > 0:
    st.sidebar.success(f"📹 Videos: {valid_video_count} ready")
else:
    st.sidebar.warning("📹 Videos: None uploaded")
    st.sidebar.caption("   → Go to Upload Videos tab")

# Drive status
if DRIVE_AVAILABLE:
    st.sidebar.markdown("")
    if is_drive_authenticated():
        st.sidebar.info("📁 Drive: Connected")
        if st.sidebar.button("Logout from Drive", key="sidebar_logout"):
            logout_drive()
            st.rerun()
    else:
        st.sidebar.info("📁 Drive: Not connected")

st.sidebar.markdown("---")

# Keyboard Shortcuts & Tips
with st.sidebar.expander("⌨️ Shortcuts & Tips"):
    st.markdown("""
    **Navigation:**
    - Tab through fields with `Tab` key
    - Press `Enter` in forms to submit
    - Use `Esc` to close dialogs

    **Quick Tips:**
    - Check Workflow Progress above to see next steps
    - Green status = ready to proceed
    - Cost Estimator in Upload Videos tab
    - Low confidence results auto-expand for review

    **Getting Help:**
    - Hover over (?) icons for field help
    - Check empty states for guidance
    - Contact support if stuck
    """)

# --- MAIN CONTENT WITH HORIZONTAL TABS ---

# Show welcome message for first-time users
check_first_time_user()

tab_home, tab_setup, tab_briefs, tab_creators, tab_analysis, tab_reports = st.tabs([
    "🏠 Home",
    "⚙️ System Setup",
    "📄 Briefs",
    "👥 Creators",
    "🔍 Analysis",
    "📊 Reports"
])

# --- TAB: HOME/OVERVIEW ---

with tab_home:
    st.header("Welcome to BrandSafe Talent Analysis")

    # Quick stats overview
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        briefs_df = db.get_briefs(user_id)
        st.metric("📄 Briefs", len(briefs_df))
    with col2:
        creators_df = db.get_creators(user_id)
        st.metric("👥 Creators", len(creators_df))
    with col3:
        # Get total number of creator reports
        all_reports = []
        if not briefs_df.empty:
            for _, brief in briefs_df.iterrows():
                reports = db.get_reports_for_brief(brief['id'])
                all_reports.extend(reports.to_dict('records') if not reports.empty else [])
        st.metric("📊 Reports", len(all_reports))
    with col4:
        stats_home = db.get_statistics(user_id)
        st.metric("💰 Total Cost", format_cost(stats_home['total_cost']))

    st.markdown("---")

    # Two-column layout for overview
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("### 🚀 Quick Start Guide")
        st.markdown("""
        **1. System Setup**
        - Add your Gemini API key
        - Optional: Add YouTube API keys for multi-platform analysis

        **2. Create Brief**
        - Define campaign goals and brand context
        - Set target audience and values
        - Create the framework for talent evaluation

        **3. Add Creators**
        - Input social media URLs (YouTube, Instagram, TikTok, Twitch)
        - Auto-detect platforms and fetch profile stats
        - Add multiple accounts per creator

        **4. Run Analysis**
        - Choose analysis depth (Quick/Standard/Deep)
        - Configure time range for content analysis
        - Review brand fit scores and recommendations

        **5. View Reports**
        - Export professional reports (Markdown/HTML/PDF)
        - Review platform statistics and demographics
        - Share insights with stakeholders
        """)

        st.markdown("---")

        # System readiness check
        st.markdown("### ✅ System Readiness")
        if st.session_state.api_key:
            st.success("🔑 API Key configured")
        else:
            st.error("🔑 API Key missing - Go to System Setup")

        if len(briefs_df) > 0:
            st.success(f"📄 {len(briefs_df)} Brief(s) created")
        else:
            st.warning("📄 No Briefs - Go to Briefs tab")

        if len(creators_df) > 0:
            st.success(f"👥 {len(creators_df)} Creator(s) added")
        else:
            st.warning("👥 No Creators - Go to Creators tab")

    with col_right:
        st.markdown("### 📊 Recent Activity")

        # Show recent briefs and reports
        if not briefs_df.empty:
            recent_briefs = briefs_df.sort_values('created_at', ascending=False).head(3)
            for _, brief in recent_briefs.iterrows():
                st.caption(f"📄 **{brief['name']}**")
                # Get creators for this brief
                brief_creators = db.get_creators_for_brief(brief['id'])
                if not brief_creators.empty:
                    st.caption(f"   ↳ {len(brief_creators)} creator(s) linked")
                st.caption(f"   ↳ Created: {brief['created_at'][:10]}")
                st.markdown("")
        else:
            st.info("No briefs yet. Create your first brief!")

        st.markdown("---")

        # Key features highlight
        st.markdown("### ✨ Key Features")
        st.markdown("""
        - **Multi-Platform Analysis** - YouTube, Instagram, TikTok, Twitch
        - **Brand Fit Scoring** - AI-powered brand safety & alignment (1-10 scale)
        - **Flexible Analysis Tiers** - Quick (free), Standard, Deep analysis
        - **Professional Reports** - Export to Markdown, HTML, plain text
        - **Cost Optimization** - API key rotation, smart caching
        - **Account Discovery** - Auto-detect creator's alternate platforms
        - **Content Analysis** - Themes, sentiment, engagement quality
        """)

        if len(all_reports) > 0:
            st.markdown("---")
            st.markdown("### 📈 Analysis Summary")
            # Show average brand fit score across all reports
            avg_score = sum(r.get('overall_score', 0) for r in all_reports) / len(all_reports)
            st.caption(f"• **Average Brand Fit Score**: {avg_score:.1f}/10")
            st.caption(f"• **Total Creators Analyzed**: {len(all_reports)}")
            st.caption(f"• **Total Cost**: {format_cost(stats_home['total_cost'])}")

# --- TAB: SYSTEM SETUP ---

with tab_setup:
    st.header("System Setup")
    
    with st.expander("Gemini Configuration", expanded=True):
        new_api_key = st.text_input("Gemini API Key", value=st.session_state.api_key, type="password")

        # Save API key if changed
        if new_api_key != st.session_state.api_key:
            st.session_state.api_key = new_api_key
            if new_api_key and not auth.is_demo_mode():  # Only save non-empty keys for non-demo users
                db.save_setting(user_id, "api_key", new_api_key)

        # Get model list from config
        model_ids = get_model_list()
        model_display_names = [get_model_info(m)["display_name"] for m in model_ids]

        # Find current selection index
        try:
            current_index = model_ids.index(st.session_state.selected_model)
        except ValueError:
            current_index = 0
            st.session_state.selected_model = model_ids[0]

        selected_display = st.selectbox(
            "Select Model",
            model_display_names,
            index=current_index,
            help="Choose the Gemini model for analysis"
        )

        # Update session state with actual model ID
        selected_idx = model_display_names.index(selected_display)
        new_model = model_ids[selected_idx]

        # Save model if changed
        if new_model != st.session_state.selected_model:
            st.session_state.selected_model = new_model
            if not auth.is_demo_mode():
                db.save_setting(user_id, "selected_model", new_model)

        # Show model info
        model_info = get_model_info(st.session_state.selected_model)
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"**Best for:** {model_info['best_for']}")
        with col2:
            if model_info["cost_per_m_tokens_input"] > 0:
                st.caption(f"**Cost:** ${model_info['cost_per_m_tokens_input']:.2f} / ${model_info['cost_per_m_tokens_output']:.2f} per M tokens")
            else:
                st.caption("**Cost:** Free during preview")

        # Default model preference
        st.markdown("---")
        current_default = db.get_setting(user_id, "default_model", DEFAULT_MODEL)
        current_default_info = get_model_info(current_default)

        col1, col2 = st.columns([2, 1])
        with col1:
            st.caption(f"**Current Default:** {current_default_info['display_name']}")
        with col2:
            if st.session_state.selected_model != current_default:
                if st.button("Set as Default", key="set_default_btn"):
                    if not auth.is_demo_mode():
                        db.save_setting(user_id, "default_model", st.session_state.selected_model)
                    st.success(f"Default model updated to {model_info['display_name']}")
                    st.rerun()
            else:
                st.caption("✓ This is default")

    with st.expander("System Prompt", expanded=True):
        st.session_state.system_prompt = st.text_area(
            "Analysis Instruction",
            value=st.session_state.system_prompt,
            height=200
        )

    with st.expander("YouTube Configuration (Optional)", expanded=False):
        st.markdown("Add YouTube Data API v3 keys to enable creator analysis on YouTube.")
        st.caption("Get your API key from [Google Cloud Console](https://console.cloud.google.com/apis/credentials)")

        # Add new key section
        with st.form("add_youtube_key_form"):
            col1, col2 = st.columns([3, 1])
            with col1:
                new_yt_key = st.text_input("YouTube API Key", type="password", placeholder="AIzaSy...")
            with col2:
                key_name = st.text_input("Key Name", placeholder="Primary Key")

            if st.form_submit_button("Add API Key"):
                if new_yt_key and key_name:
                    key_id = db.save_youtube_api_key(user_id, new_yt_key, key_name)
                    if key_id > 0:
                        st.success(f"✅ Added YouTube API key: {key_name}")
                        st.rerun()
                    else:
                        st.error("Failed to save API key")
                else:
                    st.warning("Please provide both API key and name")

        # Display existing keys
        existing_keys = db.get_youtube_api_keys_with_info(user_id)

        if existing_keys:
            st.markdown("---")
            st.subheader("Configured Keys")

            for key in existing_keys:
                col1, col2, col3 = st.columns([2, 2, 1])
                with col1:
                    st.text(f"🔑 {key['key_name']}")
                with col2:
                    # Mask the API key
                    masked_key = key['api_key'][:10] + "..." + key['api_key'][-4:]
                    st.caption(f"`{masked_key}`")
                with col3:
                    if st.button("Delete", key=f"del_yt_key_{key['id']}"):
                        if db.delete_youtube_api_key(user_id, key['id']):
                            st.success(f"Deleted {key['key_name']}")
                            st.rerun()
                        else:
                            st.error("Failed to delete key")
        else:
            st.info("No YouTube API keys configured. Add one above to analyze YouTube creators.")

    # Google Drive OAuth
    if DRIVE_AVAILABLE:
        with st.expander("Google Drive Integration (Optional)", expanded=False):
            st.markdown("Connect to Google Drive to import videos and export results.")

            if is_drive_authenticated():
                st.success("✅ Connected to Google Drive")
                st.caption("You can now import videos from Drive and export results to Drive.")

                if st.button("Disconnect from Drive"):
                    logout_drive()
                    st.rerun()
            else:
                st.info("Sign in to access your Google Drive files")

                try:
                    # Pass user credentials to preserve authentication through OAuth redirect
                    _, auth_url = DriveClient.get_auth_url(
                        user_id=user_id,
                        username=auth.get_current_username()
                    )
                    st.markdown(f"### [🔐 Sign in with Google]({auth_url})")
                    st.caption("You'll be redirected to Google to authorize UXR CUJ Analysis")
                except Exception as e:
                    st.error(f"Drive configuration error: {e}")
                    st.caption("Make sure you've configured Drive OAuth in `.streamlit/secrets.toml`")

# --- TAB: BRIEFS ---

with tab_briefs:
    st.header("Campaign Briefs")
    st.caption("Create and manage campaign briefs to define your talent evaluation criteria")

    # Create new brief section
    with st.expander("➕ Create New Brief", expanded=False):
        with st.form("new_brief_form"):
            brief_name = st.text_input("Brief Name*", placeholder="Q1 2025 Brand Partnership Campaign")
            brief_description = st.text_area("Description", placeholder="Overview of campaign goals and requirements", height=100)
            brand_context = st.text_area(
                "Brand Context*",
                placeholder="Describe your brand values, target audience, campaign goals, and content guidelines...",
                height=200,
                help="This context will be used by AI to evaluate creator brand fit"
            )

            if st.form_submit_button("Create Brief", type="primary"):
                if not brief_name or not brand_context:
                    st.error("Please fill in Brief Name and Brand Context (required fields)")
                elif auth.is_demo_mode() and len(briefs_df) >= 1:
                    st.error("Demo mode limit: Maximum 1 brief. Create an account for unlimited access!")
                else:
                    # Save brief
                    brief_id = db.save_brief(
                        user_id=user_id,
                        name=brief_name,
                        description=brief_description,
                        brand_context=brand_context
                    )
                    st.success(f"✅ Brief created: {brief_name}")
                    time.sleep(1)
                    st.rerun()

    st.markdown("---")

    # List existing briefs
    briefs_df = db.get_briefs(user_id)
    if not briefs_df.empty:
        st.markdown(f"### Your Briefs ({len(briefs_df)})")

        for _, brief in briefs_df.iterrows():
            with st.expander(f"📄 {brief['name']}", expanded=False):
                col1, col2 = st.columns([3, 1])

                with col1:
                    st.markdown(f"**Description:** {brief.get('description', 'N/A')}")
                    st.markdown(f"**Brand Context:**")
                    st.caption(brief['brand_context'][:300] + "..." if len(brief['brand_context']) > 300 else brief['brand_context'])
                    st.caption(f"**Created:** {brief['created_at'][:10]}")

                    # Show linked creators
                    linked_creators = db.get_creators_for_brief(brief['id'])
                    if not linked_creators.empty:
                        st.markdown(f"**Linked Creators ({len(linked_creators)}):**")
                        for _, creator in linked_creators.iterrows():
                            st.caption(f"  • {creator['name']} ({creator['primary_platform']})")
                    else:
                        st.info("No creators linked yet. Add creators in the Creators tab.")

                with col2:
                    # Edit button
                    if st.button("Edit", key=f"edit_brief_{brief['id']}"):
                        st.session_state[f'editing_brief_{brief["id"]}'] = True
                        st.rerun()

                    # Delete button
                    if st.button("Delete", key=f"delete_brief_{brief['id']}", type="secondary"):
                        st.session_state[f'confirm_delete_brief_{brief["id"]}'] = True
                        st.rerun()

                # Edit form
                if st.session_state.get(f'editing_brief_{brief["id"]}', False):
                    st.markdown("---")
                    with st.form(f"edit_brief_form_{brief['id']}"):
                        new_name = st.text_input("Brief Name", value=brief['name'])
                        new_description = st.text_area("Description", value=brief.get('description', ''), height=100)
                        new_context = st.text_area("Brand Context", value=brief['brand_context'], height=200)

                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("Save Changes", type="primary"):
                                db.update_brief(brief['id'], name=new_name, description=new_description, brand_context=new_context)
                                st.session_state[f'editing_brief_{brief["id"]}'] = False
                                st.success("Brief updated!")
                                time.sleep(1)
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("Cancel"):
                                st.session_state[f'editing_brief_{brief["id"]}'] = False
                                st.rerun()

                # Delete confirmation
                if st.session_state.get(f'confirm_delete_brief_{brief["id"]}', False):
                    st.warning("⚠️ Delete this brief? All linked reports will also be deleted.")
                    col_no, col_yes = st.columns(2)
                    with col_no:
                        if st.button("Cancel", key=f"cancel_delete_{brief['id']}"):
                            st.session_state[f'confirm_delete_brief_{brief["id"]}'] = False
                            st.rerun()
                    with col_yes:
                        if st.button("Confirm Delete", key=f"confirm_delete_{brief['id']}", type="secondary"):
                            db.delete_brief(user_id, brief['id'])
                            st.session_state[f'confirm_delete_brief_{brief["id"]}'] = False
                            st.success("Brief deleted")
                            time.sleep(1)
                            st.rerun()
    else:
        st.info("""
        📄 **No briefs yet**

        Create your first brief to start evaluating creators. A brief defines:
        - Campaign objectives and goals
        - Brand values and guidelines
        - Target audience demographics
        - Content themes and requirements

        The AI uses this context to evaluate creator brand fit.
        """)

# --- TAB: CREATORS ---

with tab_creators:
    st.header("Creator Roster")
    st.caption("Add and manage social media creators for brand partnership evaluation")

    # Add creator section
    with st.expander("➕ Add Creator", expanded=False):
        with st.form("add_creator_form"):
            creator_name = st.text_input("Creator Name*", placeholder="Jane Doe")
            profile_url = st.text_input("Social Media URL*", placeholder="https://youtube.com/@creator")

            # Auto-detect platform
            detected_platform = None
            detected_handle = None
            if profile_url:
                detected_platform = detect_platform_from_url(profile_url)
                if detected_platform:
                    detected_handle = extract_handle_from_url(profile_url, detected_platform)
                    st.info(f"✓ Detected: {detected_platform.title()} - @{detected_handle}")
                else:
                    st.warning("Could not detect platform. Please enter a valid social media URL.")

            notes = st.text_area("Notes (optional)", placeholder="Additional information about this creator...")

            if st.form_submit_button("Add Creator", type="primary"):
                if not creator_name or not profile_url:
                    st.error("Please fill in Creator Name and Social Media URL")
                elif not detected_platform:
                    st.error("Invalid social media URL. Supported platforms: YouTube, Instagram, TikTok, Twitch")
                elif auth.is_demo_mode() and len(creators_df) >= 3:
                    st.error("Demo mode limit: Maximum 3 creators. Create an account for unlimited access!")
                else:
                    # Save creator
                    creator_id = db.save_creator(
                        user_id=user_id,
                        name=creator_name,
                        primary_platform=detected_platform,
                        notes=notes
                    )

                    # Save social account
                    db.save_social_account(
                        creator_id=creator_id,
                        platform=detected_platform,
                        profile_url=profile_url,
                        handle=detected_handle,
                        discovery_method="manual"
                    )

                    st.success(f"✅ Creator added: {creator_name}")
                    time.sleep(1)
                    st.rerun()

    st.markdown("---")

    # List existing creators
    creators_df = db.get_creators(user_id)
    if not creators_df.empty:
        st.markdown(f"### Your Creators ({len(creators_df)})")

        for _, creator in creators_df.iterrows():
            with st.expander(f"👤 {creator['name']} - {creator['primary_platform'].title()}", expanded=False):
                col1, col2 = st.columns([3, 1])

                with col1:
                    if creator.get('notes'):
                        st.markdown(f"**Notes:** {creator['notes']}")
                    st.caption(f"**Added:** {creator['created_at'][:10]}")

                    # Show social accounts
                    accounts_df = db.get_social_accounts(creator['id'])
                    if not accounts_df.empty:
                        st.markdown(f"**Social Accounts ({len(accounts_df)}):**")
                        for _, account in accounts_df.iterrows():
                            st.caption(f"  • {account['platform'].title()}: [{account.get('handle', 'N/A')}]({account['profile_url']})")
                            if account.get('last_fetched_at'):
                                st.caption(f"    Last fetched: {account['last_fetched_at'][:10]}")

                    # Link to briefs
                    st.markdown("**Link to Brief:**")
                    briefs_df_link = db.get_briefs(user_id)
                    if not briefs_df_link.empty:
                        selected_brief = st.selectbox(
                            "Select brief to link",
                            ["(Select a brief)"] + briefs_df_link['name'].tolist(),
                            key=f"link_brief_{creator['id']}"
                        )
                        if selected_brief != "(Select a brief)":
                            if st.button(f"Link to {selected_brief}", key=f"link_btn_{creator['id']}"):
                                brief_id = briefs_df_link[briefs_df_link['name'] == selected_brief].iloc[0]['id']
                                db.link_creator_to_brief(brief_id, creator['id'])
                                st.success(f"Linked {creator['name']} to {selected_brief}")
                                time.sleep(1)
                                st.rerun()
                    else:
                        st.caption("No briefs available. Create a brief first.")

                with col2:
                    # Delete button
                    if st.button("Delete", key=f"delete_creator_{creator['id']}", type="secondary"):
                        st.session_state[f'confirm_delete_creator_{creator["id"]}'] = True
                        st.rerun()

                # Delete confirmation
                if st.session_state.get(f'confirm_delete_creator_{creator["id"]}', False):
                    st.warning("⚠️ Delete this creator? All associated data will be removed.")
                    col_no, col_yes = st.columns(2)
                    with col_no:
                        if st.button("Cancel", key=f"cancel_delete_creator_{creator['id']}"):
                            st.session_state[f'confirm_delete_creator_{creator["id"]}'] = False
                            st.rerun()
                    with col_yes:
                        if st.button("Confirm Delete", key=f"confirm_delete_creator_{creator['id']}", type="secondary"):
                            db.delete_creator(user_id, creator['id'])
                            st.session_state[f'confirm_delete_creator_{creator["id"]}'] = False
                            st.success("Creator deleted")
                            time.sleep(1)
                            st.rerun()
    else:
        st.info("""
        👥 **No creators yet**

        Add your first creator to start analyzing talent. You can:
        - Add creators by entering their social media URLs
        - Platform is auto-detected (YouTube, Instagram, TikTok, Twitch)
        - Link creators to briefs for brand fit evaluation
        - Track multiple social accounts per creator
        """)

# --- TAB: ANALYSIS ---

with tab_analysis:
    st.header("Run Creator Analysis")
    st.caption("Analyze creators linked to a brief for brand fit evaluation")

    # Select brief
    briefs_df = db.get_briefs(user_id)

    if briefs_df.empty:
        st.info("""
        📄 **No briefs yet**

        Create a brief first in the Briefs tab, then link creators to it.
        """)
    else:
        selected_brief_name = st.selectbox(
            "Select Brief",
            briefs_df['name'].tolist(),
            key="analysis_brief_select"
        )

        if selected_brief_name:
            brief_row = briefs_df[briefs_df['name'] == selected_brief_name].iloc[0]
            brief_id = brief_row['id']

            # Get creators for this brief
            creators_in_brief = db.get_creators_for_brief(brief_id)

            if creators_in_brief.empty:
                st.warning("""
                👥 **No creators linked to this brief**

                Go to the Creators tab and link creators to this brief first.
                """)
            else:
                st.success(f"✓ {len(creators_in_brief)} creator(s) ready to analyze")

                # Analysis configuration
                st.markdown("### Analysis Configuration")

                col_config1, col_config2 = st.columns(2)

                with col_config1:
                    time_range = st.slider(
                        "Time Range (days)",
                        min_value=30,
                        max_value=730,
                        value=DEFAULT_TIME_RANGE_DAYS,
                        help="How far back to analyze posts"
                    )

                with col_config2:
                    analysis_depth = st.selectbox(
                        "Analysis Depth",
                        list(ANALYSIS_TIERS.keys()),
                        format_func=lambda x: f"{ANALYSIS_TIERS[x]['name']} - {ANALYSIS_TIERS[x]['description']}",
                        help="Choose analysis depth"
                    )

                # Show tier details
                tier_info = ANALYSIS_TIERS[analysis_depth]
                st.caption(f"**{tier_info['name']}**: {tier_info['description']}")

                # Cost estimate
                estimated_cost = len(creators_in_brief) * tier_info['estimated_cost_per_creator']
                st.info(f"💰 **Estimated Cost**: {format_cost(estimated_cost)} ({len(creators_in_brief)} creator(s) × {format_cost(tier_info['estimated_cost_per_creator'])} each)")

                st.markdown("---")

                # Creators preview
                with st.expander(f"👥 Creators to Analyze ({len(creators_in_brief)})", expanded=True):
                    for _, creator in creators_in_brief.iterrows():
                        accounts = db.get_social_accounts(creator['id'])
                        platforms = ', '.join(accounts['platform'].str.title().tolist()) if not accounts.empty else 'N/A'
                        st.caption(f"• **{creator['name']}** ({platforms})")

                st.markdown("---")

                # Run analysis button
                if st.button("🚀 Run Analysis", type="primary", use_container_width=True):
                    if not st.session_state.api_key:
                        st.error("⚠️ Gemini API Key required. Please configure in System Setup tab.")
                        st.stop()

                    # Check if we have YouTube creators and no API keys
                    has_youtube = False
                    for _, creator in creators_in_brief.iterrows():
                        accounts = db.get_social_accounts(creator['id'])
                        if not accounts.empty and 'youtube' in accounts['platform'].str.lower().values:
                            has_youtube = True
                            break

                    youtube_keys = db.get_youtube_api_keys(user_id)

                    if has_youtube and not youtube_keys:
                        st.error("⚠️ YouTube API keys required to analyze YouTube creators. Please add them in System Setup tab.")
                        st.stop()

                    # Initialize analyzer
                    try:
                        analyzer = CreatorAnalyzer(
                            gemini_api_key=st.session_state.api_key,
                            youtube_api_keys=youtube_keys
                        )

                        # Progress tracking
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        results_container = st.container()

                        total_creators = len(creators_in_brief)
                        successful_analyses = 0
                        failed_analyses = 0

                        for idx, creator in creators_in_brief.iterrows():
                            try:
                                status_text.text(f"Analyzing {creator['name']} ({idx + 1}/{total_creators})...")

                                # Progress callback
                                def update_progress(message, progress_fraction):
                                    overall_progress = (idx + progress_fraction) / total_creators
                                    progress_bar.progress(overall_progress)
                                    status_text.text(f"{message} - {creator['name']}")

                                # Run analysis
                                result = analyzer.analyze_creator(
                                    creator_id=creator['id'],
                                    brief_id=brief_id,
                                    time_range_days=time_range,
                                    analysis_depth=analysis_depth,
                                    progress_callback=update_progress
                                )

                                if result['success']:
                                    successful_analyses += 1
                                    with results_container:
                                        st.success(f"✅ {creator['name']}: Analysis complete (Score: {result['overall_metrics'].get('brand_fit_score', 'N/A')}/10)")
                                else:
                                    failed_analyses += 1
                                    with results_container:
                                        st.error(f"❌ {creator['name']}: Analysis failed")

                            except CreatorAnalysisError as e:
                                failed_analyses += 1
                                with results_container:
                                    st.error(f"❌ {creator['name']}: {str(e)}")
                            except Exception as e:
                                failed_analyses += 1
                                with results_container:
                                    st.error(f"❌ {creator['name']}: Unexpected error - {str(e)}")

                            # Update progress
                            progress_bar.progress((idx + 1) / total_creators)

                        # Final summary
                        progress_bar.progress(1.0)
                        status_text.text("✅ Analysis complete!")

                        st.markdown("---")
                        if failed_analyses == 0:
                            st.success(f"🎉 All {successful_analyses} analyses completed successfully!")
                        else:
                            st.warning(f"⚠️ Completed: {successful_analyses} succeeded, {failed_analyses} failed")

                        st.info("💡 View detailed reports in the Reports tab")
                        time.sleep(2)
                        st.rerun()

                    except Exception as e:
                        st.error(f"Failed to initialize analyzer: {str(e)}")

# --- TAB: REPORTS ---

with tab_reports:
    st.header("Analysis Reports")
    st.caption("View and export creator analysis reports")

    # Select brief
    briefs_df = db.get_briefs(user_id)

    if briefs_df.empty:
        st.info("""
        📄 **No briefs yet**

        Create a brief and run analysis first to see reports here.
        """)
    else:
        selected_brief_name = st.selectbox(
            "Select Brief",
            briefs_df['name'].tolist(),
            key="reports_brief_select"
        )

        if selected_brief_name:
            brief_row = briefs_df[briefs_df['name'] == selected_brief_name].iloc[0]
            brief_id = int(brief_row['id'])  # Convert numpy.int64 to Python int

            # Get reports for this brief
            reports_df = db.get_reports_for_brief(brief_id)

            if reports_df.empty:
                st.info("""
                📊 **No reports yet**

                Run an analysis in the Analysis tab to generate reports.
                """)
            else:
                st.success(f"✓ {len(reports_df)} report(s) available")

                # Sort by overall score (descending)
                reports_df = reports_df.sort_values('overall_score', ascending=False)

                # Export complete brief report button
                st.markdown("### 📥 Export Complete Brief Report")
                st.caption(f"Download a comprehensive report including all {len(reports_df)} creator(s) with executive summary and comparison table")

                col1, col2, col3 = st.columns(3)

                # Markdown Export
                with col1:
                    if st.button("📄 Markdown", key="export_brief_md", use_container_width=True):
                        try:
                            from report_generator import ReportGenerator
                            gen = ReportGenerator()
                            report_content = gen.generate_brief_report(brief_id, format="markdown")

                            brief_name_clean = selected_brief_name.replace(' ', '_')
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"brief_report_{brief_name_clean}_{timestamp}.md"

                            st.download_button(
                                label="⬇️ Download MD",
                                data=report_content,
                                file_name=filename,
                                mime="text/markdown",
                                key="download_brief_md_final",
                                use_container_width=True
                            )

                        except Exception as e:
                            st.error(f"Failed to generate Markdown: {str(e)}")

                # PDF Export
                with col2:
                    if st.button("📕 PDF", key="export_brief_pdf", use_container_width=True):
                        try:
                            # Force reload to pick up new dependencies
                            import sys
                            import importlib
                            if 'report_generator' in sys.modules:
                                importlib.reload(sys.modules['report_generator'])

                            from report_generator import ReportGenerator
                            gen = ReportGenerator()

                            with st.spinner("Generating PDF..."):
                                pdf_content = gen.generate_brief_report_pdf(brief_id)

                            if pdf_content:
                                brief_name_clean = selected_brief_name.replace(' ', '_')
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                filename = f"brief_report_{brief_name_clean}_{timestamp}.pdf"

                                st.download_button(
                                    label="⬇️ Download PDF",
                                    data=pdf_content,
                                    file_name=filename,
                                    mime="application/pdf",
                                    key="download_brief_pdf_final",
                                    use_container_width=True
                                )
                            else:
                                st.error("Failed to generate PDF")

                        except Exception as e:
                            import traceback
                            st.error(f"Failed to generate PDF: {str(e)}")
                            print(f"[ERROR] PDF Export failed:\n{traceback.format_exc()}")

                # Excel Export
                with col3:
                    if st.button("📊 Excel", key="export_brief_excel", use_container_width=True):
                        try:
                            # Force reload to pick up new dependencies
                            import sys
                            import importlib
                            if 'report_generator' in sys.modules:
                                importlib.reload(sys.modules['report_generator'])

                            from report_generator import ReportGenerator
                            gen = ReportGenerator()

                            with st.spinner("Generating Excel..."):
                                excel_content = gen.generate_brief_report_excel(brief_id)

                            if excel_content:
                                brief_name_clean = selected_brief_name.replace(' ', '_')
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                filename = f"brief_report_{brief_name_clean}_{timestamp}.xlsx"

                                st.download_button(
                                    label="⬇️ Download Excel",
                                    data=excel_content,
                                    file_name=filename,
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="download_brief_excel_final",
                                    use_container_width=True
                                )
                            else:
                                st.error("Failed to generate Excel")

                        except Exception as e:
                            import traceback
                            st.error(f"Failed to generate Excel: {str(e)}")
                            print(f"[ERROR] Excel Export failed:\n{traceback.format_exc()}")

                st.markdown("---")

                # Display reports
                for _, report_row in reports_df.iterrows():
                    score = report_row['overall_score']

                    # Score indicator (1-5 scale)
                    if score >= 4.0:
                        score_emoji = "🟢"
                        score_label = "Strong Fit"
                    elif score >= 3.0:
                        score_emoji = "🟡"
                        score_label = "Moderate Fit"
                    else:
                        score_emoji = "🔴"
                        score_label = "Limited Fit"

                    with st.expander(f"{score_emoji} {report_row['creator_name']} - {score:.1f}/5.0 ({score_label})", expanded=False):
                        # Generate report
                        try:
                            gen = ReportGenerator()
                            report_markdown = gen.generate_report(
                                creator_id=report_row['creator_id'],
                                brief_id=brief_id,
                                format="markdown"
                            )

                            # Display report
                            st.markdown(report_markdown)

                            st.markdown("---")

                            # Export buttons
                            col_export1, col_export2, col_export3 = st.columns(3)

                            with col_export1:
                                # Markdown export
                                st.download_button(
                                    label="📄 Export Markdown",
                                    data=report_markdown,
                                    file_name=f"report_{report_row['creator_name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.md",
                                    mime="text/markdown",
                                    key=f"md_{report_row['id']}",
                                    use_container_width=True
                                )

                            with col_export2:
                                # HTML export
                                report_html = gen.generate_report(
                                    creator_id=report_row['creator_id'],
                                    brief_id=brief_id,
                                    format="html"
                                )
                                st.download_button(
                                    label="🌐 Export HTML",
                                    data=report_html,
                                    file_name=f"report_{report_row['creator_name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.html",
                                    mime="text/html",
                                    key=f"html_{report_row['id']}",
                                    use_container_width=True
                                )

                            with col_export3:
                                # Text export
                                report_text = gen.generate_report(
                                    creator_id=report_row['creator_id'],
                                    brief_id=brief_id,
                                    format="text"
                                )
                                st.download_button(
                                    label="📝 Export Text",
                                    data=report_text,
                                    file_name=f"report_{report_row['creator_name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.txt",
                                    mime="text/plain",
                                    key=f"txt_{report_row['id']}",
                                    use_container_width=True
                                )

                        except Exception as e:
                            st.error(f"Error generating report: {str(e)}")

