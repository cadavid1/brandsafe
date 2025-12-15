"""
Simple test to verify demographics fetch works outside of Streamlit
"""

import sys
import os
import importlib

# Add parent directory to path so we can import modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Force reload of modules to get latest code changes
if 'creator_analyzer' in sys.modules:
    del sys.modules['creator_analyzer']
if 'deep_research_client' in sys.modules:
    del sys.modules['deep_research_client']

from storage import DatabaseManager
from creator_analyzer import CreatorAnalyzer

def test_fetch():
    print("\n" + "=" * 80)
    print("TESTING DEMOGRAPHICS FETCH DIRECTLY")
    print("=" * 80)

    db = DatabaseManager()

    # Get Gemini API key from settings
    # Try common key names
    gemini_api_key = db.get_setting(user_id=1, key="api_key", default="")
    if not gemini_api_key:
        gemini_api_key = db.get_setting(user_id=1, key="gemini_api_key", default="")
    if not gemini_api_key:
        gemini_api_key = db.get_setting(user_id=1, key="google_api_key", default="")

    if not gemini_api_key:
        print("❌ ERROR: Gemini API key not configured")
        print("Please set your Gemini API key in Settings first")
        return

    print(f"✅ Found Gemini API key (length: {len(gemini_api_key)})")

    analyzer = CreatorAnalyzer(gemini_api_key)

    # Get all creators and show them
    creators = db.get_creators(user_id=1)
    if creators.empty:
        print("❌ No creators found")
        return

    print("\nAvailable creators:")
    for idx, creator in creators.iterrows():
        print(f"  ID: {creator['id']}, Name: {creator['name']}")

    creator_id = creators.iloc[0]['id']
    creator_name = creators.iloc[0]['name']

    print(f"\nFetching demographics for: {creator_name} (ID: {creator_id})")

    # Debug: Check what's actually in the database
    print("\n[DEBUG] Querying database directly...")
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM creators")
    rows = cursor.fetchall()
    print(f"[DEBUG] All creators in database:")
    for row in rows:
        print(f"  ID: {row['id']}, Name: {row['name']}")
    conn.close()

    # Debug: Check if get_creator works
    print(f"\n[DEBUG] Now calling get_creator({creator_id})...")
    test_creator = db.get_creator(creator_id)
    print(f"Debug - get_creator({creator_id}) returns: {test_creator}")

    if not test_creator:
        print("❌ ERROR: get_creator() returned None")
        return

    # Check social accounts
    print(f"\n[DEBUG] Checking social accounts for creator {creator_id}...")
    accounts = db.get_social_accounts(creator_id)
    print(f"[DEBUG] Found {len(accounts)} social accounts:")
    for _, account in accounts.iterrows():
        print(f"  - Platform: {account['platform']}, ID: {account['id']}, URL: {account['profile_url']}")

    if accounts.empty:
        print("❌ ERROR: No social accounts found for this creator")
        return

    print(f"\nThis will make actual Deep Research API calls\n")

    # This should print "[DEMOGRAPHICS FETCH] Starting for {name}"
    results = analyzer.fetch_demographics_for_creator(
        creator_id=creator_id,
        analysis_depth="deep_research"
    )

    print("\n" + "=" * 80)
    print("RESULTS:")
    print("=" * 80)
    for platform, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{status}: {platform}")

if __name__ == "__main__":
    test_fetch()
