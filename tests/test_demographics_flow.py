"""
Test script to verify demographics fetch works correctly without blocking main analysis
"""

import sys
from storage import DatabaseManager
from creator_analyzer import CreatorAnalyzer

def test_main_analysis_non_blocking():
    """Test that main analysis completes quickly without demographics fetch"""
    print("\n" + "=" * 80)
    print("TEST 1: Main Analysis (Should complete quickly)")
    print("=" * 80)

    db = DatabaseManager()
    analyzer = CreatorAnalyzer(db)

    # Get first creator
    creators = db.get_creators(user_id=1)
    if creators.empty:
        print("❌ No creators found - please add a creator first")
        return False

    creator_id = creators.iloc[0]['id']
    creator_name = creators.iloc[0]['name']

    print(f"\nTesting with creator: {creator_name} (ID: {creator_id})")
    print(f"Analysis tier: deep_research")
    print(f"Expected behavior: Should complete in < 60 seconds, skipping demographics fetch")

    # Create a brief for testing
    brief_id = db.create_brief(
        user_id=1,
        brand_name="Test Brand",
        campaign_goal="Test Campaign",
        target_audience="Test Audience",
        key_messages=["Test message"],
        brand_values=["Test value"],
        content_guidelines="Test guidelines"
    )

    print(f"\nCreated test brief ID: {brief_id}")
    print("\nStarting analysis...")
    print("-" * 80)

    import time
    start_time = time.time()

    try:
        result = analyzer.analyze_creator(
            creator_id=creator_id,
            brief_id=brief_id,
            analysis_depth="deep_research"
        )

        elapsed = time.time() - start_time

        print("\n" + "-" * 80)
        print(f"✅ Analysis completed in {elapsed:.1f} seconds")

        if elapsed > 120:
            print("⚠️  WARNING: Analysis took longer than expected")
            print("   This suggests demographics fetch may be blocking")
            return False
        else:
            print("✅ PASS: Analysis completed quickly (no blocking)")

        # Check if report was created
        if result.get('report_id'):
            print(f"✅ Report created with ID: {result['report_id']}")
        else:
            print("❌ No report ID in result")
            return False

        return True

    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_standalone_demographics_fetch():
    """Test standalone demographics fetch method"""
    print("\n\n" + "=" * 80)
    print("TEST 2: Standalone Demographics Fetch")
    print("=" * 80)

    db = DatabaseManager()
    analyzer = CreatorAnalyzer(db)

    # Get first creator
    creators = db.get_creators(user_id=1)
    if creators.empty:
        print("❌ No creators found")
        return False

    creator_id = creators.iloc[0]['id']
    creator_name = creators.iloc[0]['name']

    print(f"\nTesting demographics fetch for: {creator_name} (ID: {creator_id})")
    print(f"Expected behavior: Will take 5-30 minutes depending on Deep Research")
    print(f"Note: This test will actually wait for completion to verify it works")

    user_input = input("\nThis will make actual API calls. Continue? (y/n): ")
    if user_input.lower() != 'y':
        print("Skipped - user chose not to run")
        return None

    print("\nStarting demographics fetch...")
    print("This may take several minutes...")
    print("-" * 80)

    import time
    start_time = time.time()

    try:
        results = analyzer.fetch_demographics_for_creator(
            creator_id=creator_id,
            analysis_depth="deep_research"
        )

        elapsed = time.time() - start_time

        print("\n" + "-" * 80)
        print(f"✅ Demographics fetch completed in {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")

        # Check results
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        print(f"\nResults: {success_count}/{total_count} platforms successful")
        for platform, success in results.items():
            status = "✅" if success else "❌"
            print(f"  {status} {platform}")

        if success_count > 0:
            print("\n✅ PASS: Demographics fetched successfully")

            # Verify data was saved to database
            accounts = db.get_social_accounts(creator_id)
            saved_count = 0
            for _, account in accounts.iterrows():
                demo_data = db.get_demographics_data(account['id'])
                if demo_data:
                    saved_count += 1
                    print(f"  ✅ {account['platform']}: Demographics found in database")

            if saved_count > 0:
                print(f"\n✅ PASS: Demographics saved to database ({saved_count} platforms)")
                return True
            else:
                print("\n❌ FAIL: No demographics found in database")
                return False
        else:
            print("\n⚠️  No demographics were fetched")
            return False

    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_diagnostics():
    """Test the diagnostics functionality"""
    print("\n\n" + "=" * 80)
    print("TEST 3: Demographics Diagnostics")
    print("=" * 80)

    db = DatabaseManager()

    # Get all creators
    creators = db.get_creators(user_id=1)
    if creators.empty:
        print("❌ No creators found")
        return False

    print(f"\nAnalyzing demographics coverage for {len(creators)} creator(s)")
    print("-" * 80)

    total_accounts = 0
    accounts_with_demographics = 0

    for _, creator in creators.iterrows():
        print(f"\n{creator['name']}:")
        accounts = db.get_social_accounts(creator['id'])

        for _, account in accounts.iterrows():
            total_accounts += 1
            demo_data = db.get_demographics_data(account['id'])

            platform = account['platform'].title()
            if demo_data:
                accounts_with_demographics += 1
                print(f"  ✅ {platform}: Has demographics")
                print(f"     - Data source: {demo_data.get('data_source', 'Unknown')}")
                print(f"     - Snapshot: {demo_data.get('snapshot_date', 'N/A')}")
            else:
                print(f"  ❌ {platform}: No demographics")

    print("\n" + "-" * 80)
    coverage_pct = (accounts_with_demographics / total_accounts * 100) if total_accounts > 0 else 0
    print(f"Coverage: {accounts_with_demographics}/{total_accounts} accounts ({coverage_pct:.1f}%)")

    return True


if __name__ == "__main__":
    print("\n🧪 BrandSafe Demographics Flow Testing")
    print("=" * 80)

    # Test 1: Main analysis should be non-blocking
    test1_passed = test_main_analysis_non_blocking()

    # Test 2: Standalone demographics fetch (optional - takes long time)
    test2_result = test_standalone_demographics_fetch()

    # Test 3: Diagnostics
    test3_passed = test_diagnostics()

    # Summary
    print("\n\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Test 1 (Non-blocking analysis): {'✅ PASS' if test1_passed else '❌ FAIL'}")
    print(f"Test 2 (Demographics fetch):    {'✅ PASS' if test2_result is True else '⚠️  SKIPPED' if test2_result is None else '❌ FAIL'}")
    print(f"Test 3 (Diagnostics):            {'✅ PASS' if test3_passed else '❌ FAIL'}")
    print("=" * 80)
