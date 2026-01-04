"""
Test script for database connection retry logic
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from storage import get_db
import config

def test_connection_health():
    """Test basic connection health check"""
    print("=" * 60)
    print("Testing Database Connection Health")
    print("=" * 60)

    db = get_db()

    print(f"\nDatabase Type: {config.DATABASE_TYPE}")
    print(f"Connection alive: {db.db_adapter.is_connection_alive()}")

    # Test a simple query
    try:
        result = db.get_setting(user_id=1, key="test_key", default="no_value")
        print(f"[OK] Successfully executed test query")
        print(f"  Result: {result}")
    except Exception as e:
        print(f"[ERROR] Query failed: {e}")

    print("\n" + "=" * 60)

def test_connection_refresh():
    """Test connection refresh mechanism"""
    print("=" * 60)
    print("Testing Connection Refresh")
    print("=" * 60)

    db = get_db()

    # First refresh (should not actually refresh, too soon)
    print("\n1. Testing initial refresh (should skip)...")
    db.refresh_connection_if_needed(refresh_interval_seconds=300)

    # Force refresh by setting interval to 0
    print("\n2. Testing forced refresh (interval=0)...")
    db.refresh_connection_if_needed(refresh_interval_seconds=0)

    # Verify connection still works
    print("\n3. Verifying connection still works...")
    try:
        result = db.get_setting(user_id=1, key="test_key", default="default")
        print(f"[OK] Connection working after refresh")
    except Exception as e:
        print(f"[ERROR] Connection failed after refresh: {e}")

    print("\n" + "=" * 60)

def test_retry_logic():
    """Test database operation retry logic"""
    print("=" * 60)
    print("Testing Retry Logic")
    print("=" * 60)

    db = get_db()

    print("\n1. Testing normal query with retry wrapper...")
    try:
        # This uses the retry wrapper internally
        result = db.get_setting(user_id=1, key="test_key", default="default")
        print(f"[OK] Query succeeded: {result}")
    except Exception as e:
        print(f"[ERROR] Query failed: {e}")

    print("\n2. Testing connection ensure...")
    try:
        db.db_adapter.ensure_connection()
        print(f"[OK] Connection ensured successfully")
        print(f"  Connection alive: {db.db_adapter.is_connection_alive()}")
    except Exception as e:
        print(f"[ERROR] Failed to ensure connection: {e}")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("DATABASE CONNECTION RETRY TEST SUITE")
    print("=" * 60 + "\n")

    try:
        test_connection_health()
        test_connection_refresh()
        test_retry_logic()

        print("\n" + "=" * 60)
        print("[SUCCESS] ALL TESTS COMPLETED")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n[FAILED] TEST SUITE FAILED: {e}")
        import traceback
        traceback.print_exc()
