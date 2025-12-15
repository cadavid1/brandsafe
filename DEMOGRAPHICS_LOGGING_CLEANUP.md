# Demographics Logging Cleanup

## Problem

The demographics logging was way too verbose, causing spam in the terminal:

```
[DEMOGRAPHICS] Checking demographics for youtube account_id=7
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for instagram account_id=8
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for tiktok account_id=9
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for youtube account_id=7
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for instagram account_id=8
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for tiktok account_id=9
[DEMOGRAPHICS] ❌ No demographics found
```

This happened because:
1. Report generation checks demographics for every platform
2. Streamlit reruns pages frequently
3. Debug logs printed on every check

## Solution

Made logging more elegant and contextual:

### 1. Report Generator (report_generator.py)

**Before:**
```python
demographics = self.db.get_demographics_data(account['id'])
_debug_log(f"[DEMOGRAPHICS] Checking demographics for {account['platform']} account_id={account['id']}")
if demographics:
    _debug_log(f"[DEMOGRAPHICS] ✓ Found demographics: {list(demographics.keys())}")
    demographics_data[account['platform']] = demographics
else:
    _debug_log(f"[DEMOGRAPHICS] ❌ No demographics found")
```

**After:**
```python
# Get demographics data for this platform (silently)
demographics = self.db.get_demographics_data(account['id'])
if demographics:
    demographics_data[account['platform']] = demographics

# Log demographics summary (only if debug mode is on)
if demographics_data:
    platforms_with_demo = ', '.join(demographics_data.keys())
    _debug_log(f"[REPORT] Using demographics for: {platforms_with_demo}")
else:
    _debug_log(f"[REPORT] No demographics available for this report")
```

**Changes:**
- ❌ Removed per-platform logging spam
- ✅ Added single summary log after collecting all demographics
- ✅ Only logs once per report generation
- ✅ More useful: shows which platforms have data

### 2. Expected Output

**Old (Spammy):**
```
[DEMOGRAPHICS] Checking demographics for youtube account_id=7
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for instagram account_id=8
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for tiktok account_id=9
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for youtube account_id=7
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for instagram account_id=8
[DEMOGRAPHICS] ❌ No demographics found
[DEMOGRAPHICS] Checking demographics for tiktok account_id=9
[DEMOGRAPHICS] ❌ No demographics found
```

**New (Clean):**
```
[REPORT] No demographics available for this report
```

Or if demographics exist:
```
[REPORT] Using demographics for: youtube, instagram, tiktok
```

### 3. Debug Mode Still Works

When demographics debug mode is enabled in Settings, you'll still see:
- ✅ Detailed logs during actual demographics **fetching**
- ✅ API calls and status updates
- ✅ Save confirmations
- ✅ Cache hit/miss info
- ❌ **Not** spammy repeated checks during report viewing

## Context-Aware Logging

The logging now distinguishes between:

### Fetching (Verbose - Important)
```
[DEMOGRAPHICS FETCH] Starting for Mark Rober
[PLATFORM] YOUTUBE
  [DEEP RESEARCH] Fetching demographics...
  [DEEP RESEARCH] Status: in_progress, elapsed: 5s
  [DEEP RESEARCH] Status: completed
  [SUCCESS] Demographics research completed
  [DB] Updated demographics for platform_analytics id=7
```

### Report Generation (Quiet - Not Important)
```
[REPORT] Using demographics for: youtube, instagram
```

### Diagnostics (Summary - Useful)
```
[DEMOGRAPHICS] Successfully fetched for 3/3 platforms
[INFO] Demographics cached for 90 days
```

## Benefits

✅ **Much cleaner terminal output**
✅ **One-line summary instead of repeated spam**
✅ **Still shows important info when fetching**
✅ **Debug mode works correctly**
✅ **Better user experience**

## Files Changed

### report_generator.py (Lines 124-155)

**Removed:**
- Per-platform check logging
- Repeated "no demographics found" messages

**Added:**
- Single summary log after collecting all data
- Contextual `[REPORT]` prefix

## Testing

After restarting Streamlit:
1. ✅ View any report - you'll see one summary log (if debug enabled)
2. ✅ Fetch demographics - you'll see detailed progress
3. ✅ No more spam when navigating between pages
4. ✅ Terminal output is clean and readable

## Summary

Demographics logging is now:
- **Quiet during normal use** (report viewing)
- **Verbose during fetching** (when you need details)
- **Summarized when useful** (one-line status)
- **Context-aware** (different prefixes for different operations)

No more spam! 🎉
