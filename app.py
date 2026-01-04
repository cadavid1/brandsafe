import streamlit as st
import json
import pandas as pd
import time
import os
from datetime import datetime
from pathlib import Path

# Import new modules
from config import (
    MODELS, DEFAULT_MODEL, get_model_list, get_model_info,
    estimate_cost, format_cost, DRIVE_ENABLED,
    ANALYSIS_TIERS, PLATFORM_CONFIGS, DEFAULT_TIME_RANGE_DAYS,
    CREATOR_ANALYSIS_SYSTEM_PROMPT
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
from visualization import ReportVisualizer

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
            if st.button("Create Account", type="primary", width='stretch'):
                # Clear demo session and show registration
                auth.logout()
                st.rerun()

# Ensure data directories exist
ensure_video_directory()

# Initialize database
db = get_db()

# Initialize Session State
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

def calculate_dynamic_cost_estimate(tier_key, num_creators, model_id, posts_for_analysis, max_videos_to_analyze):
    """Calculate dynamic cost estimate based on actual user settings

    Args:
        tier_key: Analysis tier (quick, standard, deep, deep_research)
        num_creators: Number of creators to analyze
        model_id: Selected Gemini model ID
        posts_for_analysis: Number of posts to send to Gemini
        max_videos_to_analyze: Maximum videos to analyze per creator

    Returns:
        dict with 'total' and 'breakdown' keys containing cost estimates
    """
    try:
        # Get model pricing
        model_info = get_model_info(model_id)

        # Calculate text analysis cost per creator
        # Input tokens: posts * 600 tokens/post + 1000 for system prompt
        input_tokens = posts_for_analysis * 600 + 1000
        output_tokens = 500  # Conservative estimate for analysis JSON output

        text_cost_per_creator = (
            (input_tokens / 1_000_000) * model_info['cost_per_m_tokens_input'] +
            (output_tokens / 1_000_000) * model_info['cost_per_m_tokens_output']
        )

        # Calculate video analysis cost per creator
        # Using transcript-based cost as baseline (most common and conservative)
        video_cost_per_creator = 0.0
        if max_videos_to_analyze > 0:
            video_cost_per_creator = max_videos_to_analyze * 0.01  # $0.01 per video transcript

        # Calculate deep research cost per creator
        research_cost_per_creator = 0.0
        if tier_key == 'deep_research':
            # Average deep research cost based on typical query complexity
            # Uses Gemini 3 Pro pricing: $2.00 input / $12.00 output per M tokens
            research_cost_per_creator = 1.50

        # Calculate totals
        total_text = text_cost_per_creator * num_creators
        total_video = video_cost_per_creator * num_creators
        total_research = research_cost_per_creator * num_creators

        return {
            'total': total_text + total_video + total_research,
            'breakdown': {
                'text_analysis': total_text,
                'video_analysis': total_video,
                'deep_research': total_research
            }
        }
    except Exception as e:
        # Fallback to static estimate if calculation fails
        tier_info = ANALYSIS_TIERS.get(tier_key, ANALYSIS_TIERS['standard'])
        fallback_cost = num_creators * tier_info.get('estimated_cost_per_creator', 0.0)
        return {
            'total': fallback_cost,
            'breakdown': {
                'text_analysis': fallback_cost,
                'video_analysis': 0.0,
                'deep_research': 0.0
            }
        }

def format_cost_breakdown(cost_estimate, num_creators):
    """Format cost estimate breakdown for display

    Args:
        cost_estimate: Dict from calculate_dynamic_cost_estimate()
        num_creators: Number of creators

    Returns:
        Formatted string with cost breakdown
    """
    if num_creators == 0:
        return ""

    breakdown = cost_estimate['breakdown']
    per_creator_text = breakdown['text_analysis'] / num_creators
    per_creator_video = breakdown['video_analysis'] / num_creators
    per_creator_research = breakdown['deep_research'] / num_creators

    lines = []
    if per_creator_text > 0:
        lines.append(f"  - Text Analysis: {format_cost(per_creator_text)}")
    if per_creator_video > 0:
        lines.append(f"  - Video Analysis: {format_cost(per_creator_video)}")
    if per_creator_research > 0:
        lines.append(f"  - Deep Research: {format_cost(per_creator_research)}")

    return "\n".join(lines) if lines else ""

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
            👋 **Welcome to BrandSafe Talent Analysis!**

            This tool uses AI to analyze social media creators for brand partnership opportunities.

            **Quick Start:**
            1. Add your Gemini API key in System Setup
            2. Create a brief defining your campaign goals
            3. Add creators with their social media URLs
            4. Run analysis to evaluate brand fit

            💡 Check the System Status in the sidebar for next steps →
            """)
        st.session_state.welcome_shown = True

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

# Enhanced Status Indicators
st.sidebar.markdown("### System Status")

# API Key status
if st.session_state.api_key:
    st.sidebar.success("🔑 API Key: Connected")
else:
    st.sidebar.error("🔑 API Key: Not Set")
    st.sidebar.caption("   → Go to System Setup tab")

# Brief status
briefs_df = db.get_briefs(user_id)
if len(briefs_df) > 0:
    st.sidebar.success(f"📄 Briefs: {len(briefs_df)} created")
else:
    st.sidebar.warning("📄 Briefs: None created")
    st.sidebar.caption("   → Go to Briefs tab")

# Creator status
creators_df = db.get_creators(user_id)
if len(creators_df) > 0:
    st.sidebar.success(f"👥 Creators: {len(creators_df)} added")
else:
    st.sidebar.warning("👥 Creators: None added")
    st.sidebar.caption("   → Go to Creators tab")

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
    - Check System Status above to see next steps
    - Green status = ready to proceed
    - Analysis cost estimates shown before running
    - Multi-platform support (YouTube, Instagram, TikTok, Twitch)

    **Getting Help:**
    - Check empty states for guidance
    - View Home tab for quick start guide
    - Contact support if stuck
    """)

# --- MAIN CONTENT WITH HORIZONTAL TABS ---

# Show welcome message for first-time users
check_first_time_user()

tab_home, tab_setup, tab_briefs, tab_creators, tab_analysis, tab_reports, tab_compare, tab_assets = st.tabs([
    "🏠 Home",
    "⚙️ System Setup",
    "📄 Briefs",
    "👥 Creators",
    "🔍 Analysis",
    "📊 Reports",
    "⚖️ Compare",
    "🎨 Campaign Assets"
])

# --- TAB: HOME/OVERVIEW ---

with tab_home:
    st.title("Welcome to BrandSafe")
    st.caption("AI-Powered Creator Analysis for Brand Partnerships")

    st.markdown("")

    # Quick stats overview with better styling
    col1, col2, col3, col4 = st.columns(4)
    briefs_df = db.get_briefs(user_id)
    creators_df = db.get_creators(user_id)

    # Get total number of creator reports
    all_reports = []
    if not briefs_df.empty:
        for _, brief in briefs_df.iterrows():
            reports = db.get_reports_for_brief(brief['id'])
            all_reports.extend(reports.to_dict('records') if not reports.empty else [])

    stats_home = db.get_statistics(user_id)

    with col1:
        st.metric("📄 Briefs", len(briefs_df))
    with col2:
        st.metric("👥 Creators", len(creators_df))
    with col3:
        st.metric("📊 Reports", len(all_reports))
    with col4:
        st.metric("💰 Cost", format_cost(stats_home['total_cost']))

    st.markdown("---")

    # System readiness check - prominent at top
    if not st.session_state.api_key or len(briefs_df) == 0 or len(creators_df) == 0:
        st.markdown("### 🚦 Getting Started")
        col_check1, col_check2, col_check3 = st.columns(3)

        with col_check1:
            if st.session_state.api_key:
                st.success("✅ **API Key**")
                st.caption("Ready to analyze")
            else:
                st.error("❌ **API Key**")
                st.caption("→ Go to System Setup")

        with col_check2:
            if len(briefs_df) > 0:
                st.success(f"✅ **{len(briefs_df)} Brief(s)**")
                st.caption("Campaign defined")
            else:
                st.warning("⚠️ **No Briefs**")
                st.caption("→ Go to Briefs tab")

        with col_check3:
            if len(creators_df) > 0:
                st.success(f"✅ **{len(creators_df)} Creator(s)**")
                st.caption("Ready to analyze")
            else:
                st.warning("⚠️ **No Creators**")
                st.caption("→ Go to Creators tab")

        st.markdown("---")

    # Two-column layout for overview
    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        st.markdown("### 🚀 Quick Start Guide")

        st.markdown("**1. System Setup**")
        st.markdown("Add your Gemini API key and optional YouTube API keys for multi-platform analysis")
        st.markdown("")

        st.markdown("**2. Create Brief**")
        st.markdown("Define campaign goals, brand context, and target audience to evaluate creator fit")
        st.markdown("")

        st.markdown("**3. Add Creators**")
        st.markdown("Input social media URLs (YouTube, Instagram, TikTok, Twitch) and link to brief")
        st.markdown("")

        st.markdown("**4. Run Analysis**")
        st.markdown("Choose analysis depth (Quick/Standard/Deep) and review brand fit scores")
        st.markdown("")

        st.markdown("**5. View Reports**")
        st.markdown("Export professional reports in Markdown, HTML, PDF, or Excel formats")

        st.markdown("---")

        st.markdown("### ✨ Key Features")

        feature_col1, feature_col2 = st.columns(2)

        with feature_col1:
            st.markdown("**🌐 Multi-Platform**")
            st.caption("YouTube, Instagram, TikTok, Twitch")
            st.markdown("")

            st.markdown("**📊 Brand Fit Scoring**")
            st.caption("AI-powered 1-5 scale alignment")
            st.markdown("")

            st.markdown("**⚡ Flexible Tiers**")
            st.caption("Quick, Standard, Deep analysis")
            st.markdown("")

            st.markdown("**📄 Pro Reports**")
            st.caption("MD, HTML, PDF, Excel export")

        with feature_col2:
            st.markdown("**💰 Cost Optimization**")
            st.caption("API key rotation & caching")
            st.markdown("")

            st.markdown("**🔍 Account Discovery**")
            st.caption("Auto-detect alternate platforms")
            st.markdown("")

            st.markdown("**📈 Content Analysis**")
            st.caption("Themes, sentiment, engagement")
            st.markdown("")

            st.markdown("**👥 Demographics**")
            st.caption("Audience insights & stats")

    with col_right:
        st.markdown("### 📊 Recent Activity")

        # Show recent briefs and reports
        if not briefs_df.empty:
            recent_briefs = briefs_df.sort_values('created_at', ascending=False).head(3)

            for _, brief in recent_briefs.iterrows():
                with st.container():
                    st.markdown(f"**📄 {brief['name']}**")

                    # Get creators for this brief
                    brief_creators = db.get_creators_for_brief(brief['id'])
                    if not brief_creators.empty:
                        st.caption(f"↳ {len(brief_creators)} creator(s) linked")

                    # Handle both string (SQLite) and Timestamp (PostgreSQL) formats
                    created_date = brief['created_at']
                    if hasattr(created_date, 'strftime'):
                        created_date = created_date.strftime('%Y-%m-%d')
                    else:
                        created_date = str(created_date)[:10]
                    st.caption(f"↳ Created {created_date}")
                    st.markdown("")
        else:
            st.info("💡 **No activity yet**\n\nCreate your first brief to get started!")

        if len(all_reports) > 0:
            st.markdown("---")
            st.markdown("### 📈 Analysis Summary")

            # Show average brand fit score across all reports
            avg_score = sum(r.get('overall_score', 0) for r in all_reports) / len(all_reports)

            # Score indicator
            if avg_score >= 4.0:
                score_color = "🟢"
                score_label = "Strong"
            elif avg_score >= 3.0:
                score_color = "🟡"
                score_label = "Moderate"
            else:
                score_color = "🔴"
                score_label = "Mixed"

            st.markdown(f"**{score_color} Average Brand Fit:** {avg_score:.1f}/5.0 ({score_label})")
            st.caption(f"Based on {len(all_reports)} creator analysis")
            st.caption(f"Total investment: {format_cost(stats_home['total_cost'])}")

# --- TAB: SYSTEM SETUP ---

with tab_setup:
    st.header("System Setup")

    # System Status at the top
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.session_state.api_key:
            st.success("🔑 API Key")
        else:
            st.error("🔑 API Key Missing")
    with col2:
        briefs_df_status = db.get_briefs(user_id)
        if len(briefs_df_status) > 0:
            st.success(f"📄 {len(briefs_df_status)} Briefs")
        else:
            st.warning("📄 No Briefs")
    with col3:
        creators_df_status = db.get_creators(user_id)
        if len(creators_df_status) > 0:
            st.success(f"👥 {len(creators_df_status)} Creators")
        else:
            st.warning("👥 No Creators")
    with col4:
        stats_setup = db.get_statistics(user_id)
        st.metric("💰 Cost", format_cost(stats_setup['total_cost']))

    st.markdown("---")

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

        # Show cost impact notice if model differs from default
        if st.session_state.selected_model != DEFAULT_MODEL:
            default_info = get_model_info(DEFAULT_MODEL)
            # Compare output cost as it's typically the dominant factor
            if default_info['cost_per_m_tokens_output'] > 0 and model_info['cost_per_m_tokens_output'] > 0:
                cost_multiplier = (
                    model_info['cost_per_m_tokens_output'] /
                    default_info['cost_per_m_tokens_output']
                )
                if cost_multiplier > 1.2:
                    st.warning(f"⚠️ This model costs ~{cost_multiplier:.1f}x more than the default model ({default_info['display_name']})")
                elif cost_multiplier < 0.8:
                    st.info(f"💡 This model costs ~{1/cost_multiplier:.1f}x less than the default model ({default_info['display_name']})")

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

    with st.expander("Debug Mode", expanded=False):
        st.markdown("Enable verbose debug logging in the terminal/console")

        # Get current debug mode setting
        debug_mode = db.get_setting(user_id, "debug_mode", "false") == "true"

        new_debug_mode = st.checkbox(
            "Enable Debug Logging",
            value=debug_mode,
            help="Shows detailed logs for OAuth, API calls, and internal operations in the terminal"
        )

        if new_debug_mode != debug_mode:
            db.save_setting(user_id, "debug_mode", "true" if new_debug_mode else "false")
            if new_debug_mode:
                st.success("✅ Debug mode enabled - check your terminal for detailed logs")
            else:
                st.success("✅ Debug mode disabled")
            st.rerun()

        if debug_mode:
            st.info("🐛 Debug mode is ON - verbose logging active in terminal")
        else:
            st.caption("Debug mode is off - minimal console output")

        st.markdown("---")

        # Demographics Debug Mode
        demographics_debug = db.get_setting(user_id, "demographics_debug", "false") == "true"

        new_demographics_debug = st.checkbox(
            "Enable Demographics Debug Logging",
            value=demographics_debug,
            help="Shows detailed logs specifically for demographics data fetching, caching, and storage"
        )

        if new_demographics_debug != demographics_debug:
            db.save_setting(user_id, "demographics_debug", "true" if new_demographics_debug else "false")
            if new_demographics_debug:
                st.success("✅ Demographics debug enabled - detailed tracking in terminal")
            else:
                st.success("✅ Demographics debug disabled")
            st.rerun()

        if demographics_debug:
            st.info("📊 Demographics debug is ON - tracking data flow in terminal")

            # Add diagnostics button
            if st.button("🔍 Run Demographics Diagnostics", help="Check demographics data status for all creators"):
                st.markdown("### Demographics Diagnostics Report")

                # Get all creators for this user
                creators = db.get_creators(user_id)
                if creators.empty:
                    st.warning("No creators found")
                else:
                    total_accounts = 0
                    accounts_with_demographics = 0
                    demographics_details = []

                    for _, creator in creators.iterrows():
                        accounts = db.get_social_accounts(creator['id'])
                        for _, account in accounts.iterrows():
                            total_accounts += 1
                            demo_data = db.get_demographics_data(account['id'])

                            if demo_data:
                                accounts_with_demographics += 1
                                demographics_details.append({
                                    'Creator': creator['name'],
                                    'Platform': account['platform'].title(),
                                    'Has Demographics': '✅ Yes',
                                    'Data Source': demo_data.get('data_source', 'Unknown'),
                                    'Snapshot Date': demo_data.get('snapshot_date', 'N/A'),
                                    'Data Confidence': demo_data.get('data_confidence', 'N/A'),
                                    'Has Gender': '✓' if demo_data.get('gender') else '✗',
                                    'Has Age': '✓' if demo_data.get('age_brackets') else '✗',
                                    'Has Geography': '✓' if demo_data.get('geography') else '✗'
                                })
                            else:
                                demographics_details.append({
                                    'Creator': creator['name'],
                                    'Platform': account['platform'].title(),
                                    'Has Demographics': '❌ No',
                                    'Data Source': 'N/A',
                                    'Snapshot Date': 'N/A',
                                    'Data Confidence': 'N/A',
                                    'Has Gender': '✗',
                                    'Has Age': '✗',
                                    'Has Geography': '✗'
                                })

                    # Summary stats
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Social Accounts", total_accounts)
                    with col2:
                        st.metric("Accounts with Demographics", accounts_with_demographics)
                    with col3:
                        coverage = (accounts_with_demographics / total_accounts * 100) if total_accounts > 0 else 0
                        st.metric("Coverage", f"{coverage:.1f}%")

                    # Detailed table
                    if demographics_details:
                        st.dataframe(pd.DataFrame(demographics_details), width="stretch", hide_index=True)

                    # Recommendations
                    st.markdown("### 💡 Recommendations")
                    if coverage < 10:
                        st.error("⚠️ Very low demographics coverage. Make sure to use the 'Deep Research' analysis tier when analyzing creators.")
                    elif coverage < 50:
                        st.warning("⚠️ Low demographics coverage. Consider re-analyzing creators with the 'Deep Research' tier.")
                    elif coverage < 80:
                        st.info("📊 Moderate demographics coverage. Some creators are missing demographic data.")
                    else:
                        st.success("✅ Good demographics coverage!")

                    st.markdown("""
                    **How to fix missing demographics:**
                    1. Use the **Deep Research** analysis tier (not Quick, Standard, or Comprehensive)
                    2. Ensure your Gemini API key is properly configured
                    3. Check the terminal logs for any API errors
                    4. Demographics data is cached for 90 days by default
                    """)

                    # Add manual demographics fetch option
                    st.markdown("---")
                    st.markdown("### 🔄 Manual Demographics Fetch")
                    st.markdown("Fetch demographics data for a specific creator (takes 5-30 minutes)")

                    # Select creator
                    creator_options = {row['name']: row['id'] for _, row in creators.iterrows()}
                    selected_creator = st.selectbox(
                        "Select creator to fetch demographics:",
                        options=list(creator_options.keys()),
                        key="demographics_fetch_creator"
                    )

                    # Use a unique key for the button to avoid conflicts
                    fetch_clicked = st.button(
                        "🚀 Fetch Demographics Now",
                        key="fetch_demographics_button",
                        help="This will start a Deep Research job (may take 5-30 minutes)"
                    )

                    if fetch_clicked:
                        selected_creator_id = creator_options[selected_creator]

                        st.info(f"⏳ Starting demographics fetch for {selected_creator}...")
                        st.markdown("**Note:** This may take 5-30 minutes depending on Deep Research. Check the terminal for progress logs.")

                        # Add a separator to see the fetch logs clearly
                        print("\n" + "=" * 80)
                        print("MANUAL DEMOGRAPHICS FETCH TRIGGERED FROM UI")
                        print("=" * 80)

                        try:
                            from creator_analyzer import CreatorAnalyzer

                            # Get Gemini API key from settings
                            gemini_api_key = db.get_setting(user_id, "api_key", default="")
                            if not gemini_api_key:
                                gemini_api_key = db.get_setting(user_id, "gemini_api_key", default="")
                            if not gemini_api_key:
                                gemini_api_key = db.get_setting(user_id, "google_api_key", default="")

                            if not gemini_api_key:
                                st.error("❌ Gemini API key not configured. Please add your API key in Settings first.")
                            else:
                                analyzer = CreatorAnalyzer(gemini_api_key)

                                # Run in a progress container
                                with st.spinner("Fetching demographics via Deep Research..."):
                                    results = analyzer.fetch_demographics_for_creator(
                                        creator_id=selected_creator_id,
                                        analysis_depth="deep_research"
                                    )

                                # Show results
                                success_count = sum(1 for v in results.values() if v)
                                total_count = len(results)

                                if success_count > 0:
                                    st.success(f"✅ Demographics fetched for {success_count}/{total_count} platforms")
                                    for platform, success in results.items():
                                        if success:
                                            st.write(f"  ✅ {platform}")
                                        else:
                                            st.write(f"  ❌ {platform}")

                                    st.info("🔄 Refresh the page to see updated demographics in reports")
                                else:
                                    st.error("❌ Failed to fetch demographics for any platform")
                                    st.markdown("Check the terminal logs for detailed error information")

                        except Exception as e:
                            st.error(f"❌ Error: {type(e).__name__}: {e}")
                            st.markdown("Check the terminal logs for detailed error information")
                            import traceback
                            print("\n[ERROR] Exception during demographics fetch:")
                            traceback.print_exc()

        else:
            st.caption("Demographics debug is off")

        st.markdown("---")

        # Custom Factor Weights
        st.markdown("### 🎚️ Brand Fit Score Weights")
        st.caption("Customize how different factors contribute to the overall brand fit score")

        # Get current weights or use defaults
        default_weights = {
            'brand_safety': 0.3,
            'authenticity': 0.25,
            'natural_alignment': 0.25,
            'reach': 0.2
        }

        current_weights = {
            'brand_safety': float(db.get_setting(user_id, "weight_brand_safety", str(default_weights['brand_safety']))),
            'authenticity': float(db.get_setting(user_id, "weight_authenticity", str(default_weights['authenticity']))),
            'natural_alignment': float(db.get_setting(user_id, "weight_natural_alignment", str(default_weights['natural_alignment']))),
            'reach': float(db.get_setting(user_id, "weight_reach", str(default_weights['reach'])))
        }

        # Display current total
        current_total = sum(current_weights.values())
        if abs(current_total - 1.0) > 0.01:
            st.warning(f"⚠️ Current weights sum to {current_total:.2f}, not 1.0. Please adjust.")

        # Create sliders for each weight
        new_weights = {}
        cols = st.columns(2)

        with cols[0]:
            new_weights['brand_safety'] = st.slider(
                "Brand Safety",
                min_value=0.0,
                max_value=1.0,
                value=current_weights['brand_safety'],
                step=0.05,
                help="Weight for brand safety score (content appropriateness)",
                key="weight_slider_safety"
            )

            new_weights['natural_alignment'] = st.slider(
                "Natural Alignment",
                min_value=0.0,
                max_value=1.0,
                value=current_weights['natural_alignment'],
                step=0.05,
                help="Weight for natural alignment (organic brand/category mentions)",
                key="weight_slider_alignment"
            )

        with cols[1]:
            new_weights['authenticity'] = st.slider(
                "Authenticity",
                min_value=0.0,
                max_value=1.0,
                value=current_weights['authenticity'],
                step=0.05,
                help="Weight for authenticity score (genuine engagement)",
                key="weight_slider_authenticity"
            )

            new_weights['reach'] = st.slider(
                "Reach",
                min_value=0.0,
                max_value=1.0,
                value=current_weights['reach'],
                step=0.05,
                help="Weight for reach (follower count, scaled)",
                key="weight_slider_reach"
            )

        # Calculate new total
        new_total = sum(new_weights.values())
        total_color = "green" if abs(new_total - 1.0) < 0.01 else "orange"
        st.markdown(f"**Total Weight:** :{total_color}[{new_total:.2f}] {'✅' if abs(new_total - 1.0) < 0.01 else '⚠️ Must equal 1.00'}")

        # Show formula preview
        st.caption(f"""
**Formula:** Brand Fit = (Safety × {new_weights['brand_safety']:.2f}) +
(Authenticity × {new_weights['authenticity']:.2f}) +
(Alignment × {new_weights['natural_alignment']:.2f}) +
(Reach × {new_weights['reach']:.2f})
""")

        # Save button
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("💾 Save Weights", disabled=abs(new_total - 1.0) >= 0.01, key="save_weights_btn"):
                # Save all weights
                db.save_setting(user_id, "weight_brand_safety", str(new_weights['brand_safety']))
                db.save_setting(user_id, "weight_authenticity", str(new_weights['authenticity']))
                db.save_setting(user_id, "weight_natural_alignment", str(new_weights['natural_alignment']))
                db.save_setting(user_id, "weight_reach", str(new_weights['reach']))
                st.success("✅ Custom weights saved!")
                st.rerun()

        with col2:
            if st.button("🔄 Reset to Default", key="reset_weights_btn"):
                # Reset to defaults
                for factor, default in default_weights.items():
                    db.save_setting(user_id, f"weight_{factor}", str(default))
                st.success("✅ Reset to default weights")
                st.rerun()

        # Show if using custom weights
        weights_are_custom = any(
            abs(current_weights[k] - default_weights[k]) > 0.01
            for k in default_weights
        )
        if weights_are_custom:
            st.info("ℹ️ Using custom weights. All new analyses will use these weights.")
        else:
            st.caption("Using default weights (30% safety, 25% authenticity, 25% alignment, 20% reach)")

        st.markdown("---")

        # Alignment Score Debug Mode
        alignment_debug = db.get_setting(user_id, "alignment_debug", "false") == "true"

        new_alignment_debug = st.checkbox(
            "Enable Natural Alignment Debug Logging",
            value=alignment_debug,
            help="Shows detailed logs for how natural alignment scores are calculated by Gemini AI",
            key="alignment_debug_checkbox"
        )

        if new_alignment_debug != alignment_debug:
            db.save_setting(user_id, "alignment_debug", "true" if new_alignment_debug else "false")
            if new_alignment_debug:
                st.success("✅ Alignment debug enabled - check terminal for detailed logs")
            else:
                st.success("✅ Alignment debug disabled")
            st.rerun()

        if alignment_debug:
            st.info("🔍 Alignment debug is ON - tracking natural alignment scoring in terminal")
        else:
            st.caption("Alignment debug is off")

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

    with st.expander("Analysis Configuration", expanded=False):
        st.markdown("### Content Analysis Prompt")
        st.caption("This prompt is sent to Gemini along with creator posts to evaluate brand safety, content themes, and partnership fit.")

        # Get current custom prompt or use default
        current_custom_prompt = db.get_setting(user_id, "custom_analysis_prompt", "")
        using_custom = bool(current_custom_prompt)

        if using_custom:
            display_prompt = current_custom_prompt
            st.info("✓ Using custom prompt")
        else:
            display_prompt = CREATOR_ANALYSIS_SYSTEM_PROMPT
            st.info("Using default prompt")

        # Prompt editor
        edited_prompt = st.text_area(
            "Analysis Prompt",
            value=display_prompt,
            height=300,
            help="This prompt defines how Gemini analyzes creator content. Customize it to match your evaluation criteria."
        )

        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("💾 Save Custom Prompt", type="primary"):
                if edited_prompt and edited_prompt != CREATOR_ANALYSIS_SYSTEM_PROMPT:
                    db.save_setting(user_id, "custom_analysis_prompt", edited_prompt)
                    st.success("✅ Custom prompt saved")
                    st.rerun()
                elif edited_prompt == CREATOR_ANALYSIS_SYSTEM_PROMPT:
                    # If it matches default, clear custom setting
                    db.save_setting(user_id, "custom_analysis_prompt", "")
                    st.info("Prompt matches default - cleared custom setting")
                    st.rerun()
                else:
                    st.warning("Prompt cannot be empty")

        with col2:
            if using_custom:
                if st.button("↩️ Reset to Default"):
                    db.save_setting(user_id, "custom_analysis_prompt", "")
                    st.success("✅ Reset to default prompt")
                    st.rerun()

        with col3:
            with st.popover("ℹ️ How Prompts Work"):
                st.markdown("""
                **How Analysis Works:**

                1. **Data Collection**: System fetches recent posts from creator's social accounts
                2. **Prompt Construction**: Up to 20 posts are selected and formatted with:
                   - Platform name
                   - Post caption/title (first 500 chars)
                   - Engagement metrics (likes, views)
                3. **AI Analysis**: The prompt + brand context + posts are sent to Gemini
                4. **Response**: Gemini returns structured JSON with themes, scores, and recommendations

                **Tips for Custom Prompts:**
                - Keep the JSON output format intact for proper parsing
                - Focus on your specific brand safety criteria
                - Add custom scoring dimensions if needed
                - Include examples of red flags specific to your brand
                """)

        st.markdown("---")
        st.markdown("### Analysis Limits")
        st.caption("Control how much content is analyzed per creator to balance quality and cost.")

        # Get current limits or use defaults
        posts_for_analysis = int(db.get_setting(user_id, "posts_for_gemini_analysis", "20"))

        col1, col2 = st.columns(2)
        with col1:
            new_posts_limit = st.number_input(
                "Posts Sent to Gemini for Analysis",
                min_value=5,
                max_value=100,
                value=posts_for_analysis,
                step=5,
                help="Number of most engaging posts to analyze with Gemini. More posts = better insights but higher cost."
            )

            if new_posts_limit != posts_for_analysis:
                db.save_setting(user_id, "posts_for_gemini_analysis", str(new_posts_limit))
                st.success(f"✅ Updated to {new_posts_limit} posts")
                st.rerun()

        with col2:
            st.metric("Current Setting", f"{posts_for_analysis} posts")

            # Estimate token/cost impact
            estimated_tokens = posts_for_analysis * 600  # ~600 tokens per post (caption + metadata)
            estimated_cost = (estimated_tokens / 1_000_000) * 1.25  # Using Gemini 2.5 Pro input cost

            st.caption(f"≈ {estimated_tokens:,} tokens")
            st.caption(f"≈ ${estimated_cost:.3f} per creator")

        st.markdown("**Analysis Tier Configurations:**")
        st.caption("Configure max posts fetched from platforms (before selection for Gemini analysis)")

        # Get tier configurations
        tier_configs = {
            "standard": {
                "name": "Standard Analysis",
                "current_max": int(db.get_setting(user_id, "tier_standard_max_posts", "10")),
                "default": 10
            },
            "deep": {
                "name": "Deep Dive",
                "current_max": int(db.get_setting(user_id, "tier_deep_max_posts", "50")),
                "default": 50
            },
            "deep_research": {
                "name": "Deep Research",
                "current_max": int(db.get_setting(user_id, "tier_deep_research_max_posts", "50")),
                "default": 50
            }
        }

        for tier_key, tier_info in tier_configs.items():
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                st.text(tier_info["name"])

            with col2:
                new_max = st.number_input(
                    f"Max posts",
                    min_value=5,
                    max_value=200,
                    value=tier_info["current_max"],
                    step=5,
                    key=f"tier_{tier_key}_max",
                    label_visibility="collapsed"
                )

                if new_max != tier_info["current_max"]:
                    db.save_setting(user_id, f"tier_{tier_key}_max_posts", str(new_max))
                    st.rerun()

            with col3:
                if tier_info["current_max"] != tier_info["default"]:
                    if st.button("Reset", key=f"reset_{tier_key}"):
                        db.save_setting(user_id, f"tier_{tier_key}_max_posts", str(tier_info["default"]))
                        st.rerun()

        st.info("""
        **Note**: The system fetches up to `Max posts` from each platform, then selects the top posts
        by engagement for Gemini analysis (based on "Posts Sent to Gemini" setting above).
        """)

    with st.expander("Instagram Configuration (Optional)", expanded=False):
        st.markdown("Add Instagram login credentials to improve scraping reliability and bypass rate limits.")
        st.warning("⚠️ **Privacy Notice**: Credentials are stored locally and only used for Instagram API access. Use a dedicated account if concerned.")

        # Get current Instagram credentials
        instagram_username = db.get_setting(user_id, "instagram_username", "")
        instagram_password_set = bool(db.get_setting(user_id, "instagram_password", ""))

        # Form to update credentials
        with st.form("instagram_credentials_form"):
            col1, col2 = st.columns(2)
            with col1:
                new_ig_username = st.text_input(
                    "Instagram Username",
                    value=instagram_username,
                    placeholder="your_instagram_username",
                    help="Your Instagram username (without @)"
                )
            with col2:
                new_ig_password = st.text_input(
                    "Instagram Password",
                    type="password",
                    placeholder="••••••••" if instagram_password_set else "Enter password",
                    help="Your Instagram password"
                )

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.form_submit_button("💾 Save Credentials", type="primary"):
                    if new_ig_username and new_ig_password:
                        db.save_setting(user_id, "instagram_username", new_ig_username)
                        db.save_setting(user_id, "instagram_password", new_ig_password)
                        st.success("✅ Instagram credentials saved")
                        st.rerun()
                    elif new_ig_username:
                        # Save username only, keep existing password
                        db.save_setting(user_id, "instagram_username", new_ig_username)
                        st.success("✅ Username saved")
                        st.rerun()
                    else:
                        st.warning("Please provide at least a username")

            with col2:
                if instagram_username or instagram_password_set:
                    if st.form_submit_button("🗑️ Clear Credentials"):
                        db.save_setting(user_id, "instagram_username", "")
                        db.save_setting(user_id, "instagram_password", "")
                        st.success("✅ Credentials cleared")
                        st.rerun()

        # Status display
        if instagram_username:
            st.info(f"✓ Logged in as @{instagram_username}")
            st.caption("Instagram scraping will use authenticated access for better reliability")
        else:
            st.info("ℹ️ No credentials configured - Instagram will use anonymous access (limited)")
            st.caption("Anonymous access may result in rate limits or 403 errors. Consider adding credentials.")

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
                    # Handle both string (SQLite) and Timestamp (PostgreSQL) formats
                    created_date = brief['created_at']
                    if hasattr(created_date, 'strftime'):
                        created_date = created_date.strftime('%Y-%m-%d')
                    else:
                        created_date = str(created_date)[:10]
                    st.caption(f"**Created:** {created_date}")

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

            st.markdown("**Social Media Accounts** (add at least one)")

            # Multiple URL inputs for different platforms
            col1, col2 = st.columns(2)
            with col1:
                youtube_url = st.text_input("YouTube", placeholder="https://youtube.com/@creator", key="yt_url")
                instagram_url = st.text_input("Instagram", placeholder="https://instagram.com/creator", key="ig_url")
            with col2:
                tiktok_url = st.text_input("TikTok", placeholder="https://tiktok.com/@creator", key="tt_url")
                twitch_url = st.text_input("Twitch", placeholder="https://twitch.tv/creator", key="tw_url")

            notes = st.text_area("Notes (optional)", placeholder="Additional information about this creator...")

            if st.form_submit_button("Add Creator", type="primary"):
                # Collect all provided URLs
                platform_urls = {}

                if youtube_url:
                    platform = detect_platform_from_url(youtube_url)
                    if platform == 'youtube':
                        platform_urls['youtube'] = {
                            'url': youtube_url,
                            'handle': extract_handle_from_url(youtube_url, 'youtube')
                        }

                if instagram_url:
                    platform = detect_platform_from_url(instagram_url)
                    if platform == 'instagram':
                        platform_urls['instagram'] = {
                            'url': instagram_url,
                            'handle': extract_handle_from_url(instagram_url, 'instagram')
                        }

                if tiktok_url:
                    platform = detect_platform_from_url(tiktok_url)
                    if platform == 'tiktok':
                        platform_urls['tiktok'] = {
                            'url': tiktok_url,
                            'handle': extract_handle_from_url(tiktok_url, 'tiktok')
                        }

                if twitch_url:
                    platform = detect_platform_from_url(twitch_url)
                    if platform == 'twitch':
                        platform_urls['twitch'] = {
                            'url': twitch_url,
                            'handle': extract_handle_from_url(twitch_url, 'twitch')
                        }

                # Validation
                if not creator_name:
                    st.error("Please enter a Creator Name")
                elif len(platform_urls) == 0:
                    st.error("Please add at least one social media URL")
                else:
                    # Determine primary platform (first one added)
                    primary_platform = list(platform_urls.keys())[0]

                    # Save creator
                    creator_id = db.save_creator(
                        user_id=user_id,
                        name=creator_name,
                        primary_platform=primary_platform,
                        notes=notes
                    )

                    # Save all social accounts
                    for platform, data in platform_urls.items():
                        db.save_social_account(
                            creator_id=creator_id,
                            platform=platform,
                            profile_url=data['url'],
                            handle=data['handle'],
                            discovery_method="manual"
                        )

                    st.success(f"✅ Creator added: {creator_name} ({len(platform_urls)} platform(s))")
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
                    # Handle both string (SQLite) and Timestamp (PostgreSQL) formats
                    created_date = creator['created_at']
                    if hasattr(created_date, 'strftime'):
                        created_date = created_date.strftime('%Y-%m-%d')
                    else:
                        created_date = str(created_date)[:10]
                    st.caption(f"**Added:** {created_date}")

                    # Show social accounts
                    accounts_df = db.get_social_accounts(creator['id'])
                    if not accounts_df.empty:
                        st.markdown(f"**Social Accounts ({len(accounts_df)}):**")
                        for _, account in accounts_df.iterrows():
                            st.caption(f"  • {account['platform'].title()}: [{account.get('handle', 'N/A')}]({account['profile_url']})")
                            if account.get('last_fetched_at'):
                                # Handle both string (SQLite) and Timestamp (PostgreSQL) formats
                                fetched_date = account['last_fetched_at']
                                if hasattr(fetched_date, 'strftime'):
                                    fetched_date = fetched_date.strftime('%Y-%m-%d')
                                else:
                                    fetched_date = str(fetched_date)[:10]
                                st.caption(f"    Last fetched: {fetched_date}")

                    # Add additional social account
                    with st.expander("➕ Add Another Social Account"):
                        with st.form(f"add_social_account_{creator['id']}"):
                            new_profile_url = st.text_input(
                                "Social Media URL",
                                placeholder="https://instagram.com/creator or https://tiktok.com/@creator",
                                key=f"new_url_{creator['id']}"
                            )

                            # Auto-detect platform
                            new_detected_platform = None
                            new_detected_handle = None
                            if new_profile_url:
                                new_detected_platform = detect_platform_from_url(new_profile_url)
                                if new_detected_platform:
                                    new_detected_handle = extract_handle_from_url(new_profile_url, new_detected_platform)

                                    # Check if this platform already exists for this creator
                                    existing_platforms = accounts_df['platform'].tolist() if not accounts_df.empty else []
                                    if new_detected_platform in existing_platforms:
                                        st.warning(f"⚠️ {new_detected_platform.title()} account already exists for this creator")
                                    else:
                                        st.info(f"✓ Detected: {new_detected_platform.title()} - @{new_detected_handle}")
                                else:
                                    st.warning("Could not detect platform. Supported: YouTube, Instagram, TikTok, Twitch")

                            if st.form_submit_button("Add Social Account", type="primary"):
                                if not new_profile_url:
                                    st.error("Please enter a social media URL")
                                elif not new_detected_platform:
                                    st.error("Invalid URL. Supported platforms: YouTube, Instagram, TikTok, Twitch")
                                else:
                                    # Check for duplicates
                                    existing_platforms = accounts_df['platform'].tolist() if not accounts_df.empty else []
                                    if new_detected_platform in existing_platforms:
                                        st.error(f"{new_detected_platform.title()} account already exists for this creator")
                                    else:
                                        # Save new social account
                                        db.save_social_account(
                                            creator_id=creator['id'],
                                            platform=new_detected_platform,
                                            profile_url=new_profile_url,
                                            handle=new_detected_handle,
                                            discovery_method="manual"
                                        )
                                        st.success(f"✅ Added {new_detected_platform.title()} account!")
                                        time.sleep(1)
                                        st.rerun()

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
                                brief_id = int(briefs_df_link[briefs_df_link['name'] == selected_brief].iloc[0]['id'])
                                result = db.link_creator_to_brief(brief_id, creator['id'])
                                if result:
                                    st.success(f"Linked {creator['name']} to {selected_brief}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"Failed to link {creator['name']} to {selected_brief}. Check the terminal for details.")
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
            brief_id = int(brief_row['id'])

            # Get creators for this brief
            creators_in_brief = db.get_creators_for_brief(brief_id)

            if creators_in_brief.empty:
                st.warning("""
                👥 **No creators linked to this brief**

                Go to the Creators tab and link creators to this brief first.
                """)
            else:
                # Creator Selection Section
                st.markdown("### Select Creators to Analyze")

                # Initialize session state for selected creators if not exists
                if 'selected_creators_for_analysis' not in st.session_state:
                    st.session_state.selected_creators_for_analysis = set(creators_in_brief['id'].tolist())

                # Search/Filter Bar
                col_search, col_clear = st.columns([4, 1])
                with col_search:
                    search_query = st.text_input(
                        "🔍 Search creators",
                        placeholder="Filter by name or platform...",
                        key="creator_search_analysis",
                        label_visibility="collapsed"
                    )
                with col_clear:
                    if search_query and st.button("✕ Clear", width='stretch', key="clear_search_analysis"):
                        st.session_state.creator_search_analysis = ""
                        st.rerun()

                # Filter creators based on search query
                if search_query:
                    search_lower = search_query.lower()
                    filtered_creators = []

                    for _, creator in creators_in_brief.iterrows():
                        # Search in creator name
                        if search_lower in creator['name'].lower():
                            filtered_creators.append(creator)
                            continue

                        # Search in platforms
                        accounts = db.get_social_accounts(int(creator['id']))
                        platforms_str = ' '.join(accounts['platform'].str.lower().tolist()) if not accounts.empty else ''
                        if search_lower in platforms_str:
                            filtered_creators.append(creator)
                            continue

                    # Convert back to DataFrame
                    import pandas as pd
                    if filtered_creators:
                        creators_display = pd.DataFrame(filtered_creators)
                    else:
                        creators_display = pd.DataFrame()

                    # Show filter status
                    if creators_display.empty:
                        st.warning(f"🔍 No creators found matching '{search_query}'")
                    else:
                        st.info(f"🔍 Showing {len(creators_display)} of {len(creators_in_brief)} creators")
                else:
                    creators_display = creators_in_brief

                # Selection controls
                col_select1, col_select2, col_select3 = st.columns([1, 1, 2])

                with col_select1:
                    if st.button("✓ Select All", width='stretch', help="Select all creators (including filtered)"):
                        st.session_state.selected_creators_for_analysis = set(creators_in_brief['id'].tolist())
                        st.rerun()

                with col_select2:
                    if st.button("✗ Deselect All", width='stretch', help="Deselect all creators"):
                        st.session_state.selected_creators_for_analysis = set()
                        st.rerun()

                with col_select3:
                    selected_count = len(st.session_state.selected_creators_for_analysis)
                    st.caption(f"**{selected_count}** of **{len(creators_in_brief)}** creator(s) selected")

                st.markdown("")

                # Display creators with checkboxes and brief associations
                if creators_display.empty:
                    st.caption("No creators to display")
                else:
                    for _, creator in creators_display.iterrows():
                        creator_id = int(creator['id'])

                        # Get all briefs this creator is linked to
                        conn = db._get_connection()
                        cursor = db.db_adapter.cursor()
                        cursor.execute("""
                            SELECT b.name
                            FROM briefs b
                            JOIN brief_creators bc ON b.id = bc.brief_id
                            WHERE bc.creator_id = ? AND b.user_id = ?
                            ORDER BY b.name
                        """, (creator_id, user_id))
                        brief_names = [row['name'] for row in cursor.fetchall()]
                        # Don't close the connection - it's managed by the database adapter

                        # Get social accounts
                        accounts = db.get_social_accounts(creator_id)
                        platforms = ', '.join(accounts['platform'].str.title().tolist()) if not accounts.empty else 'No platforms'

                        # Checkbox for selection
                        col_check, col_info = st.columns([0.5, 9.5])

                        with col_check:
                            is_selected = creator_id in st.session_state.selected_creators_for_analysis
                            if st.checkbox(f"Select {creator['name']}", value=is_selected, key=f"creator_select_{creator_id}", label_visibility="collapsed"):
                                st.session_state.selected_creators_for_analysis.add(creator_id)
                            else:
                                st.session_state.selected_creators_for_analysis.discard(creator_id)

                        with col_info:
                            st.markdown(f"**{creator['name']}**")
                            st.caption(f"📱 Platforms: {platforms}")

                            # Show brief associations
                            if len(brief_names) > 1:
                                other_briefs = [b for b in brief_names if b != selected_brief_name]
                                if other_briefs:
                                    st.caption(f"📄 Also in: {', '.join(other_briefs)}")

                st.markdown("---")

                # Filter selected creators
                selected_creator_ids = list(st.session_state.selected_creators_for_analysis)
                creators_to_analyze = creators_in_brief[creators_in_brief['id'].isin(selected_creator_ids)]

                if len(creators_to_analyze) == 0:
                    st.warning("⚠️ No creators selected. Please select at least one creator to analyze.")
                else:
                    st.success(f"✓ {len(creators_to_analyze)} creator(s) ready to analyze")

                    # Analysis configuration
                    st.markdown("### Analysis Configuration")

                    col_config1, col_config2 = st.columns(2)

                    with col_config1:
                        # Quarterly steps: 90, 180, 270, 365, 455, 545, 635, 730
                        time_range_options = [90, 180, 270, 365, 455, 545, 635, 730]
                        time_range_labels = ["3 months", "6 months", "9 months", "1 year", "15 months", "18 months", "21 months", "2 years"]

                        # Find closest default value or use 6 months
                        try:
                            default_index = time_range_options.index(DEFAULT_TIME_RANGE_DAYS)
                        except ValueError:
                            # If DEFAULT_TIME_RANGE_DAYS not in list, find closest
                            default_index = min(range(len(time_range_options)),
                                              key=lambda i: abs(time_range_options[i] - DEFAULT_TIME_RANGE_DAYS))

                        time_range_selection = st.select_slider(
                            "Time Range",
                            options=time_range_options,
                            value=time_range_options[default_index],
                            format_func=lambda x: time_range_labels[time_range_options.index(x)],
                            help="How far back to analyze posts"
                        )
                        time_range = time_range_selection

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

                    # Dynamic cost estimate
                    if len(creators_to_analyze) > 0:
                        # Get current user settings
                        model_id = db.get_setting(user_id, "model", DEFAULT_MODEL)
                        posts_for_analysis = int(db.get_setting(user_id, "posts_for_gemini_analysis", "20"))
                        max_videos = tier_info.get('max_videos_to_analyze', 0)

                        # Calculate dynamic estimate
                        cost_estimate = calculate_dynamic_cost_estimate(
                            tier_key=analysis_depth,
                            num_creators=len(creators_to_analyze),
                            model_id=model_id,
                            posts_for_analysis=posts_for_analysis,
                            max_videos_to_analyze=max_videos
                        )

                        # Display with breakdown
                        total_cost = cost_estimate['total']
                        per_creator_cost = total_cost / len(creators_to_analyze)

                        breakdown_text = format_cost_breakdown(cost_estimate, len(creators_to_analyze))

                        cost_info = f"""💰 **Estimated Cost**: {format_cost(total_cost)}
({len(creators_to_analyze)} creator(s) × {format_cost(per_creator_cost)} each)

**Cost Breakdown per Creator**:
{breakdown_text}"""

                        st.info(cost_info)
                        st.caption("💡 Estimates may vary based on actual content complexity")
                    else:
                        st.info("💰 **Estimated Cost**: Select creators to see cost estimate")

                    st.markdown("---")

                    # Run analysis button
                    if st.button("🚀 Run Analysis", type="primary", width='stretch'):
                        if not st.session_state.api_key:
                            st.error("⚠️ Gemini API Key required. Please configure in System Setup tab.")
                            st.stop()

                        # Check if we have YouTube creators and no API keys
                        has_youtube = False
                        for _, creator in creators_to_analyze.iterrows():
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

                            total_creators = len(creators_to_analyze)
                            successful_analyses = 0
                            failed_analyses = 0

                            for idx, (_, creator) in enumerate(creators_to_analyze.iterrows()):
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
                                            st.success(f"✅ {creator['name']}: Analysis complete (Score: {result['overall_metrics'].get('brand_fit_score', 'N/A')}/5.0)")
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
                # Add checkbox for deduplication
                show_only_latest = st.checkbox(
                    "Show only most recent report per creator",
                    value=True,
                    key="show_only_latest_reports",
                    help="When enabled, only the most recent report for each creator is shown. Turn off to see all historical reports."
                )

                # Filter to most recent per creator if checkbox is enabled
                if show_only_latest:
                    # Sort by generated_at descending to get most recent first
                    reports_df = reports_df.sort_values('generated_at', ascending=False)
                    # Keep only the first (most recent) report for each creator_id
                    reports_df = reports_df.drop_duplicates(subset='creator_id', keep='first')

                st.success(f"✓ {len(reports_df)} report(s) available")

                # Sort by overall score (descending)
                reports_df = reports_df.sort_values('overall_score', ascending=False)

                # Export complete brief report button
                st.markdown("### 📥 Export Complete Brief Report")
                st.caption(f"Download a comprehensive report including all {len(reports_df)} creator(s) with executive summary and comparison table")

                col1, col2, col3 = st.columns(3)

                # Markdown Export
                with col1:
                    if st.button("📄 Markdown", key="export_brief_md", width='stretch'):
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
                                width='stretch'
                            )

                        except Exception as e:
                            st.error(f"Failed to generate Markdown: {str(e)}")

                # PDF Export
                with col2:
                    if st.button("📕 PDF", key="export_brief_pdf", width='stretch'):
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
                                    width='stretch'
                                )
                            else:
                                st.error("Failed to generate PDF")

                        except Exception as e:
                            import traceback
                            st.error(f"Failed to generate PDF: {str(e)}")
                            print(f"[ERROR] PDF Export failed:\n{traceback.format_exc()}")

                # Excel Export
                with col3:
                    if st.button("📊 Excel", key="export_brief_excel", width='stretch'):
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
                                    width='stretch'
                                )
                            else:
                                st.error("Failed to generate Excel")

                        except Exception as e:
                            import traceback
                            st.error(f"Failed to generate Excel: {str(e)}")
                            print(f"[ERROR] Excel Export failed:\n{traceback.format_exc()}")

                st.markdown("---")

                # Visual Analytics Section
                st.markdown("### 📊 Portfolio Analytics")

                # Initialize visualizer
                viz = ReportVisualizer()

                # Create metrics cards
                col_metric1, col_metric2, col_metric3, col_metric4 = st.columns(4)

                total_reach = 0
                avg_score = 0
                platform_counts = {}

                # Calculate portfolio stats
                for _, report_row in reports_df.iterrows():
                    # Get creator info
                    creator_id = report_row['creator_id']
                    creator = db.get_creator(creator_id)

                    if creator:
                        # Get social accounts
                        social_accounts = db.get_social_accounts(creator_id)
                        for _, account in social_accounts.iterrows():
                            # Get latest analytics
                            analytics = db.get_latest_analytics(account['id'])
                            if analytics:
                                followers = analytics.get('followers_count', 0) or 0
                                total_reach += followers

                                platform = account['platform']
                                platform_counts[platform] = platform_counts.get(platform, 0) + 1

                avg_score = reports_df['overall_score'].mean() if not reports_df.empty else 0

                # Display metrics
                with col_metric1:
                    st.metric("Total Reach", f"{total_reach:,.0f}", help="Combined followers across all creators")

                with col_metric2:
                    st.metric("Avg Score", f"{avg_score:.1f}/5", help="Average brand safety score")

                with col_metric3:
                    st.metric("Creators", len(reports_df), help="Number of analyzed creators")

                with col_metric4:
                    st.metric("Platforms", len(platform_counts), help="Number of platforms covered")

                # Charts row
                col_chart1, col_chart2 = st.columns(2)

                with col_chart1:
                    # Score distribution histogram
                    scores = reports_df['overall_score'].tolist()
                    fig_scores = viz.create_score_distribution_histogram(scores)
                    st.plotly_chart(fig_scores, width='stretch')

                with col_chart2:
                    # Platform distribution pie chart
                    if platform_counts:
                        import plotly.graph_objects as go
                        fig_platforms = go.Figure(data=[go.Pie(
                            labels=list(platform_counts.keys()),
                            values=list(platform_counts.values()),
                            marker=dict(colors=['#2E86AB', '#06D6A0', '#F77F00', '#118AB2']),
                            hovertemplate='<b>%{label}</b><br>Creators: %{value}<br><extra></extra>'
                        )])
                        fig_platforms.update_layout(
                            title='Platform Distribution',
                            template='plotly_white'
                        )
                        st.plotly_chart(fig_platforms, width='stretch')

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
                                    width='stretch'
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
                                    width='stretch'
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
                                    width='stretch'
                                )

                            # Delete report button
                            st.markdown("---")
                            if st.button(f"🗑️ Delete Report", key=f"del_report_{report_row['id']}", type="secondary"):
                                if db.delete_creator_report(report_row['id'], user_id):
                                    st.success(f"✅ Report deleted: {report_row['creator_name']}")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("Failed to delete report")

                        except Exception as e:
                            st.error(f"Error generating report: {str(e)}")


# --- TAB: COMPARE ---
with tab_compare:
    st.header("Compare Creators")
    st.caption("Side-by-side comparison of multiple creators")

    # Import comparison engine
    from comparison_engine import ComparisonEngine

    # Select brief
    briefs_df = db.get_briefs(user_id)

    if briefs_df.empty:
        st.info("""
        📄 **No briefs yet**

        Create a brief and run analysis first to compare creators.
        """)
    else:
        selected_brief_name = st.selectbox(
            "Select Brief",
            briefs_df['name'].tolist(),
            key="compare_brief_select"
        )

        if selected_brief_name:
            brief_row = briefs_df[briefs_df['name'] == selected_brief_name].iloc[0]
            brief_id = int(brief_row['id'])

            # Get all creators for this brief
            creators_df = db.get_creators_for_brief(brief_id)

            if creators_df.empty:
                st.info("No creators in this brief. Add creators first.")
            else:
                # Multi-select creators to compare (max 5)
                st.markdown("### Select Creators to Compare (up to 5)")
                selected_creators = st.multiselect(
                    "Choose creators",
                    creators_df['name'].tolist(),
                    default=creators_df['name'].tolist()[:min(3, len(creators_df))],
                    max_selections=5,
                    key="compare_creators_select"
                )

                if not selected_creators:
                    st.warning("Please select at least 2 creators to compare")
                elif len(selected_creators) < 2:
                    st.warning("Please select at least 2 creators for comparison")
                else:
                    # Get creator IDs
                    creator_ids = []
                    for name in selected_creators:
                        creator_row = creators_df[creators_df['name'] == name].iloc[0]
                        creator_ids.append(int(creator_row['id']))

                    # Initialize comparison engine
                    comp_engine = ComparisonEngine(db)

                    # Run comparison
                    comparison = comp_engine.compare_creators(creator_ids, brief_id)

                    if 'error' in comparison:
                        st.error(comparison['error'])
                    else:
                        # Display summary metrics
                        st.markdown("### 📊 Comparison Summary")

                        col_sum1, col_sum2, col_sum3, col_sum4 = st.columns(4)

                        summary = comparison['metrics_summary']

                        with col_sum1:
                            st.metric("Total Reach", f"{summary.get('total_reach', 0):,.0f}")

                        with col_sum2:
                            st.metric("Avg Score", f"{summary.get('avg_overall_score', 0):.1f}/5")

                        with col_sum3:
                            st.metric("Avg Engagement", f"{summary.get('avg_engagement_rate', 0):.2f}%")

                        with col_sum4:
                            st.metric("Est. Cost", f"${summary.get('total_estimated_cost', 0):.2f}")

                        st.markdown("---")

                        # Comparison table
                        st.markdown("### 📋 Side-by-Side Comparison")

                        comparison_table = []
                        for creator_data in comparison['creators']:
                            comparison_table.append({
                                'Creator': creator_data['name'],
                                'Platforms': ', '.join(creator_data['platforms']),
                                'Followers': f"{creator_data['total_followers']:,.0f}",
                                'Engagement': f"{creator_data['avg_engagement_rate']:.2f}%",
                                'Score': f"{creator_data['overall_score']:.1f}/5",
                                'Brand Safety': f"{creator_data['brand_safety_score']:.1f}/5",
                                'Cost': f"${creator_data['estimated_cost']:.2f}"
                            })

                        comparison_df = pd.DataFrame(comparison_table)
                        st.dataframe(comparison_df, width='stretch', hide_index=True)

                        st.markdown("---")

                        # Visual comparisons
                        st.markdown("### 📈 Visual Comparison")

                        col_viz1, col_viz2 = st.columns(2)

                        with col_viz1:
                            # Bar chart: Overall scores
                            import plotly.graph_objects as go

                            fig_scores = go.Figure(data=[
                                go.Bar(
                                    x=[c['name'] for c in comparison['creators']],
                                    y=[c['overall_score'] for c in comparison['creators']],
                                    marker_color=['#06D6A0' if c['overall_score'] >= 4 else
                                                 '#F77F00' if c['overall_score'] >= 3 else
                                                 '#EF476F' for c in comparison['creators']],
                                    text=[f"{c['overall_score']:.1f}" for c in comparison['creators']],
                                    textposition='auto'
                                )
                            ])

                            fig_scores.update_layout(
                                title='Overall Scores Comparison',
                                xaxis_title='Creator',
                                yaxis_title='Score (out of 5)',
                                template='plotly_white',
                                yaxis=dict(range=[0, 5])
                            )

                            st.plotly_chart(fig_scores, width='stretch')

                        with col_viz2:
                            # Bar chart: Followers
                            fig_followers = go.Figure(data=[
                                go.Bar(
                                    x=[c['name'] for c in comparison['creators']],
                                    y=[c['total_followers'] for c in comparison['creators']],
                                    marker_color='#2E86AB',
                                    text=[f"{c['total_followers']:,.0f}" for c in comparison['creators']],
                                    textposition='auto'
                                )
                            ])

                            fig_followers.update_layout(
                                title='Total Followers Comparison',
                                xaxis_title='Creator',
                                yaxis_title='Followers',
                                template='plotly_white'
                            )

                            st.plotly_chart(fig_followers, width='stretch')

                        # Radar chart for brand safety dimensions
                        st.markdown("### 🎯 Multi-Dimensional Comparison")

                        # Create radar chart
                        from visualization import ReportVisualizer
                        viz = ReportVisualizer()

                        fig_radar = go.Figure()

                        categories = ['Overall Score', 'Brand Safety', 'Content Quality',
                                     'Audience Fit', 'Engagement Quality']

                        for creator_data in comparison['creators']:
                            values = [
                                creator_data['overall_score'],
                                creator_data['brand_safety_score'],
                                creator_data['content_quality_score'],
                                creator_data['audience_fit_score'],
                                creator_data['engagement_quality_score']
                            ]

                            # Close the radar
                            values_closed = values + [values[0]]
                            categories_closed = categories + [categories[0]]

                            fig_radar.add_trace(go.Scatterpolar(
                                r=values_closed,
                                theta=categories_closed,
                                fill='toself',
                                name=creator_data['name']
                            ))

                        fig_radar.update_layout(
                            polar=dict(
                                radialaxis=dict(visible=True, range=[0, 5])
                            ),
                            title='Brand Fit Dimensions',
                            template='plotly_white',
                            showlegend=True
                        )

                        st.plotly_chart(fig_radar, width='stretch')

                        st.markdown("---")

                        # Rankings section
                        st.markdown("### 🏆 Rankings")

                        col_rank1, col_rank2, col_rank3 = st.columns(3)

                        rankings = comparison['rankings']

                        with col_rank1:
                            st.markdown("**By Overall Score**")
                            for rank_data in rankings.get('overall_score', [])[:5]:
                                st.write(f"{rank_data['rank']}. {rank_data['name']} ({rank_data['value']:.1f})")

                        with col_rank2:
                            st.markdown("**By Followers**")
                            for rank_data in rankings.get('total_followers', [])[:5]:
                                st.write(f"{rank_data['rank']}. {rank_data['name']} ({rank_data['value']:,.0f})")

                        with col_rank3:
                            st.markdown("**By Engagement**")
                            for rank_data in rankings.get('avg_engagement_rate', [])[:5]:
                                st.write(f"{rank_data['rank']}. {rank_data['name']} ({rank_data['value']:.2f}%)")

                        st.markdown("---")

                        # ROI Calculator
                        with st.expander("💰 Campaign ROI Calculator", expanded=False):
                            st.markdown("Estimate the return on investment for a campaign with these creators")

                            col_roi1, col_roi2 = st.columns(2)

                            with col_roi1:
                                campaign_budget = st.number_input(
                                    "Campaign Budget ($)",
                                    min_value=0.0,
                                    value=10000.0,
                                    step=1000.0,
                                    key="roi_budget"
                                )

                            with col_roi2:
                                revenue_per_conversion = st.number_input(
                                    "Expected Revenue per Conversion ($)",
                                    min_value=0.0,
                                    value=100.0,
                                    step=10.0,
                                    key="roi_revenue_per_conversion"
                                )

                            if st.button("Calculate ROI", key="calc_roi"):
                                roi_data = comp_engine.estimate_campaign_roi(
                                    creator_ids, campaign_budget, revenue_per_conversion, brief_id
                                )

                                if 'error' not in roi_data:
                                    st.markdown("#### 📊 ROI Projections")

                                    col_roi_res1, col_roi_res2, col_roi_res3, col_roi_res4 = st.columns(4)

                                    with col_roi_res1:
                                        st.metric("Est. Impressions", f"{roi_data['estimated_impressions']:,.0f}")

                                    with col_roi_res2:
                                        st.metric("Est. Engagement", f"{roi_data['estimated_engagement']:,.0f}")

                                    with col_roi_res3:
                                        st.metric("Est. Conversions", f"{roi_data['estimated_conversions']:,.0f}")

                                    with col_roi_res4:
                                        roi_pct = roi_data['roi_percentage']
                                        roi_color = "normal" if roi_pct > 0 else "inverse"
                                        st.metric("ROI", f"{roi_pct:.1f}%", delta=None)

                                    st.markdown("---")

                                    st.info(f"""
                                    **Assumptions:**
                                    - Each creator posts 3 times
                                    - {roi_data['organic_reach_rate']:.0f}% organic reach per post
                                    - {roi_data['conversion_rate']:.1f}% of engaged users convert
                                    - Cost per impression: ${roi_data['cost_per_impression']:.4f}
                                    - Cost per engagement: ${roi_data['cost_per_engagement']:.2f}
                                    """)
                                else:
                                    st.error(roi_data['error'])


# --- TAB: CAMPAIGN ASSETS ---
with tab_assets:
    st.header("Campaign Assets")
    st.caption("Generate AI-powered campaign images and videos")

    # Import asset generator
    from asset_generator import AssetGenerator

    # Get API key from session state (same as other tabs)
    gemini_api_key = st.session_state.api_key

    if not gemini_api_key:
        st.warning("Please configure your Gemini API key in System Setup first.")
    else:
        # Initialize asset generator
        try:
            asset_gen = AssetGenerator(gemini_api_key, db)
        except Exception as e:
            st.error(f"Failed to initialize asset generator: {str(e)}")
            st.stop()

        # Select Brief
        briefs_df = db.get_briefs(user_id)

        if briefs_df.empty:
            st.info("Create a brief first to generate campaign assets.")
        else:
            selected_brief_name = st.selectbox(
                "Select Brief",
                briefs_df['name'].tolist(),
                key="assets_brief_select"
            )

            if selected_brief_name:
                brief_row = briefs_df[briefs_df['name'] == selected_brief_name].iloc[0]
                brief_id = int(brief_row['id'])
                brief = db.get_brief(brief_id)

                # Get creators for this brief
                creators_df = db.get_creators_for_brief(brief_id)

                if creators_df.empty:
                    st.info("No creators in this brief. Add creators first.")
                else:
                    # Select SINGLE Creator (dropdown, not multiselect)
                    selected_creator_name = st.selectbox(
                        "Select Creator",
                        [""] + creators_df['name'].tolist(),
                        key="assets_creator_select"
                    )

                    if selected_creator_name:
                        creator_row = creators_df[creators_df['name'] == selected_creator_name].iloc[0]
                        creator_id = int(creator_row['id'])
                        creator = db.get_creator(creator_id)

                        # Show creator context
                        st.markdown("---")
                        st.markdown("### 👤 Creator Context")

                        col_ctx1, col_ctx2, col_ctx3 = st.columns(3)

                        with col_ctx1:
                            st.metric("Primary Platform", creator['primary_platform'].title())

                        # Get social accounts
                        social_accounts_df = db.get_social_accounts(creator_id)
                        total_followers = 0
                        for _, acc in social_accounts_df.iterrows():
                            analytics = db.get_latest_analytics(acc['id'])
                            if analytics:
                                total_followers += analytics.get('followers_count', 0) or 0

                        with col_ctx2:
                            st.metric("Total Reach", f"{total_followers:,}")

                        # Get report if exists
                        report = db.get_creator_report(brief_id, creator_id)
                        if report:
                            with col_ctx3:
                                st.metric("Overall Score", f"{report['overall_score']:.1f}/5")

                            # Show brief summary
                            with st.expander("Analysis Summary", expanded=False):
                                st.markdown(report.get('summary', 'No summary available'))

                        st.markdown("---")

                        # Asset Generation Section
                        st.markdown("### 🎨 Generate Assets")

                        # Tabs for Image and Video
                        asset_tab_image, asset_tab_video = st.tabs(["📸 Campaign Image", "🎬 Campaign Video"])

                        # --- IMAGE GENERATION TAB ---
                        with asset_tab_image:
                            st.markdown("Generate a visual representation of the campaign concept featuring this creator with your brand.")

                            # Configuration
                            col_img1, col_img2 = st.columns(2)

                            with col_img1:
                                aspect_ratio = st.selectbox(
                                    "Aspect Ratio",
                                    ["16:9 (Landscape)", "1:1 (Square)", "9:16 (Portrait)", "4:3 (Standard)"],
                                    index=1,
                                    key="image_aspect_ratio"
                                )
                                aspect_ratio_value = aspect_ratio.split()[0]

                            with col_img2:
                                use_custom_prompt = st.checkbox("Customize prompt", key="use_custom_image_prompt")

                            # Show default prompt preview or custom input
                            custom_image_prompt = None
                            if not use_custom_prompt:
                                with st.expander("View Default Prompt", expanded=False):
                                    default_prompt = asset_gen.build_campaign_image_prompt(
                                        brief, creator, social_accounts_df.to_dict('records'), report
                                    )
                                    st.text_area("Default prompt:", default_prompt, height=150, disabled=True, key="default_img_prompt_display")
                            else:
                                custom_image_prompt = st.text_area(
                                    "Custom Image Prompt",
                                    height=150,
                                    key="custom_image_prompt",
                                    placeholder="Describe the campaign image you want to generate..."
                                )

                            # Cost estimate
                            from config import estimate_image_generation_cost
                            image_cost = estimate_image_generation_cost(1)
                            st.info(f"💰 Estimated cost: ${image_cost['total_cost']:.3f} per image")

                            # Generate button
                            if st.button("🎨 Generate Campaign Image", key="generate_image_btn", type="primary"):
                                prompt_to_use = custom_image_prompt if use_custom_prompt else None

                                progress_bar = st.progress(0)
                                status_text = st.empty()

                                def progress_callback(message, progress):
                                    status_text.text(message)
                                    progress_bar.progress(progress)

                                try:
                                    result = asset_gen.generate_campaign_image(
                                        user_id=user_id,
                                        brief_id=brief_id,
                                        creator_id=creator_id,
                                        custom_prompt=prompt_to_use,
                                        aspect_ratio=aspect_ratio_value,
                                        progress_callback=progress_callback
                                    )

                                    progress_bar.progress(1.0)
                                    status_text.text("✓ Generation complete!")

                                    st.success(f"Image generated successfully! Cost: ${result['cost']:.3f}")
                                    st.rerun()

                                except Exception as e:
                                    st.error(f"Generation failed: {str(e)}")

                            # Display generated images
                            st.markdown("---")
                            st.markdown("#### 📸 Generated Images")

                            assets_df = db.get_campaign_assets(
                                user_id=user_id,
                                brief_id=brief_id,
                                creator_id=creator_id,
                                asset_type='image'
                            )

                            if not assets_df.empty:
                                # Display in grid
                                cols_per_row = 2
                                for i in range(0, len(assets_df), cols_per_row):
                                    cols = st.columns(cols_per_row)
                                    for j, col in enumerate(cols):
                                        idx = i + j
                                        if idx < len(assets_df):
                                            asset = assets_df.iloc[idx]
                                            with col:
                                                if os.path.exists(asset['file_path']):
                                                    st.image(asset['file_path'], width='stretch')
                                                    # Handle both string (SQLite) and Timestamp (PostgreSQL) formats
                                                    created_date = asset['created_at']
                                                    if hasattr(created_date, 'strftime'):
                                                        created_date = created_date.strftime('%Y-%m-%d %H:%M')
                                                    else:
                                                        created_date = str(created_date)
                                                    st.caption(f"Generated: {created_date}")
                                                    st.caption(f"Cost: ${asset['cost']:.3f}")

                                                    col_btn1, col_btn2 = st.columns(2)
                                                    with col_btn1:
                                                        with open(asset['file_path'], 'rb') as f:
                                                            st.download_button(
                                                                "📥 Download",
                                                                f.read(),
                                                                file_name=f"campaign_image_{asset['id']}.png",
                                                                key=f"download_img_{asset['id']}"
                                                            )
                                                    with col_btn2:
                                                        if st.button("🗑️ Delete", key=f"delete_img_{asset['id']}"):
                                                            if db.delete_campaign_asset(user_id, asset['id']):
                                                                if os.path.exists(asset['file_path']):
                                                                    os.remove(asset['file_path'])
                                                                st.rerun()
                                                else:
                                                    st.warning(f"File not found: {asset['file_path']}")
                            else:
                                st.info("No images generated yet. Click 'Generate Campaign Image' to create one.")

                        # --- VIDEO GENERATION TAB ---
                        with asset_tab_video:
                            st.markdown("Generate campaign videos featuring creator stats, highlights, and concepts.")

                            # Video type selection
                            video_type = st.radio(
                                "Video Type",
                                ["Campaign Concept Visualization", "Creator Stats & Highlights"],
                                key="video_type_select"
                            )
                            video_type_value = "concept" if video_type.startswith("Campaign") else "stats"

                            # Configuration
                            col_vid1, col_vid2 = st.columns(2)

                            with col_vid1:
                                duration = st.slider(
                                    "Duration (seconds)",
                                    min_value=4,
                                    max_value=8,
                                    value=8,
                                    key="video_duration"
                                )

                            with col_vid2:
                                resolution = st.selectbox(
                                    "Resolution",
                                    ["720p", "1080p"],
                                    key="video_resolution"
                                )

                            use_custom_vid_prompt = st.checkbox("Customize prompt", key="use_custom_video_prompt")

                            # Show default prompt preview or custom input
                            custom_video_prompt = None
                            if not use_custom_vid_prompt:
                                with st.expander("View Default Prompt", expanded=False):
                                    # Build appropriate analytics dict
                                    analytics_data = {}
                                    for _, acc in social_accounts_df.iterrows():
                                        analytics = db.get_latest_analytics(acc['id'])
                                        if analytics:
                                            analytics_data[acc['platform']] = analytics

                                    default_vid_prompt = asset_gen.build_campaign_video_prompt(
                                        video_type_value,
                                        brief,
                                        creator,
                                        social_accounts_df.to_dict('records'),
                                        analytics_data,
                                        report
                                    )
                                    st.text_area("Default prompt:", default_vid_prompt, height=150, disabled=True, key="default_vid_prompt_display")
                            else:
                                custom_video_prompt = st.text_area(
                                    "Custom Video Prompt",
                                    height=150,
                                    key="custom_video_prompt",
                                    placeholder="Describe the campaign video you want to generate..."
                                )

                            # Cost estimate
                            from config import estimate_video_generation_cost
                            video_cost = estimate_video_generation_cost(duration)
                            st.info(f"💰 Estimated cost: ${video_cost['total_cost']:.2f} for {duration}s video")

                            # Generate button
                            generate_video_clicked = st.button("🎬 Generate Campaign Video", key="generate_video_btn", type="primary")

                            # Initialize session state
                            if 'video_generating' not in st.session_state:
                                st.session_state.video_generating = False

                            # Start generation on button click
                            if generate_video_clicked and not st.session_state.video_generating:
                                st.session_state.video_generating = True
                                st.rerun()

                            # Execute generation if flag is set
                            if st.session_state.video_generating:
                                prompt_to_use = custom_video_prompt if use_custom_vid_prompt else None

                                progress_bar = st.progress(0)
                                status_text = st.empty()

                                def video_progress_callback(message, progress):
                                    status_text.text(message)
                                    progress_bar.progress(progress)

                                try:
                                    st.warning("⏳ Video generation can take 2-5 minutes. Please wait...")

                                    result = asset_gen.generate_campaign_video(
                                        user_id=user_id,
                                        brief_id=brief_id,
                                        creator_id=creator_id,
                                        video_type=video_type_value,
                                        custom_prompt=prompt_to_use,
                                        duration_seconds=duration,
                                        resolution=resolution,
                                        progress_callback=video_progress_callback
                                    )

                                    progress_bar.progress(1.0)
                                    status_text.text("✓ Video generation complete!")

                                    st.success(f"Video generated successfully! Cost: ${result['cost']:.2f}")
                                    st.session_state.video_generating = False
                                    st.rerun()

                                except Exception as e:
                                    st.session_state.video_generating = False
                                    st.error(f"Video generation failed: {str(e)}")

                            # Display generated videos
                            st.markdown("---")
                            st.markdown("#### 🎬 Generated Videos")

                            video_assets_df = db.get_campaign_assets(
                                user_id=user_id,
                                brief_id=brief_id,
                                creator_id=creator_id,
                                asset_type='video'
                            )

                            if not video_assets_df.empty:
                                for idx, asset in video_assets_df.iterrows():
                                    if os.path.exists(asset['file_path']):
                                        col_v1, col_v2 = st.columns([2, 1])

                                        with col_v1:
                                            st.video(asset['file_path'])

                                        with col_v2:
                                            st.caption(f"**Type:** {asset['asset_subtype'].title()}")
                                            # Handle both string (SQLite) and Timestamp (PostgreSQL) formats
                                            created_date = asset['created_at']
                                            if hasattr(created_date, 'strftime'):
                                                created_date = created_date.strftime('%Y-%m-%d %H:%M')
                                            else:
                                                created_date = str(created_date)
                                            st.caption(f"**Generated:** {created_date}")
                                            st.caption(f"**Cost:** ${asset['cost']:.2f}")

                                            with open(asset['file_path'], 'rb') as f:
                                                st.download_button(
                                                    "📥 Download Video",
                                                    f.read(),
                                                    file_name=f"campaign_video_{asset['id']}.mp4",
                                                    key=f"download_vid_{asset['id']}"
                                                )

                                            if st.button("🗑️ Delete", key=f"delete_vid_{asset['id']}"):
                                                if db.delete_campaign_asset(user_id, asset['id']):
                                                    if os.path.exists(asset['file_path']):
                                                        os.remove(asset['file_path'])
                                                    if asset['thumbnail_path'] and os.path.exists(asset['thumbnail_path']):
                                                        os.remove(asset['thumbnail_path'])
                                                    st.rerun()

                                        st.markdown("---")
                                    else:
                                        st.warning(f"File not found: {asset['file_path']}")
                            else:
                                st.info("No videos generated yet. Click 'Generate Campaign Video' to create one.")

