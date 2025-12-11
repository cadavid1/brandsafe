"""
Authentication module for UXR CUJ Analysis
Handles user registration, login, and session management
"""

import streamlit as st
import bcrypt
import uuid
from storage import get_db
from typing import Optional, Tuple


class AuthManager:
    """Manages user authentication and session state"""

    def __init__(self):
        self.db = get_db()
        self._init_session_state()

    def _init_session_state(self):
        """Initialize authentication session state"""
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False
        if 'user_id' not in st.session_state:
            st.session_state.user_id = None
        if 'username' not in st.session_state:
            st.session_state.username = None
        if 'user_email' not in st.session_state:
            st.session_state.user_email = None

    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify a password against its hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

    def register_user(self, email: str, username: str, password: str, full_name: str = "") -> Tuple[bool, str]:
        """
        Register a new user

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Validate inputs
        if not username or not password:
            return False, "Username and password are required"

        if len(password) < 6:
            return False, "Password must be at least 6 characters"

        # Check if user already exists
        if email and self.db.get_user_by_email(email):
            return False, "Email already registered"

        if self.db.get_user_by_username(username):
            return False, "Username already taken"

        # Hash password and create user
        password_hash = self.hash_password(password)
        user_id = self.db.create_user(email or None, username, password_hash, full_name)

        if user_id:
            return True, "Registration successful! Please log in."
        else:
            return False, "Registration failed. Please try again."

    def login(self, username: str, password: str) -> Tuple[bool, str]:
        """
        Authenticate a user

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not username or not password:
            return False, "Username and password required"

        # Get user from database
        user = self.db.get_user_by_username(username)

        if not user:
            return False, "Invalid username or password"

        # Verify password
        if not self.verify_password(password, user['password_hash']):
            return False, "Invalid username or password"

        # Set session state
        st.session_state.authenticated = True
        st.session_state.user_id = user['id']
        st.session_state.username = user['username']
        st.session_state.user_email = user['email']
        st.session_state.user_full_name = user.get('full_name', '')

        # Update last login
        self.db.update_last_login(user['id'])

        return True, f"Welcome back, {user['username']}!"

    def demo_login(self) -> Tuple[bool, str]:
        """
        Create a demo session with unique ID
        Demo users get full functionality but no data persistence

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Generate unique demo session ID
        demo_session_id = f"demo_{uuid.uuid4().hex[:8]}"

        # Set session state for demo mode
        st.session_state.authenticated = True
        st.session_state.is_demo_mode = True
        st.session_state.user_id = demo_session_id
        st.session_state.username = "Demo User"
        st.session_state.user_email = "demo@example.com"
        st.session_state.user_full_name = "Demo User"

        return True, "Welcome to the demo! Your data will not be saved."

    def logout(self):
        """Log out the current user and clear all user-specific data"""
        # Clear authentication
        st.session_state.authenticated = False
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.user_email = None
        st.session_state.user_full_name = None

        # Clear user-specific data to prevent data leakage between users
        user_data_keys = [
            'api_key',
            'selected_model',
            'system_prompt',
            'cujs',
            'videos',
            'results',
            'db_synced',
            'welcome_shown',
            'processed_files',
            'cuj_video_mapping',
            'show_cleanup_dialog',
            'selected_videos',
            'drive_current_folder',
            'drive_search_query',
            'drive_link_file_id'
        ]

        for key in user_data_keys:
            if key in st.session_state:
                del st.session_state[key]

    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        return st.session_state.get('authenticated', False)

    def is_demo_mode(self) -> bool:
        """Check if current session is in demo mode"""
        return st.session_state.get('is_demo_mode', False)

    def get_current_user_id(self) -> Optional[int]:
        """Get the current user's ID"""
        return st.session_state.get('user_id')

    def get_current_username(self) -> Optional[str]:
        """Get the current user's username"""
        return st.session_state.get('username')

    def require_auth(self):
        """
        Require authentication - show login/register UI if not authenticated
        Returns True if authenticated, False otherwise
        """
        if self.is_authenticated():
            return True

        # Show authentication UI
        self.show_auth_ui()
        return False

    def show_auth_ui(self):
        """Display login/register UI"""
        # Note: Page config is set in app.py before auth check

        # Header
        st.title("🧪 UXR CUJ Analysis")
        st.markdown("**AI-Powered User Journey Analysis**")
        st.markdown("---")

        # Demo mode button (prominent placement)
        st.info("👋 **New here?** Try the app without creating an account")
        if st.button("🎭 Try Demo Mode", type="primary", use_container_width=True):
            success, message = self.demo_login()
            if success:
                st.success(message)
                st.rerun()

        st.markdown("---")

        # Tab selection
        auth_tab = st.radio(
            "Select an option",
            ["Login", "Register"],
            horizontal=True,
            label_visibility="collapsed"
        )

        if auth_tab == "Login":
            self._show_login_form()
        else:
            self._show_register_form()

        # Footer
        st.markdown("---")
        st.caption("🔒 Your data is private and secure. Each user has isolated access to their own data.")

    def _show_login_form(self):
        """Show login form"""
        st.header("Login")

        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submit = st.form_submit_button("Login", type="primary", use_container_width=True)

            if submit:
                success, message = self.login(username, password)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    def _show_register_form(self):
        """Show registration form"""
        st.header("Register")

        with st.form("register_form"):
            username = st.text_input("Username", key="register_username")
            password = st.text_input("Password", type="password", key="register_password")
            password_confirm = st.text_input("Confirm Password", type="password", key="register_password_confirm")
            email = st.text_input("Email (optional)", key="register_email")
            full_name = st.text_input("Full Name (optional)", key="register_full_name")

            submit = st.form_submit_button("Register", type="primary", use_container_width=True)

            if submit:
                # Validate passwords match
                if password != password_confirm:
                    st.error("Passwords do not match")
                else:
                    success, message = self.register_user(email, username, password, full_name)
                    if success:
                        st.success(message)
                        st.info("👈 Please use the Login tab to sign in")
                    else:
                        st.error(message)

    def show_user_info_sidebar(self):
        """Display user info in sidebar"""
        if self.is_authenticated():
            st.sidebar.markdown("---")
            st.sidebar.markdown("### 👤 Account")
            st.sidebar.caption(f"**{st.session_state.username}**")
            if st.session_state.get('user_full_name'):
                st.sidebar.caption(st.session_state.user_full_name)
            st.sidebar.caption(st.session_state.user_email)

            if st.sidebar.button("Logout", use_container_width=True):
                self.logout()
                st.rerun()


# Singleton instance
_auth_instance = None


def get_auth() -> AuthManager:
    """Get singleton auth manager instance"""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = AuthManager()
    return _auth_instance
