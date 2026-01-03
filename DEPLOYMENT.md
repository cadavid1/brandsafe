# Deployment Guide: Database Persistence on Streamlit Community Cloud

This guide will help you deploy your BrandSafe application to Streamlit Community Cloud with persistent data using PostgreSQL.

## Overview

The application now supports **two database modes**:
- **SQLite** (local development) - Data stored in `./data/brandsafe.db`
- **PostgreSQL** (cloud deployment) - Data stored in cloud database

The application automatically detects which database to use based on the presence of the `DATABASE_URL` environment variable.

---

## Step 1: Set Up Cloud Database (Neon - Recommended)

### Why Neon?
- **Free tier**: 0.5 GB storage (plenty for personal/demo use)
- **Auto-scales to zero**: No cost when inactive
- **PostgreSQL 16**: Latest version
- **No credit card required**: True free tier

### Create Neon Database

1. Go to [https://neon.tech](https://neon.tech)
2. Click "Sign Up" (use GitHub, Google, or email)
3. Create a new project:
   - **Project name**: `brandsafe` (or your choice)
   - **Database name**: `brandsafe` (or your choice)
   - **Region**: Choose closest to you (for best performance)
4. Click "Create Project"

### Get Connection String

After project creation, you'll see a connection string like:

```
postgresql://username:password@ep-xyz-123456.us-east-2.aws.neon.tech/brandsafe?sslmode=require
```

**Copy this connection string** - you'll need it in Step 2.

---

## Step 2: Configure Streamlit Secrets

### Update `.streamlit/secrets.toml`

Add your database connection string to your Streamlit secrets file:

```toml
# Database Configuration
DATABASE_URL = "postgresql://username:password@ep-xyz-123456.us-east-2.aws.neon.tech/brandsafe?sslmode=require"

# Your existing secrets (Google Drive, etc.)
GOOGLE_DRIVE_CLIENT_ID = "your-client-id"
GOOGLE_DRIVE_CLIENT_SECRET = "your-client-secret"
# ... other secrets ...
```

**⚠️ Important**: The `.streamlit/secrets.toml` file is in `.gitignore` and should NEVER be committed to git.

### For Local Testing with PostgreSQL (Optional)

If you want to test with PostgreSQL locally:

```bash
# Set environment variable (Windows)
set DATABASE_URL=postgresql://username:password@...

# Set environment variable (Mac/Linux)
export DATABASE_URL=postgresql://username:password@...

# Run your app
streamlit run app.py
```

---

## Step 3: Deploy to Streamlit Community Cloud

### First-Time Deployment

1. **Push your code to GitHub**:
   ```bash
   git add .
   git commit -m "Add PostgreSQL support for Streamlit Cloud"
   git push origin main
   ```

2. **Go to Streamlit Community Cloud**:
   - Visit [https://share.streamlit.io](https://share.streamlit.io)
   - Click "New app"
   - Connect your GitHub repository
   - Select your repository and branch
   - Set main file path: `app.py`

3. **Configure Secrets**:
   - Click "Advanced settings" → "Secrets"
   - Copy the contents of your local `.streamlit/secrets.toml`
   - Paste into the secrets editor
   - Make sure `DATABASE_URL` is included

4. **Deploy**:
   - Click "Deploy"
   - Wait for deployment (usually 2-5 minutes)

### Updating Existing Deployment

1. **Update secrets** (if not done yet):
   - Go to your app dashboard on Streamlit Cloud
   - Click ⚙️ (Settings) → "Secrets"
   - Add the `DATABASE_URL` line
   - Save

2. **Redeploy**:
   - Push your code changes to GitHub
   - Streamlit Cloud will automatically redeploy
   - Or manually trigger: Click "Reboot app" in settings

---

## Step 4: Verify Data Persistence

### Test That Data Persists

1. **Create a user account** in your deployed app
2. **Create a brief** or add some data
3. **Restart your app**:
   - Go to app settings on Streamlit Cloud
   - Click "Reboot app"
4. **Log back in** and verify your data is still there

✅ If your data persists after reboot, congratulations! You're all set.

---

## Alternative Database Providers

If you prefer a different PostgreSQL provider:

### Supabase
- Free tier: 500 MB storage
- Includes auth, storage, and real-time features
- Connection string format: `postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres`
- Website: [https://supabase.com](https://supabase.com)

### Railway
- Free tier: $5 credit/month (includes database)
- Very simple setup
- Connection string provided in dashboard
- Website: [https://railway.app](https://railway.app)

### Heroku Postgres
- Requires credit card (but has free tier)
- Connection string format: `postgres://[username]:[password]@[host]:[port]/[database]`
- Website: [https://www.heroku.com/postgres](https://www.heroku.com/postgres)

---

## How It Works

### Database Type Detection

The application automatically detects which database to use:

```python
# In config.py
DATABASE_URL = os.environ.get("DATABASE_URL")  # From Streamlit secrets
DATABASE_TYPE = "postgresql" if DATABASE_URL else "sqlite"
```

- **Local development** (no `DATABASE_URL`): Uses SQLite at `./data/brandsafe.db`
- **Streamlit Cloud** (with `DATABASE_URL`): Uses PostgreSQL

### Database Adapter Layer

The `database_adapter.py` automatically converts SQL syntax:

- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY` (PostgreSQL)
- `?` placeholders → `%s` (PostgreSQL)
- `DATETIME` → `TIMESTAMP` (PostgreSQL)
- `CURRENT_TIMESTAMP`, `date('now')` → PostgreSQL equivalents

All existing code in `storage.py` works without modification! 🎉

---

## Troubleshooting

### Issue: "Cannot connect to database"

**Solution**: Check your connection string:
- Copy connection string directly from Neon dashboard
- Make sure it includes `?sslmode=require` at the end
- Verify secrets are saved in Streamlit Cloud

### Issue: "psycopg2 not found"

**Solution**: Redeploy the app
- The updated `requirements.txt` includes `psycopg2-binary>=2.9.9`
- Streamlit Cloud should install it automatically
- If not, try "Reboot app" or redeploy from GitHub

### Issue: "Table does not exist"

**Solution**: Database migrations run automatically
- The first time the app starts with PostgreSQL, it creates all tables
- If tables are missing, check logs for migration errors
- You can manually recreate: delete the database and let it reinitialize

### Issue: "Data is still being reset"

**Solution**: Verify `DATABASE_URL` is set
- Check Streamlit Cloud app settings → Secrets
- Ensure `DATABASE_URL` is present and correct
- Reboot the app after adding secrets

### View Logs

To debug issues:
1. Go to your app on Streamlit Cloud
2. Click "Manage app" → "Logs"
3. Look for database-related errors

---

##  Migration from SQLite to PostgreSQL (Optional)

If you have existing data in SQLite that you want to move to PostgreSQL:

### Option 1: Export and Re-Import (Recommended for small datasets)

1. **Export data locally**:
   ```bash
   sqlite3 data/brandsafe.db .dump > brandsafe_dump.sql
   ```

2. **Manual data transfer**:
   - Use the app's export features to download your data
   - Recreate users, briefs, and creators in the new PostgreSQL deployment

### Option 2: Use Migration Tool (For large datasets)

1. **Install pgloader**:
   ```bash
   # Mac
   brew install pgloader

   # Linux
   sudo apt-get install pgloader
   ```

2. **Migrate data**:
   ```bash
   pgloader data/brandsafe.db "postgresql://username:password@host/database"
   ```

⚠️ **Note**: Schema differences may require manual fixes after migration.

---

## Database Backups

### Neon Backups
- Neon automatically takes backups
- Free tier: 7-day point-in-time recovery
- Pro tier: 30-day point-in-time recovery

### Manual Backup

Using `pg_dump`:
```bash
pg_dump "postgresql://username:password@host/database" > backup.sql
```

### Restore from Backup

```bash
psql "postgresql://username:password@host/database" < backup.sql
```

---

## Performance Considerations

### Free Tier Limits

**Neon Free Tier**:
- 0.5 GB storage
- 3 GB data transfer/month
- Shared compute resources
- Auto-pauses after 5 minutes of inactivity

**When to Upgrade**:
- Database exceeds 0.5 GB
- High traffic (> 3 GB transfer/month)
- Need faster performance
- Want dedicated compute

### Optimizations

1. **Indexes**: Already included on key columns (user_id, creator_id, etc.)
2. **Connection pooling**: Managed by Neon automatically
3. **Query optimization**: Use existing methods in `storage.py`

---

## Security Best Practices

### Secrets Management

✅ **DO**:
- Keep `DATABASE_URL` in `.streamlit/secrets.toml`
- Use Streamlit Cloud secrets manager
- Never commit secrets to git
- Rotate credentials periodically

❌ **DON'T**:
- Hard-code connection strings in code
- Share secrets in messages or emails
- Commit `.streamlit/secrets.toml` to git
- Use the same password for multiple services

### Database Security

- ✅ Use SSL/TLS connections (`?sslmode=require`)
- ✅ Use strong passwords
- ✅ Restrict database access to your IP (if possible)
- ✅ Regularly update dependencies

---

## Cost Estimation

### Free Tier (Recommended for personal/demo use)

- **Neon Free**: $0/month (0.5 GB storage)
- **Streamlit Cloud**: $0/month (1 app)
- **Total**: **$0/month** 🎉

### Paid Tier (For production/larger usage)

- **Neon Scale**: $19/month (starts at 10 GB storage)
- **Streamlit Cloud**: Free (up to 1 private app)
- **Total**: **$19/month**

### When You Need to Upgrade

- Database > 0.5 GB
- More than 50 concurrent users
- Need better performance
- Want advanced features (backups, analytics, etc.)

---

## Support and Resources

### Documentation
- **Neon Docs**: [https://neon.tech/docs](https://neon.tech/docs)
- **Streamlit Docs**: [https://docs.streamlit.io](https://docs.streamlit.io)
- **PostgreSQL Docs**: [https://www.postgresql.org/docs/](https://www.postgresql.org/docs/)

### Getting Help
- **Streamlit Forum**: [https://discuss.streamlit.io](https://discuss.streamlit.io)
- **Neon Discord**: [https://discord.gg/neon](https://discord.gg/neon)
- **This Repository**: Open an issue on GitHub

---

## Summary Checklist

- [ ] Sign up for Neon (or alternative PostgreSQL provider)
- [ ] Create database project
- [ ] Copy connection string
- [ ] Add `DATABASE_URL` to `.streamlit/secrets.toml`
- [ ] Push code to GitHub
- [ ] Deploy to Streamlit Community Cloud
- [ ] Configure secrets in Streamlit Cloud dashboard
- [ ] Test data persistence by creating data and rebooting app
- [ ] Set up regular backups (optional)

---

**Congratulations! Your app now has persistent data that survives restarts! 🎊**

For questions or issues, please refer to the troubleshooting section or open an issue on GitHub.
