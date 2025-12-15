# Demographics Data Flow Verification

## ✅ Data Flow is Correct

I've verified the complete data flow from save to display. Everything is correctly connected.

## Complete Data Flow

### 1. Save Path (Deep Research → Database)

**When demographics are fetched:**
```python
# creator_analyzer.py line 806
save_demographics_data(social_account_id, demographics)
    ↓
# storage.py line 2009
def save_demographics_data(social_account_id, demographics):
    ↓
# Saves to: platform_analytics table
# Field: demographics_data (TEXT/JSON)
# Key: social_account_id
```

**SQL in `save_demographics_data()`:**
```sql
-- Updates existing record OR creates new one
UPDATE platform_analytics
SET demographics_data = ?
WHERE id = ?

-- OR

INSERT INTO platform_analytics (
    social_account_id,
    snapshot_date,
    demographics_data,
    data_source
) VALUES (?, date('now'), ?, 'deep_research')
```

### 2. Retrieve Path (Database → Diagnostics)

**When diagnostics button is clicked:**
```python
# app.py line 703
demo_data = db.get_demographics_data(account['id'])
    ↓
# storage.py line 2055
def get_demographics_data(social_account_id):
    ↓
# Reads from: platform_analytics table
# Field: demographics_data (TEXT/JSON)
# Key: social_account_id
```

**SQL in `get_demographics_data()`:**
```sql
SELECT demographics_data, snapshot_date
FROM platform_analytics
WHERE social_account_id = ?
AND demographics_data IS NOT NULL
AND demographics_data != ''
AND demographics_data != '{}'
ORDER BY snapshot_date DESC
LIMIT 1
```

### 3. Display Path (Diagnostics Table)

**Fields displayed in diagnostics table (app.py lines 707-729):**

| Column | Source | Notes |
|--------|--------|-------|
| Creator | `creator['name']` | From creators table |
| Platform | `account['platform']` | From social_accounts table |
| Has Demographics | '✅ Yes' or '❌ No' | Based on demo_data existence |
| Data Source | `demo_data.get('data_source')` | From demographics JSON |
| Snapshot Date | `demo_data.get('snapshot_date')` | From demographics JSON |
| Data Confidence | `demo_data.get('data_confidence')` | From demographics JSON |
| Has Gender | Check `demo_data.get('gender')` | From demographics JSON |
| Has Age | Check `demo_data.get('age_brackets')` | From demographics JSON |
| Has Geography | Check `demo_data.get('geography')` | From demographics JSON |

## Database Schema Verification

### platform_analytics Table
```sql
CREATE TABLE IF NOT EXISTS platform_analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    social_account_id INTEGER NOT NULL,
    snapshot_date DATE NOT NULL,
    followers_count INTEGER,
    following_count INTEGER,
    total_posts INTEGER,
    avg_likes REAL,
    avg_comments REAL,
    avg_shares REAL,
    engagement_rate REAL,
    demographics_data TEXT,        -- ✅ This field stores demographics JSON
    raw_data TEXT,
    data_source TEXT,
    FOREIGN KEY (social_account_id) REFERENCES social_accounts(id)
)
```

## Data Structure in demographics_data Field

**JSON Structure (as defined in creator_analyzer.py line 838):**
```json
{
  "gender": {
    "female": <number>,
    "male": <number>,
    "other": <number>
  },
  "age_brackets": {
    "13-17": <number>,
    "18-24": <number>,
    "25-34": <number>,
    "35-44": <number>,
    "45-54": <number>,
    "55-64": <number>,
    "65+": <number>
  },
  "geography": [
    {"country": "US", "percentage": <number>},
    {"country": "<country>", "percentage": <number>}
  ],
  "languages": [
    {"language": "<language>", "percentage": <number>}
  ],
  "interests": ["interest1", "interest2", ...],
  "data_confidence": "high" | "medium" | "low",
  "data_source": "deep_research",
  "snapshot_date": "2024-01-01",
  "collected_at": "2024-01-01T12:00:00",
  "sources": [
    {"source": "source name/URL", "data_points": ["gender", "age"]}
  ],
  "notes": "Any additional context",
  "raw_text": "Full API response text",
  "query_type": "demographics",
  "creator_name": "Creator Name",
  "platform": "youtube"
}
```

## Verification Checklist

### ✅ Save Operation
- [x] Uses correct table: `platform_analytics`
- [x] Uses correct field: `demographics_data`
- [x] Uses correct key: `social_account_id`
- [x] Stores as JSON string
- [x] Updates existing or creates new record
- [x] Sets data_source to 'deep_research'
- [x] Sets snapshot_date to current date

### ✅ Retrieve Operation
- [x] Queries correct table: `platform_analytics`
- [x] Queries correct field: `demographics_data`
- [x] Filters by correct key: `social_account_id`
- [x] Orders by snapshot_date DESC (gets most recent)
- [x] Filters out NULL, empty string, and empty JSON
- [x] Parses JSON correctly
- [x] Adds snapshot_date to returned dict

### ✅ Display Operation
- [x] Iterates through all creators
- [x] Gets social accounts for each creator
- [x] Calls get_demographics_data(account['id'])
- [x] Correctly interprets returned data
- [x] Displays all relevant fields
- [x] Shows proper coverage metrics
- [x] Handles missing data gracefully

## What the Diagnostics Table Shows

### When Demographics Exist:
```
Creator    | Platform  | Has Demographics | Data Source    | Snapshot Date | Has Gender | Has Age | Has Geography
-----------|-----------|------------------|----------------|---------------|------------|---------|---------------
Mark Rober | Youtube   | ✅ Yes           | deep_research  | 2024-12-14   | ✓          | ✓       | ✓
Mark Rober | Instagram | ✅ Yes           | deep_research  | 2024-12-14   | ✓          | ✓       | ✓
```

### When Demographics Missing:
```
Creator    | Platform  | Has Demographics | Data Source | Snapshot Date | Has Gender | Has Age | Has Geography
-----------|-----------|------------------|-------------|---------------|------------|---------|---------------
John Doe   | Youtube   | ❌ No            | N/A         | N/A          | ✗          | ✗       | ✗
```

## Coverage Calculation

**Formula (app.py line 738):**
```python
coverage = (accounts_with_demographics / total_accounts * 100) if total_accounts > 0 else 0
```

**Logic:**
- `total_accounts`: Count of all social accounts across all creators
- `accounts_with_demographics`: Count where `get_demographics_data()` returns data
- `coverage`: Percentage with demographics

**Example:**
- 10 total social accounts (5 creators × 2 platforms each)
- 3 accounts have demographics
- Coverage: 30%

## Key Relationships

```
creators table
    ↓ (creator_id)
social_accounts table
    ↓ (social_account_id = account['id'])
platform_analytics table
    └─ demographics_data field (JSON)
```

## Common Patterns

### Pattern 1: New Creator (No Demographics)
```
User adds creator → Creates social_accounts → No platform_analytics record yet
Diagnostics shows: ❌ No demographics for all platforms
```

### Pattern 2: After First Analysis (Non-Deep Research)
```
User runs Quick/Standard/Comprehensive → Creates platform_analytics with followers/engagement
But: demographics_data field is NULL
Diagnostics shows: ❌ No demographics (even though other analytics exist)
```

### Pattern 3: After Deep Research Analysis
```
User runs Deep Research → Fetches demographics → Updates platform_analytics.demographics_data
Diagnostics shows: ✅ Yes with all details
```

### Pattern 4: After Manual Fetch
```
User clicks "Fetch Demographics Now" → Saves to platform_analytics.demographics_data
Diagnostics shows: ✅ Yes with all details
```

## Potential Issues & Solutions

### Issue: Demographics not showing after fetch
**Possible causes:**
1. Deep Research API failed (check logs)
2. timedelta import error (now fixed)
3. JSON parsing error
4. Empty demographics object

**How to debug:**
1. Check terminal logs for save confirmation
2. Query database directly: `SELECT demographics_data FROM platform_analytics WHERE social_account_id = X`
3. Run diagnostics to see coverage
4. Enable demographics debug mode

### Issue: Old demographics showing
**Cause:** Cache is valid for 90 days
**Solution:** Either wait 90 days or manually fetch new data

### Issue: Demographics showing for wrong creator
**Unlikely:** social_account_id is the foreign key, properly linked

## Conclusion

✅ **The diagnostics table is pulling from the correct data sources**

The complete data flow is:
1. **Save:** Deep Research → `save_demographics_data()` → `platform_analytics.demographics_data`
2. **Retrieve:** Diagnostics → `get_demographics_data()` → `platform_analytics.demographics_data`
3. **Display:** Parse JSON → Show in table with all fields

All connections are correct, using proper foreign keys and filtering. The diagnostics will accurately reflect what's stored in the database.
