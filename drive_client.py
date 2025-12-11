"""
Google Drive API client for UXR CUJ Analysis
Handles OAuth authentication and Drive operations
"""

import os
import io
import re
import json
import hmac
import hashlib
import base64
import streamlit as st
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import time
import random


class DriveAPIError(Exception):
    """Custom exception for Drive API errors"""
    pass


def _get_state_secret() -> str:
    """Get secret key for signing OAuth state tokens"""
    # Use Streamlit secrets if available, otherwise fall back to env var
    try:
        secret = st.secrets.get("oauth_state_secret", os.getenv("OAUTH_STATE_SECRET", "default-secret-key"))
        print(f"[OAuth Debug] Secret key from streamlit secrets: {repr(secret[:10])}... (length: {len(secret)})")
        return secret
    except Exception as e:
        secret = os.getenv("OAUTH_STATE_SECRET", "default-secret-key")
        print(f"[OAuth Debug] Secret key from env/default: {repr(secret[:10])}... (length: {len(secret)}) [Exception: {e}]")
        return secret


def _create_state_token(user_id: int, username: str) -> str:
    """
    Create a signed state token containing user authentication info

    Args:
        user_id: User ID
        username: Username

    Returns:
        Base64-encoded signed token
    """
    # Create payload with user info
    payload = {
        "user_id": user_id,
        "username": username,
        "timestamp": time.time()
    }

    # Convert to JSON
    payload_json = json.dumps(payload)
    payload_bytes = payload_json.encode('utf-8')

    # Create signature
    print(f"[OAuth Debug] [CREATE] Getting secret for signing...")
    secret = _get_state_secret()
    print(f"[OAuth Debug] [CREATE] Using secret: {repr(secret[:10])}... (length: {len(secret)})")
    print(f"[OAuth Debug] [CREATE] Payload to sign: {repr(payload_bytes[:50])}...")
    signature = hmac.new(
        secret.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).digest()
    print(f"[OAuth Debug] [CREATE] Generated signature: {base64.b64encode(signature).decode()[:32]}...")

    # Combine payload and signature with NULL byte delimiter (safe because NULL won't appear in JSON)
    token_bytes = payload_bytes + b'\x00' + signature

    # Base64 encode
    token = base64.urlsafe_b64encode(token_bytes).decode('utf-8')

    print(f"[OAuth Debug] Created state token for user_id={user_id}, username={username}")
    print(f"[OAuth Debug] Full created token: {token}")
    print(f"[OAuth Debug] Created token length: {len(token)}")

    return token


def _verify_state_token(token: str) -> Optional[Dict]:
    """
    Verify and decode a state token

    Args:
        token: Base64-encoded signed token

    Returns:
        Dictionary with user_id and username if valid, None otherwise
    """
    print(f"[OAuth Debug] Verifying state token: {token[:50]}...")

    try:
        # Base64 decode
        token_bytes = base64.urlsafe_b64decode(token.encode('utf-8'))

        # Split payload and signature on NULL byte delimiter
        parts = token_bytes.split(b'\x00', 1)
        if len(parts) != 2:
            print("[OAuth Debug] ❌ Invalid token format (missing signature)")
            return None

        payload_bytes, signature = parts
        print(f"[OAuth Debug] [VERIFY] Received signature: {base64.b64encode(signature).decode()[:32]}...")
        print(f"[OAuth Debug] [VERIFY] Payload to verify: {repr(payload_bytes[:50])}...")

        # Verify signature
        print(f"[OAuth Debug] [VERIFY] Getting secret for verification...")
        secret = _get_state_secret()
        print(f"[OAuth Debug] [VERIFY] Using secret: {repr(secret[:10])}... (length: {len(secret)})")
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).digest()
        print(f"[OAuth Debug] [VERIFY] Expected signature: {base64.b64encode(expected_signature).decode()[:32]}...")

        if not hmac.compare_digest(signature, expected_signature):
            print("[OAuth Debug] ❌ Signature verification failed")
            print(f"[OAuth Debug] ❌ Received:  {base64.b64encode(signature).decode()}")
            print(f"[OAuth Debug] ❌ Expected:  {base64.b64encode(expected_signature).decode()}")
            return None

        # Decode payload
        payload = json.loads(payload_bytes.decode('utf-8'))
        print(f"[OAuth Debug] ✅ Token decoded successfully: user_id={payload.get('user_id')}, username={payload.get('username')}")

        # Check timestamp (reject tokens older than 1 hour)
        token_age = time.time() - payload.get('timestamp', 0)
        if token_age > 3600:
            print(f"[OAuth Debug] ❌ Token expired (age: {token_age:.0f}s)")
            return None

        print(f"[OAuth Debug] ✅ Token valid (age: {token_age:.0f}s)")
        return payload

    except Exception as e:
        print(f"[OAuth Debug] ❌ Error verifying state token: {e}")
        return None


class DriveClient:
    """Google Drive API client with OAuth 2.0 authentication"""

    # OAuth scopes
    SCOPES = [
        'https://www.googleapis.com/auth/drive.readonly',  # Browse and download
        'https://www.googleapis.com/auth/drive.file'       # Upload files
    ]

    # Video MIME types to filter
    VIDEO_MIME_TYPES = [
        'video/mp4',
        'video/quicktime',
        'video/x-msvideo',
        'video/webm',
        'video/x-matroska',
        'video/x-flv'
    ]

    def __init__(self):
        """Initialize Drive client"""
        self.service = None

    @staticmethod
    def get_redirect_uri() -> str:
        """Get appropriate redirect URI based on environment"""
        # Check if running in Streamlit Cloud
        if os.getenv('STREAMLIT_RUNTIME_ENV') == 'cloud':
            return st.secrets.get("google_drive", {}).get("redirect_uri_prod", "http://localhost:8501")
        return st.secrets.get("google_drive", {}).get("redirect_uri", "http://localhost:8501")

    @staticmethod
    def create_oauth_flow() -> Flow:
        """Create OAuth flow from secrets"""
        client_config = {
            "web": {
                "client_id": st.secrets["google_drive"]["client_id"],
                "client_secret": st.secrets["google_drive"]["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [DriveClient.get_redirect_uri()]
            }
        }

        return Flow.from_client_config(
            client_config,
            scopes=DriveClient.SCOPES,
            redirect_uri=DriveClient.get_redirect_uri()
        )

    @staticmethod
    def credentials_to_dict(credentials: Credentials) -> Dict:
        """Convert credentials object to dictionary for session state"""
        return {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }

    @staticmethod
    def dict_to_credentials(creds_dict: Dict) -> Credentials:
        """Convert dictionary to credentials object"""
        return Credentials(**creds_dict)

    @staticmethod
    def get_auth_url(user_id: Optional[int] = None, username: Optional[str] = None) -> Tuple[Flow, str]:
        """
        Get authorization URL for OAuth flow

        Args:
            user_id: Current user's ID to preserve in OAuth state
            username: Current user's username to preserve in OAuth state

        Returns:
            Tuple of (Flow, auth_url)
        """
        print(f"[OAuth Debug] Generating auth URL for user_id={user_id}, username={username}")

        flow = DriveClient.create_oauth_flow()

        # Create state token with user info if provided
        state = None
        if user_id is not None and username:
            state = _create_state_token(user_id, username)
            print(f"[OAuth Debug] State token will be included in OAuth URL")
        else:
            print(f"[OAuth Debug] ⚠️  No user info provided, state token will not be created")

        auth_url, _ = flow.authorization_url(
            prompt='consent',
            access_type='offline',  # Request refresh token
            include_granted_scopes='true',
            state=state  # Pass user info in state parameter
        )

        print(f"[OAuth Debug] Auth URL generated (contains state={state is not None})")
        return flow, auth_url

    @staticmethod
    def parse_drive_url(url: str) -> Optional[Tuple[str, str]]:
        """
        Parse Google Drive URL to extract file/folder ID and type

        Supported URL formats:
        - https://drive.google.com/file/d/{id}/view
        - https://drive.google.com/drive/folders/{id}
        - https://drive.google.com/open?id={id}
        - https://drive.google.com/drive/u/0/folders/{id}

        Args:
            url: Google Drive URL

        Returns:
            Tuple of (id, type) where type is 'file' or 'folder', or None if invalid
        """
        if not url or not isinstance(url, str):
            return None

        # Pattern for file URLs
        file_pattern = r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)'
        # Pattern for folder URLs
        folder_pattern = r'drive\.google\.com/(?:drive/)?(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)'
        # Pattern for open?id= URLs (could be file or folder)
        open_pattern = r'drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)'

        # Try file pattern
        match = re.search(file_pattern, url)
        if match:
            return (match.group(1), 'file')

        # Try folder pattern
        match = re.search(folder_pattern, url)
        if match:
            return (match.group(1), 'folder')

        # Try open pattern (assume file by default)
        match = re.search(open_pattern, url)
        if match:
            return (match.group(1), 'file')

        return None

    @staticmethod
    def exchange_code_for_token(code: str) -> Dict:
        """Exchange authorization code for access token"""
        try:
            flow = DriveClient.create_oauth_flow()
            flow.fetch_token(code=code)
            return DriveClient.credentials_to_dict(flow.credentials)
        except Exception as e:
            raise DriveAPIError(f"Failed to exchange code for token: {str(e)}")

    @staticmethod
    def refresh_credentials(creds_dict: Dict) -> Dict:
        """Refresh expired credentials"""
        credentials = DriveClient.dict_to_credentials(creds_dict)

        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                return DriveClient.credentials_to_dict(credentials)
            except Exception as e:
                raise DriveAPIError(f"Failed to refresh credentials: {str(e)}")

        return creds_dict

    def initialize_service(self, creds_dict: Dict):
        """Initialize Drive service with credentials"""
        try:
            # Refresh if needed
            creds_dict = self.refresh_credentials(creds_dict)
            credentials = self.dict_to_credentials(creds_dict)

            # Build service
            self.service = build('drive', 'v3', credentials=credentials)

            # Update session state with refreshed credentials
            if 'drive_credentials' in st.session_state:
                st.session_state.drive_credentials = creds_dict

        except Exception as e:
            raise DriveAPIError(f"Failed to initialize Drive service: {str(e)}")

    @staticmethod
    def exponential_backoff_retry(func, max_retries=5):
        """Execute function with exponential backoff retry logic"""
        retry_count = 0

        while retry_count < max_retries:
            try:
                return func()

            except HttpError as error:
                if error.resp.status in [403, 429]:
                    # Rate limit exceeded
                    retry_count += 1
                    if retry_count >= max_retries:
                        raise DriveAPIError(f"Rate limit exceeded after {max_retries} retries")

                    wait_time = min((2 ** retry_count) + random.random(), 64)
                    time.sleep(wait_time)

                elif error.resp.status in [500, 502, 503, 504]:
                    # Server errors
                    retry_count += 1
                    if retry_count >= max_retries:
                        raise DriveAPIError(f"Server error after {max_retries} retries")

                    wait_time = min((2 ** retry_count), 32)
                    time.sleep(wait_time)

                else:
                    # Non-retryable error
                    raise DriveAPIError(f"Drive API error: {error}")

        raise DriveAPIError(f"Max retries ({max_retries}) exceeded")

    def list_files(self, page_size: int = 100, query: Optional[str] = None,
                   page_token: Optional[str] = None) -> Dict:
        """
        List files in Drive with optional filtering

        Args:
            page_size: Number of files to return (max 1000)
            query: Query string for filtering (e.g., "mimeType contains 'video/'")
            page_token: Token for pagination

        Returns:
            Dictionary with 'files' list and optional 'nextPageToken'
        """
        if not self.service:
            raise DriveAPIError("Drive service not initialized")

        def _list():
            params = {
                'pageSize': min(page_size, 1000),
                'fields': 'nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)',
                'orderBy': 'modifiedTime desc'
            }

            if query:
                params['q'] = query

            if page_token:
                params['pageToken'] = page_token

            return self.service.files().list(**params).execute()

        try:
            return self.exponential_backoff_retry(_list)
        except Exception as e:
            raise DriveAPIError(f"Failed to list files: {str(e)}")

    def list_video_files(self, page_size: int = 50, folder_id: Optional[str] = None,
                        search_query: Optional[str] = None, recursive: bool = False) -> List[Dict]:
        """
        List video files from Drive with optional folder filtering and search

        Args:
            page_size: Number of files to return
            folder_id: Optional folder ID to search within (None = root)
            search_query: Optional search query for filename
            recursive: If True, search all subfolders

        Returns:
            List of video file dictionaries
        """
        # Build query for video files
        mime_query = " or ".join([f"mimeType='{mime}'" for mime in self.VIDEO_MIME_TYPES])
        query_parts = [f"({mime_query})"]

        # Add folder constraint if specified
        if folder_id and not recursive:
            query_parts.append(f"'{folder_id}' in parents")

        # Add search query if specified
        if search_query:
            query_parts.append(f"name contains '{search_query}'")

        # Combine all query parts
        query = " and ".join(query_parts)

        try:
            results = self.list_files(page_size=page_size, query=query)
            return results.get('files', [])
        except Exception as e:
            raise DriveAPIError(f"Failed to list video files: {str(e)}")

    def list_folders(self, parent_folder_id: Optional[str] = None, page_size: int = 50) -> List[Dict]:
        """
        List folders in Drive

        Args:
            parent_folder_id: Optional parent folder ID (None = root)
            page_size: Number of folders to return

        Returns:
            List of folder dictionaries
        """
        query = "mimeType='application/vnd.google-apps.folder'"

        if parent_folder_id:
            query += f" and '{parent_folder_id}' in parents"

        try:
            results = self.list_files(page_size=page_size, query=query)
            return results.get('files', [])
        except Exception as e:
            raise DriveAPIError(f"Failed to list folders: {str(e)}")

    def get_folder_path(self, folder_id: str) -> List[Dict]:
        """
        Get the full path of a folder (breadcrumb trail)

        Args:
            folder_id: Folder ID to get path for

        Returns:
            List of folder dictionaries from root to current folder
        """
        if not self.service:
            raise DriveAPIError("Drive service not initialized")

        path = []
        current_id = folder_id

        try:
            while current_id:
                folder = self.service.files().get(
                    fileId=current_id,
                    fields='id, name, parents'
                ).execute()

                path.insert(0, {'id': folder['id'], 'name': folder.get('name', 'Unknown')})

                # Get parent folder if exists
                parents = folder.get('parents', [])
                current_id = parents[0] if parents else None

            return path
        except Exception as e:
            # If we can't get full path, just return what we have
            return path

    def download_file(self, file_id: str, destination_path: str,
                      progress_callback=None) -> bool:
        """
        Download file from Drive to local storage

        Args:
            file_id: Google Drive file ID
            destination_path: Local path to save file
            progress_callback: Optional callback function(progress_percent)

        Returns:
            True if successful
        """
        if not self.service:
            raise DriveAPIError("Drive service not initialized")

        try:
            # Get file metadata
            file_metadata = self.service.files().get(
                fileId=file_id,
                fields="name, size"
            ).execute()

            file_name = file_metadata.get('name', 'unknown')
            file_size = int(file_metadata.get('size', 0))

            # Create request
            request = self.service.files().get_media(fileId=file_id)

            # Download with progress
            with open(destination_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=10*1024*1024)

                done = False
                while not done:
                    status, done = downloader.next_chunk()

                    if status and progress_callback:
                        progress = int(status.progress() * 100)
                        progress_callback(progress)

            return True

        except HttpError as error:
            raise DriveAPIError(f"Failed to download file: {error}")
        except Exception as e:
            raise DriveAPIError(f"Failed to download file: {str(e)}")

    def upload_file(self, file_path: str, file_name: Optional[str] = None,
                    folder_id: Optional[str] = None,
                    progress_callback=None) -> Dict:
        """
        Upload file to Drive

        Args:
            file_path: Local path to file
            file_name: Optional custom name for Drive
            folder_id: Optional Drive folder ID
            progress_callback: Optional callback function(progress_percent)

        Returns:
            Dictionary with file metadata (id, name, webViewLink)
        """
        if not self.service:
            raise DriveAPIError("Drive service not initialized")

        if not os.path.exists(file_path):
            raise DriveAPIError(f"File not found: {file_path}")

        try:
            # Prepare metadata
            file_metadata = {
                'name': file_name or os.path.basename(file_path)
            }

            if folder_id:
                file_metadata['parents'] = [folder_id]

            # Determine MIME type
            if file_path.endswith('.csv'):
                mime_type = 'text/csv'
            elif file_path.endswith('.json'):
                mime_type = 'application/json'
            else:
                mime_type = 'application/octet-stream'

            # Get file size
            file_size = os.path.getsize(file_path)

            # Use resumable upload for files > 5MB
            if file_size > 5 * 1024 * 1024:
                media = MediaFileUpload(
                    file_path,
                    mimetype=mime_type,
                    resumable=True,
                    chunksize=5*1024*1024
                )

                request = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, name, webViewLink'
                )

                response = None
                while response is None:
                    try:
                        status, response = request.next_chunk()
                        if status and progress_callback:
                            progress = int(status.progress() * 100)
                            progress_callback(progress)
                    except HttpError as error:
                        if error.resp.status in [500, 502, 503, 504]:
                            time.sleep(2)
                        else:
                            raise

                return response

            else:
                # Simple upload for small files
                media = MediaFileUpload(file_path, mimetype=mime_type)

                file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, name, webViewLink'
                ).execute()

                if progress_callback:
                    progress_callback(100)

                return file

        except HttpError as error:
            raise DriveAPIError(f"Failed to upload file: {error}")
        except Exception as e:
            raise DriveAPIError(f"Failed to upload file: {str(e)}")

    def get_file_metadata(self, file_id: str) -> Dict:
        """Get metadata for a specific file"""
        if not self.service:
            raise DriveAPIError("Drive service not initialized")

        try:
            return self.service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, size, modifiedTime, webViewLink, videoMediaMetadata"
            ).execute()
        except HttpError as error:
            raise DriveAPIError(f"Failed to get file metadata: {error}")


# Helper functions for Streamlit integration

def is_drive_authenticated() -> bool:
    """Check if user is authenticated with Drive"""
    return 'drive_credentials' in st.session_state


def get_drive_client() -> Optional[DriveClient]:
    """Get initialized Drive client or None if not authenticated"""
    if not is_drive_authenticated():
        return None

    try:
        client = DriveClient()
        client.initialize_service(st.session_state.drive_credentials)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Drive client: {e}")
        return None


def handle_drive_oauth_callback():
    """
    Handle OAuth callback from Google Drive

    This function:
    1. Checks for OAuth callback parameters (code, state)
    2. Restores user authentication from state token if present
    3. Exchanges authorization code for access token
    4. Stores Drive credentials in session
    """
    query_params = st.query_params

    print(f"[OAuth Debug] Callback handler called. Query params: {list(query_params.keys())}")

    if 'code' in query_params:
        print("[OAuth Debug] 🔄 OAuth callback detected (code parameter present)")

        try:
            # Restore user authentication from state token if present
            if 'state' in query_params:
                print("[OAuth Debug] State parameter found in callback")
                state_token = query_params['state']
                print(f"[OAuth Debug] Raw state token from query params: {repr(state_token)}")
                print(f"[OAuth Debug] State token length: {len(state_token)}")
                print(f"[OAuth Debug] Full token: {state_token}")
                user_data = _verify_state_token(state_token)

                if user_data:
                    print(f"[OAuth Debug] 🔐 Restoring authentication for user_id={user_data['user_id']}, username={user_data['username']}")

                    # Restore authentication session
                    st.session_state.authenticated = True
                    st.session_state.user_id = user_data['user_id']
                    st.session_state.username = user_data['username']

                    # Get additional user info from database if needed
                    from storage import get_db
                    db = get_db()
                    user = db.get_user_by_username(user_data['username'])
                    if user:
                        st.session_state.user_email = user.get('email')
                        st.session_state.user_full_name = user.get('full_name', '')
                        print(f"[OAuth Debug] ✅ Authentication restored successfully")
                    else:
                        print(f"[OAuth Debug] ⚠️  User not found in database")
                else:
                    print("[OAuth Debug] ❌ State token verification failed")
                    st.warning("Session expired. Please log in again.")
            else:
                print("[OAuth Debug] ⚠️  No state parameter in callback - authentication will NOT be restored")

            # Exchange code for token
            print("[OAuth Debug] Exchanging authorization code for access token...")
            credentials = DriveClient.exchange_code_for_token(query_params['code'])

            # Store in session state
            st.session_state.drive_credentials = credentials
            print("[OAuth Debug] ✅ Drive credentials stored in session")

            # Clear query params
            st.query_params.clear()
            print("[OAuth Debug] Query params cleared, triggering rerun...")
            st.rerun()

        except Exception as e:
            print(f"[OAuth Debug] ❌ Exception during OAuth callback: {e}")
            st.error(f"Drive authentication failed: {e}")
            return False

    return True


def logout_drive():
    """Logout from Drive (clear credentials)"""
    if 'drive_credentials' in st.session_state:
        del st.session_state.drive_credentials
