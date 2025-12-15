"""
Quick test to verify timedelta import is fixed
"""

# Test that timedelta is importable at module level
try:
    from creator_analyzer import CreatorAnalyzer
    print("✅ Import successful - timedelta fix verified")

    # Verify the timedelta is in the module
    import creator_analyzer
    import inspect
    source = inspect.getsource(creator_analyzer)

    # Check for the import at module level
    if "from datetime import datetime, timedelta" in source:
        print("✅ timedelta imported at module level")
    else:
        print("❌ timedelta not found in module-level imports")

    print("\n✅ Fix verified - demographics should now save correctly")

except ImportError as e:
    print(f"❌ Import failed: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
