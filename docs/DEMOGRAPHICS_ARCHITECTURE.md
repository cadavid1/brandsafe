# Demographics Data Architecture

## Overview

BrandSafe's demographics system fetches audience demographic data (age, gender, geography) for creators using Google's Gemini Deep Research API. This document explains the architecture, design decisions, and how to use the system.

## Key Design Decision: Non-Blocking Architecture

### The Problem
Gemini Deep Research API is an autonomous research agent that can take **5-30 minutes** to complete a single query. If demographics fetching ran during the main creator analysis, it would:
- Block the UI for extended periods
- Cause browser timeouts
- Create a poor user experience
- Multiply delays when analyzing multiple creators

### The Solution
We implemented a **two-phase architecture**:

1. **Phase 1: Fast Analysis** (Main `analyze_creator()` method)
   - Completes in < 60 seconds
   - Fetches social stats, posts, engagement data
   - Runs Gemini content analysis
   - **Skips demographics fetch** to avoid blocking
   - Uses cached demographics if available (90-day cache)

2. **Phase 2: Background Demographics** (Separate `fetch_demographics_for_creator()` method)
   - Runs separately/asynchronously
   - Takes 5-30 minutes per creator
   - Can be triggered manually or scheduled
   - Saves results to database for future analyses

## Architecture Components

### 1. Database Layer (`storage.py`)

**Demographics Storage:**
- Stored in `platform_analytics.demographics_data` as JSON
- One record per social account (platform-specific)
- Includes metadata: data_source, snapshot_date, data_confidence

**Key Methods:**
```python
save_demographics_data(social_account_id, demographics)
get_demographics_data(social_account_id) -> Optional[Dict]
```

**Caching Strategy:**
- 90-day cache by default
- Two-level caching:
  1. Platform analytics cache (demographics data)
  2. Deep research queries cache (to avoid duplicate API calls)

### 2. Creator Analyzer (`creator_analyzer.py`)

**Main Analysis Method:**
```python
analyze_creator(creator_id, brief_id, analysis_depth)
```
- Runs fast analysis (< 60 seconds)
- Checks for cached demographics
- Skips demographics fetch to avoid blocking
- Returns report immediately

**Standalone Demographics Method:**
```python
fetch_demographics_for_creator(creator_id, analysis_depth="deep_research") -> Dict[str, bool]
```
- Designed for separate/async execution
- Fetches demographics for all platforms
- Returns success/failure per platform
- Saves results to database

**Demographics Fetching Logic:**
```python
_get_demographics_data(creator_name, social_account_id, platform, profile_url, tier_config)
```
- Checks cache first (90-day threshold)
- Queries Deep Research API if needed
- Parses and validates response
- Saves to database with verification

### 3. Deep Research Client (`deep_research_client.py`)

**API Request Format:**
```json
{
  "agent": "agent-id",
  "input": {
    "type": "text",
    "text": "query text"
  },
  "background": true
}
```

**Two-Step Process:**
1. **Start Research** (`start_research()`)
   - Sends query to API
   - Returns interaction ID immediately
   - Research runs in background

2. **Poll for Results** (`poll_research()`)
   - Polls status every 5-30 seconds
   - Waits for status: "in_progress" → "completed"
   - Extracts result when done
   - Timeout: 30 minutes max

**Status Flow:**
```
"pending" → "in_progress" → "completed" | "failed"
```

### 4. Report Generator (`report_generator.py`)

**Demographics Usage:**
- Reads from `platform_analytics.demographics_data`
- Includes in report if available
- Gracefully handles missing data
- Logs checks when debug mode enabled

## Analysis Tiers

Only the **Deep Research** tier fetches demographics:

| Tier | Demographics? | Speed | Use Case |
|------|--------------|-------|----------|
| Quick | ❌ | Fast | Quick overview |
| Standard | ❌ | Fast | Basic analysis |
| Comprehensive | ❌ | Fast | Detailed analysis |
| Deep Research | ✅ | Slow | Full demographic data |

## User Interface Features

### 1. Demographics Debug Mode (`app.py`)

**Enable in Settings:**
```
☑️ Enable Demographics Debug Logging
```

**Features:**
- Detailed terminal logging
- Tracks data flow through all layers
- Shows cache hits/misses
- Logs API calls and results

### 2. Demographics Diagnostics

**Button:** "🔍 Run Demographics Diagnostics"

**Shows:**
- Total social accounts
- Accounts with demographics
- Coverage percentage
- Detailed table per creator/platform
- Data source and snapshot date
- Gender/Age/Geography availability

**Recommendations:**
- Alerts for low coverage
- Instructions on how to fix missing data

### 3. Manual Demographics Fetch

**Button:** "🚀 Fetch Demographics Now"

**Features:**
- Select specific creator
- Triggers standalone demographics fetch
- Shows progress in UI
- Takes 5-30 minutes
- Updates database when complete

## Usage Patterns

### Pattern 1: Initial Creator Analysis
```python
# Fast analysis without demographics
analyzer.analyze_creator(
    creator_id=123,
    brief_id=456,
    analysis_depth="comprehensive"  # Fast tiers
)
# Returns immediately with report
```

### Pattern 2: Full Analysis with Demographics
```python
# Step 1: Fast analysis
result = analyzer.analyze_creator(
    creator_id=123,
    brief_id=456,
    analysis_depth="deep_research"  # Uses cached if available
)

# Step 2: Fetch demographics separately (if needed)
demo_results = analyzer.fetch_demographics_for_creator(
    creator_id=123,
    analysis_depth="deep_research"
)
# Takes 5-30 minutes, saves to DB

# Step 3: Re-run analysis to include new demographics
result = analyzer.analyze_creator(
    creator_id=123,
    brief_id=456,
    analysis_depth="deep_research"
)
# Now includes demographics from cache
```

### Pattern 3: Manual UI Fetch
1. Go to Settings → Demographics Debug
2. Click "Run Demographics Diagnostics"
3. Review coverage
4. Select creator with missing demographics
5. Click "Fetch Demographics Now"
6. Wait for completion (check terminal logs)
7. Refresh page to see updated data

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    MAIN ANALYSIS FLOW                       │
│                     (Fast, < 60 sec)                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ analyze_creator()                                             │
│  ├── Fetch social stats                                       │
│  ├── Fetch posts                                              │
│  ├── Run Gemini content analysis                              │
│  └── Check demographics cache ────────────┐                   │
│      ├── If cached: Use it               │                   │
│      └── If not: Skip (no blocking)      │                   │
└──────────────────────────────────────────┼────────────────────┘
                                          │
                                          ▼
                            ┌──────────────────────────┐
                            │   Return Report ID       │
                            │   (with or without demo) │
                            └──────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              BACKGROUND DEMOGRAPHICS FLOW                   │
│                 (Slow, 5-30 min per creator)                │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ fetch_demographics_for_creator()                              │
│  └── For each platform:                                       │
│      └── _get_demographics_data()                             │
│          ├── Check cache (90 days)                            │
│          ├── If expired: Query Deep Research API              │
│          │   ├── start_research() → interaction_id            │
│          │   └── poll_research() → wait for completion        │
│          ├── Parse JSON response                              │
│          ├── Validate data                                    │
│          └── save_demographics_data()                         │
└───────────────────────────────────────────────────────────────┘
                            │
                            ▼
            ┌────────────────────────────────┐
            │  Demographics in DB Cache      │
            │  (Available for future use)    │
            └────────────────────────────────┘
```

## Debugging & Troubleshooting

### Enable Debug Logging
1. Go to Settings
2. Check "Enable Demographics Debug Logging"
3. Watch terminal output for detailed logs

### Debug Log Format
```
[HH:MM:SS] [DEMOGRAPHICS] Message
```

### Common Issues

**Issue 1: "No demographics in reports"**
- Solution: Use "Deep Research" tier, not other tiers
- Or: Manually fetch demographics via UI button

**Issue 2: "Demographics fetch is slow"**
- Expected: Deep Research takes 5-30 minutes
- This is normal API behavior
- Consider pre-fetching demographics for important creators

**Issue 3: "API errors during fetch"**
- Check: Gemini API key is configured
- Check: Terminal logs for specific error
- Check: API quota/limits

**Issue 4: "Cached demographics are stale"**
- Current: 90-day cache threshold
- Solution: Data will auto-refresh after 90 days
- Or: Manually re-fetch via UI

### Verification Checklist

✅ **Before Analysis:**
1. Demographics debug mode enabled?
2. Gemini API key configured?
3. Using "Deep Research" tier?

✅ **After Analysis:**
1. Check terminal logs for demographics tracking
2. Run diagnostics to verify coverage
3. Confirm data in database: `get_demographics_data(account_id)`

✅ **For Missing Demographics:**
1. Run diagnostics to identify gaps
2. Use manual fetch button for specific creators
3. Check terminal logs for errors
4. Verify API key and quota

## Testing

### Automated Tests
```bash
python test_demographics_flow.py
```

**Test Suite:**
1. **Test 1:** Main analysis non-blocking (< 120 sec)
2. **Test 2:** Standalone demographics fetch (5-30 min)
3. **Test 3:** Diagnostics coverage report

### Manual Testing
1. Create a test creator with social accounts
2. Run analysis with "Deep Research" tier
3. Verify main analysis completes quickly
4. Check if cached demographics were used
5. If not, manually fetch demographics
6. Verify data appears in next analysis

## Performance Considerations

### API Costs
- Deep Research API: $0.40 per query
- Each platform = 1 query
- Cache reduces repeat costs

### Timing
- Fast analysis: < 60 seconds
- Demographics fetch: 5-30 minutes per creator
- Cache hit: No additional time

### Recommendations
1. Pre-fetch demographics for important creators
2. Use lower tiers for quick checks
3. Reserve Deep Research for final analysis
4. Leverage 90-day cache effectively

## Future Improvements

**Potential Enhancements:**
1. True async/background job system (Celery, RQ)
2. Progress tracking UI for long-running fetches
3. Batch demographics fetching for multiple creators
4. Configurable cache duration
5. Demographics refresh scheduling
6. API quota monitoring and alerts

## API Documentation

**Official Docs:**
- [Gemini Deep Research API](https://ai.google.dev/gemini-api/docs/deep-research)

**Endpoint:**
```
POST https://generativelanguage.googleapis.com/v1alpha/interactions
GET  https://generativelanguage.googleapis.com/v1alpha/interactions/{id}
```

**Authentication:**
```
X-Goog-Api-Key: YOUR_API_KEY
```
