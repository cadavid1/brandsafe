# Deep Research: Automatic Demographics Fetch

## What Changed

Deep Research tier now **automatically fetches demographics** after saving the report.

## New Behavior

### When you select "Deep Research" tier:

**Phase 1: Fast Analysis (< 60 seconds)**
1. Fetch social stats and posts
2. Analyze content with Gemini
3. Generate and save report
4. **Report is immediately available in UI** ✅

**Phase 2: Demographics Fetch (5-30 minutes)**
5. Automatically starts demographics fetch
6. Makes Deep Research API calls for each platform
7. Saves demographics to database cache (90 days)
8. Future reports automatically include demographics

## User Experience

### First Time Running Deep Research on a Creator

**Timeline:**
```
0:00 - Start analysis
0:60 - ✅ Report saved and visible in UI
       📊 "Report is already saved and available"
       ⏳ "Fetching demographics... this may take 5-30 minutes"
5:00 - ✅ Demographics fetched and cached
```

**You can:**
- View the initial report immediately (after ~60 seconds)
- Navigate away / close browser - fetch continues in background
- Check terminal logs to see fetch progress

### Second Time Running Analysis (Any Tier)

**Timeline:**
```
0:00 - Start analysis
0:60 - ✅ Report saved with demographics included
```

**Why faster:**
- Demographics are cached from previous fetch (90 days)
- No need to fetch again
- Works with ANY tier (Quick/Standard/Comprehensive/Deep Research)

## Code Changes

### File: `creator_analyzer.py`

**Lines 371-396: Added automatic fetch after report save**
```python
# Fetch demographics if Deep Research tier (after report is saved)
if tier_config.get('deep_research', False):
    print(f"\n[DEMOGRAPHICS] Deep Research tier detected - fetching demographics...")
    print(f"[INFO] This may take 5-30 minutes. Report is already saved and available.")
    print(f"[INFO] Demographics will be added when fetch completes.\n")

    try:
        demo_results = self.fetch_demographics_for_creator(
            creator_id=creator_id,
            analysis_depth=analysis_depth
        )

        # Count successes
        success_count = sum(1 for v in demo_results.values() if v)
        total_count = len(demo_results)

        if success_count > 0:
            print(f"\n[DEMOGRAPHICS] Successfully fetched for {success_count}/{total_count} platforms")
            print(f"[INFO] Demographics cached for 90 days")
        else:
            print(f"\n[DEMOGRAPHICS] Failed to fetch demographics for any platform")
            print(f"[INFO] Check logs above for errors")

    except Exception as e:
        print(f"\n[DEMOGRAPHICS] Error during fetch: {type(e).__name__}: {e}")
        print(f"[INFO] Report is still valid, demographics can be fetched later via Settings")
```

**Lines 265-272: Updated messaging during data fetch**
```python
# Check for cached demographics (used in reports)
if tier_config.get('deep_research', False):
    demographics = self.db.get_demographics_data(account_id)
    if demographics:
        platform_stats[platform]['demographics'] = demographics
        print(f"  [INFO] Using cached demographics data")
    else:
        print(f"  [INFO] No cached demographics - will fetch after report is saved")
```

## Expected Terminal Output

### First Deep Research Analysis (No Cache)

```
[STEP 3/5] Fetching platform data...

[PLATFORM] Processing YOUTUBE...
  [SUCCESS] Followers: 72300000, Posts: 241
  [INFO] No cached demographics - will fetch after report is saved

[STEP 4/6] Analyzing content with Gemini AI...
  [SUCCESS] Content analysis complete

[SAVING] Saving report to database...
  [SUCCESS] Report saved with ID: 23

============================================================
[ANALYSIS COMPLETE] Creator: Mark Rober
  Overall Score: 4.8/5.0
  Analysis Cost: $0.1384
============================================================

[DEMOGRAPHICS] Deep Research tier detected - fetching demographics...
[INFO] This may take 5-30 minutes. Report is already saved and available.
[INFO] Demographics will be added when fetch completes.

[DEMOGRAPHICS FETCH] Starting for Mark Rober
============================================================

[PLATFORM] YOUTUBE
  [DEEP RESEARCH] Fetching demographics for Mark Rober on youtube...
  [DEEP RESEARCH] Research started, ID: v1_xxx...
  [DEEP RESEARCH] Status: in_progress, elapsed: 0s
  ...
  [DEEP RESEARCH] Status: completed
  [SUCCESS] Demographics research completed
  [DB] Updated demographics for platform_analytics id=7

[PLATFORM] INSTAGRAM
  ...

[PLATFORM] TIKTOK
  ...

[DEMOGRAPHICS] Successfully fetched for 3/3 platforms
[INFO] Demographics cached for 90 days
```

### Second Analysis (With Cache)

```
[STEP 3/5] Fetching platform data...

[PLATFORM] Processing YOUTUBE...
  [SUCCESS] Followers: 72300000, Posts: 241
  [INFO] Using cached demographics data

[PLATFORM] Processing INSTAGRAM...
  [SUCCESS] Followers: 2979168, Posts: 579
  [INFO] Using cached demographics data

...

[ANALYSIS COMPLETE] Creator: Mark Rober
  Overall Score: 4.8/5.0
  Analysis Cost: $0.1384
============================================================

(No demographics fetch - using cache)
```

## Benefits

✅ **One-step process:** Just select Deep Research and everything happens automatically
✅ **No blocking:** Initial report appears in ~60 seconds
✅ **Automatic caching:** Demographics cached for 90 days
✅ **Error handling:** If fetch fails, report is still valid
✅ **Progress visibility:** Terminal logs show detailed progress
✅ **Cost efficient:** Only fetches once per 90 days per creator

## What If Fetch Fails?

If demographics fetch encounters errors:
- ✅ Your report is still saved and valid
- ✅ Terminal shows error details
- ✅ You can manually retry via Settings → "Fetch Demographics Now"
- ✅ Or just run Deep Research again later

## Manual Fetch Still Available

If you want to fetch demographics without running full analysis:
1. Go to **Settings** → **Demographics Debug**
2. Click **"Run Demographics Diagnostics"** to check coverage
3. Click **"Fetch Demographics Now"** to manually fetch
4. Select creator and confirm

## Cache Duration

- **Default:** 90 days
- **Configurable:** Edit `deep_research_cache_days` in config.py
- **Check cache age:** Use Demographics Diagnostics in Settings

## API Costs

- **Deep Research API:** ~$0.40 per query (per platform)
- **Example:** 3 platforms = ~$1.20 per creator
- **Cached for:** 90 days (no repeat cost)
- **Total with analysis:** ~$0.14 (analysis) + ~$1.20 (demographics) = ~$1.34 per new creator

## Testing

To test the new behavior:
1. Restart Streamlit completely (to load new code)
2. Select a creator without cached demographics
3. Choose "Deep Research" tier
4. Observe:
   - Report appears in ~60 seconds
   - Demographics fetch starts automatically
   - Terminal shows fetch progress
   - Future analyses include demographics

## Troubleshooting

**Issue:** Demographics not fetching
**Check:**
- Terminal logs for errors
- Gemini API key configured in Settings
- Demographics debug mode enabled to see detailed logs

**Issue:** Taking longer than expected
**Normal:** Deep Research can take 5-30 minutes per creator
- Check terminal for "Status: in_progress"
- Each platform is processed sequentially
- You can close browser - fetch continues

**Issue:** Fetch failed with timedelta error
**Solution:** Make sure you've restarted Streamlit completely (not just rerun)
- Kill the Streamlit process
- Start fresh: `streamlit run app.py`

## Summary

Deep Research now works as you'd expect:
- Select the tier
- Get your report quickly
- Demographics fetch automatically
- Future reports include the data

No more manual button clicking or separate steps!
