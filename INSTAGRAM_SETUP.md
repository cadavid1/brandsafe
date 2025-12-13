# Instagram Setup Guide

## Problem: 403 Forbidden Errors

When scraping Instagram without authentication, you may encounter `403 Forbidden` errors. This happens because:

1. Instagram actively blocks unauthenticated scraping attempts
2. Anonymous access has very strict rate limits
3. Your IP may be temporarily blocked after too many requests

## Solution: Add Instagram Login Credentials

To improve reliability and bypass rate limits, you can configure Instagram login credentials in BrandSafe.

### Setup Steps

1. **Go to System Setup Tab** in the BrandSafe UI
2. **Expand "Instagram Configuration (Optional)"** section
3. **Enter your Instagram credentials**:
   - Username: Your Instagram username (without @)
   - Password: Your Instagram password
4. **Click "Save Credentials"**

### Privacy & Security

⚠️ **Important Notes:**
- Credentials are stored **locally** in your database
- They are only used for Instagram API access
- Consider using a **dedicated Instagram account** for scraping if concerned
- Never share your credentials or database file

### Benefits of Authenticated Access

✅ **With credentials** (recommended):
- Much higher rate limits
- Ability to fetch up to 50 posts per creator
- Reduced chance of IP blocks
- Session caching for faster subsequent requests

❌ **Without credentials** (anonymous):
- Severe rate limits (may fail after 5-10 posts)
- Frequent 403 Forbidden errors
- IP blocking after repeated requests
- Profile stats only (no post details)

### Troubleshooting

**Still getting 403 errors after login?**
1. Wait 15-30 minutes before retrying (your IP may be temporarily blocked)
2. Delete the session file at `./data/.instagram_session` and re-login
3. Check if Instagram is prompting for 2FA - temporarily disable 2FA or use app-specific password
4. Try a different Instagram account
5. Use a VPN or proxy to change your IP address

**Login failed?**
- Verify username and password are correct
- Check if Instagram requires verification (email/SMS)
- Temporarily disable 2FA
- Make sure the account isn't flagged for suspicious activity

### Alternative: Wait and Retry

If you don't want to provide credentials:
- The client will **automatically stop** after 5 consecutive errors
- It will return whatever posts it successfully fetched
- Wait 30+ minutes before retrying to let rate limits reset
- Consider analyzing fewer creators at once

### Technical Details

BrandSafe uses the `instaloader` library with these protections:
- 2-second delay between requests (when logged in)
- 30-second delay without login
- Automatic error detection and graceful degradation
- Session caching to reduce login frequency
- Maximum 5 consecutive errors before stopping

### Example Output

**Anonymous access:**
```
[INFO] Using Instagram anonymous access (limited)
[PROGRESS] Fetched 5 posts...
[WARNING] 403 Forbidden on post (error 1/5)
[WARNING] 403 Forbidden on post (error 2/5)
...
[WARNING] Too many errors (5), stopping post fetch
[INFO] Successfully fetched 5 posts before errors
```

**Authenticated access:**
```
[INFO] Using Instagram authenticated access (@your_username)
[INFO] Loaded Instagram session for @your_username
[PROGRESS] Fetched 5 posts...
[PROGRESS] Fetched 10 posts...
...
[SUCCESS] Fetched 50 posts total
```

## Recommended Approach

1. **For testing**: Use anonymous access, accept limited results
2. **For production**: Create a dedicated Instagram account and add credentials
3. **For bulk analysis**: Spread requests over time, use authenticated access

---

**Need help?** Check the [Instaloader documentation](https://instaloader.github.io/) or contact support.
