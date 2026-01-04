"""
Database storage layer for UXR CUJ Analysis
Handles persistent storage of CUJs, videos, and analysis results
Supports both SQLite (local development) and PostgreSQL (cloud deployment)
"""

import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import warnings
import config
from database_adapter import get_database_adapter

# Suppress pandas warning about psycopg2 connections - we handle PostgreSQL correctly
warnings.filterwarnings('ignore', message='.*pandas only supports SQLAlchemy.*')


class DatabaseManager:
    """Manages database operations with support for both SQLite and PostgreSQL"""

    def __init__(self):
        """Initialize database manager"""
        self.db_adapter = get_database_adapter()
        self._ensure_database_directory()
        self.db_adapter.connect()
        self._init_database()

    def _ensure_database_directory(self):
        """Create database directory if it doesn't exist (SQLite only)"""
        if config.DATABASE_TYPE == "sqlite":
            Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self):
        """Get database connection, ensuring it's open"""
        if not self.db_adapter.conn:
            self.db_adapter.connect()
        return self.db_adapter.conn

    def _get_pandas_connection(self):
        """Get a fresh connection for pandas operations to avoid closed connection issues"""
        if self.db_adapter.db_type == "sqlite":
            import sqlite3
            # Create a fresh connection for pandas to avoid closed connection issues
            conn = sqlite3.connect(self.db_adapter.connection_string, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        else:
            # For PostgreSQL, use the existing connection
            return self._get_connection()

    def _read_sql_query(self, query: str, params=None) -> pd.DataFrame:
        """
        Execute a SQL query and return results as DataFrame with proper database compatibility

        Args:
            query: SQL query string (using SQLite syntax with ? placeholders)
            params: Query parameters tuple

        Returns:
            pandas DataFrame with query results
        """
        conn = self._get_pandas_connection()
        try:
            # Convert query for the target database
            converted_query = self.db_adapter.convert_query(query)

            # Execute query with pandas
            if params:
                df = pd.read_sql_query(converted_query, conn, params=params)
            else:
                df = pd.read_sql_query(converted_query, conn)
            return df
        except Exception as e:
            # For PostgreSQL, rollback the transaction on error
            if self.db_adapter.db_type == "postgresql":
                try:
                    conn.rollback()
                except:
                    pass
            raise
        finally:
            # Only close SQLite connections (PostgreSQL connection is managed elsewhere)
            if self.db_adapter.db_type == "sqlite":
                conn.close()

    def _init_database(self):
        """Initialize database schema"""
        cursor = self.db_adapter.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)

        # CUJs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cujs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                expectation TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Videos table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT,
                drive_id TEXT,
                drive_file_id TEXT,
                drive_web_link TEXT,
                source TEXT DEFAULT 'local',
                status TEXT DEFAULT 'ready',
                description TEXT,
                duration_seconds REAL,
                file_size_mb REAL,
                resolution TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Analysis Results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cuj_id TEXT NOT NULL,
                video_id INTEGER NOT NULL,
                model_used TEXT NOT NULL,
                status TEXT,
                friction_score INTEGER,
                confidence_score INTEGER,
                observation TEXT,
                recommendation TEXT,
                key_moments TEXT,
                cost REAL,
                raw_response TEXT,
                human_verified BOOLEAN DEFAULT 0,
                human_override_status TEXT,
                human_override_friction INTEGER,
                human_notes TEXT,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP,
                FOREIGN KEY (cuj_id) REFERENCES cujs(id),
                FOREIGN KEY (video_id) REFERENCES videos(id)
            )
        """)

        # Analysis Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                total_cost REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)

        # Settings table for app configuration (per-user settings)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, key),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Briefs table (campaign/project management)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS briefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                brand_context TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Creators table (talent/influencers)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                primary_platform TEXT NOT NULL,
                notes TEXT,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Social Accounts table (multiple platform accounts per creator)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS social_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                platform_user_id TEXT,
                handle TEXT,
                profile_url TEXT NOT NULL,
                verified BOOLEAN DEFAULT 0,
                discovery_method TEXT,
                last_fetched_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE
            )
        """)

        # Platform Analytics table (aggregated stats snapshots)
        cursor.execute("""
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
                demographics_data TEXT,
                raw_data TEXT,
                data_source TEXT,
                FOREIGN KEY (social_account_id) REFERENCES social_accounts(id) ON DELETE CASCADE
            )
        """)

        # Post Analysis table (individual post analysis)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS post_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                social_account_id INTEGER NOT NULL,
                post_id TEXT NOT NULL,
                post_url TEXT,
                post_date TIMESTAMP,
                post_type TEXT,
                caption TEXT,
                likes_count INTEGER,
                comments_count INTEGER,
                shares_count INTEGER,
                views_count INTEGER,
                duration_seconds REAL,
                sentiment_score REAL,
                content_themes TEXT,
                brand_safety_score REAL,
                natural_alignment_score REAL,
                analyzed_at TIMESTAMP,
                FOREIGN KEY (social_account_id) REFERENCES social_accounts(id) ON DELETE CASCADE
            )
        """)

        # Brief Creators table (many-to-many relationship)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS brief_creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (brief_id) REFERENCES briefs(id) ON DELETE CASCADE,
                FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE,
                UNIQUE(brief_id, creator_id)
            )
        """)

        # Creator Reports table (generated analysis reports)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS creator_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                overall_score REAL,
                natural_alignment_score REAL,
                summary TEXT,
                strengths TEXT,
                concerns TEXT,
                recommendations TEXT,
                analysis_cost REAL,
                model_used TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (brief_id) REFERENCES briefs(id) ON DELETE CASCADE,
                FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE
            )
        """)

        # Deep Research Queries table (caching for Deep Research API results)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deep_research_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT UNIQUE NOT NULL,
                query_text TEXT NOT NULL,
                query_type TEXT NOT NULL,
                creator_id INTEGER,
                social_account_id INTEGER,
                interaction_id TEXT,
                status TEXT DEFAULT 'pending',
                result_data TEXT,
                citations TEXT,
                cost REAL DEFAULT 0.0,
                input_tokens INTEGER,
                output_tokens INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                expires_at TIMESTAMP,
                error_message TEXT,
                FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE,
                FOREIGN KEY (social_account_id) REFERENCES social_accounts(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_query_hash
            ON deep_research_queries(query_hash)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_creator_type
            ON deep_research_queries(creator_id, query_type)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_status
            ON deep_research_queries(status)
        """)

        # YouTube API Keys table (for YouTube Data API v3 integration)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS youtube_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                api_key TEXT NOT NULL,
                key_name TEXT NOT NULL,
                quota_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Campaign Assets table (for generated images and videos)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaign_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                brief_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                asset_type TEXT NOT NULL,
                asset_subtype TEXT,
                file_path TEXT NOT NULL,
                thumbnail_path TEXT,
                prompt_used TEXT NOT NULL,
                model_used TEXT NOT NULL,
                generation_params TEXT,
                cost REAL DEFAULT 0.0,
                status TEXT DEFAULT 'completed',
                error_message TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (brief_id) REFERENCES briefs(id) ON DELETE CASCADE,
                FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE
            )
        """)

        # Migration: Add new columns to existing databases
        self._migrate_analysis_results_table(cursor)
        self._migrate_to_multiuser(cursor)
        self._migrate_email_optional(cursor)
        self._migrate_creator_reports_table(cursor)
        self._fix_brief_creators_data_types(cursor)
        self._migrate_natural_alignment_columns(cursor)

        self.db_adapter.commit()
        # Don't close connection - it's managed by the adapter

    def _migrate_analysis_results_table(self, cursor):
        """Add new columns to analysis_results table if they don't exist"""
        # Add missing columns
        migrations = [
            ("confidence_score", "ALTER TABLE analysis_results ADD COLUMN confidence_score INTEGER"),
            ("key_moments", "ALTER TABLE analysis_results ADD COLUMN key_moments TEXT"),
            ("human_verified", "ALTER TABLE analysis_results ADD COLUMN human_verified BOOLEAN DEFAULT 0"),
            ("human_override_status", "ALTER TABLE analysis_results ADD COLUMN human_override_status TEXT"),
            ("human_override_friction", "ALTER TABLE analysis_results ADD COLUMN human_override_friction INTEGER"),
            ("human_notes", "ALTER TABLE analysis_results ADD COLUMN human_notes TEXT"),
            ("verified_at", "ALTER TABLE analysis_results ADD COLUMN verified_at TIMESTAMP")
        ]

        for column_name, migration_sql in migrations:
            if not self.db_adapter.check_column_exists(cursor, "analysis_results", column_name):
                try:
                    cursor.execute(migration_sql)
                    print(f"Added column: {column_name}")
                except Exception as e:
                    print(f"Migration warning for {column_name}: {e}")

    def _migrate_to_multiuser(self, cursor):
        """Migrate existing single-user database to multi-user structure"""
        # Check if users table has any users
        cursor.execute("SELECT COUNT(*) as count FROM users")
        user_count = cursor.fetchone()['count']

        # Check if cujs table has user_id column
        if not self.db_adapter.check_column_exists(cursor, "cujs", "user_id"):
            print("Migrating cujs table to multi-user...")
            # Add user_id column
            cursor.execute("ALTER TABLE cujs ADD COLUMN user_id INTEGER")

            # Only assign existing data to default user if there are users
            if user_count > 0:
                cursor.execute("SELECT id FROM users LIMIT 1")
                default_user_id = cursor.fetchone()['id']
                cursor.execute("UPDATE cujs SET user_id = ? WHERE user_id IS NULL", (default_user_id,))

        # Check if videos table has user_id column
        if not self.db_adapter.check_column_exists(cursor, "videos", "user_id"):
            print("Migrating videos table to multi-user...")
            cursor.execute("ALTER TABLE videos ADD COLUMN user_id INTEGER")

            # Only assign existing data to default user if there are users
            if user_count > 0:
                cursor.execute("SELECT id FROM users LIMIT 1")
                default_user_id = cursor.fetchone()['id']
                cursor.execute("UPDATE videos SET user_id = ? WHERE user_id IS NULL", (default_user_id,))

        # Migrate settings table to per-user settings
        has_user_id = self.db_adapter.check_column_exists(cursor, "settings", "user_id")
        has_id = self.db_adapter.check_column_exists(cursor, "settings", "id")

        if not has_user_id and not has_id:
            print("Migrating settings table to multi-user...")

            # Get existing settings before dropping table
            cursor.execute("SELECT key, value FROM settings")
            old_settings = cursor.fetchall()

            # Drop and recreate settings table with new schema
            cursor.execute("DROP TABLE settings")
            cursor.execute("""
                CREATE TABLE settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, key),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

            # Restore settings for default user if there are users
            if user_count > 0 and old_settings:
                cursor.execute("SELECT id FROM users LIMIT 1")
                default_user_id = cursor.fetchone()['id']

                for key, value in old_settings:
                    cursor.execute("""
                        INSERT INTO settings (user_id, key, value)
                        VALUES (?, ?, ?)
                    """, (default_user_id, key, value))

    def _migrate_email_optional(self, cursor):
        """Migrate users table to make email optional"""
        # This migration is complex and database-specific
        # For new databases, the correct schema is created in _init_database
        # For existing databases, this migration is not critical
        pass

    def _migrate_creator_reports_table(self, cursor):
        """Add video_insights column to creator_reports table if it doesn't exist"""
        try:
            # Check if column exists
            if not self.db_adapter.check_column_exists(cursor, "creator_reports", "video_insights"):
                cursor.execute("ALTER TABLE creator_reports ADD COLUMN video_insights TEXT")
                print("Added column: video_insights to creator_reports")
        except Exception as e:
            print(f"Creator reports migration warning: {e}")

    def _fix_brief_creators_data_types(self, cursor):
        """Fix brief_creators table where brief_id may have been stored as binary data"""
        try:
            # Check if there are any rows with corrupted data
            cursor.execute("SELECT id, brief_id, creator_id, status, added_at FROM brief_creators")
            rows = cursor.fetchall()

            corrupted_rows = []
            for row in rows:
                brief_id = row[1]
                # Check if brief_id is binary data (bytes object)
                if isinstance(brief_id, bytes):
                    # Convert binary to integer (assuming little-endian)
                    try:
                        brief_id_int = int.from_bytes(brief_id[:8], byteorder='little')
                        corrupted_rows.append((row[0], brief_id_int, row[2], row[3], row[4]))
                    except:
                        print(f"Could not convert brief_id for row {row[0]}")

            if corrupted_rows:
                print(f"Fixing {len(corrupted_rows)} corrupted rows in brief_creators table...")
                # Delete the corrupted rows
                for row_id, _, _, _, _ in corrupted_rows:
                    cursor.execute("DELETE FROM brief_creators WHERE id = ?", (row_id,))

                # Reinsert with correct data types
                for row_id, brief_id, creator_id, status, added_at in corrupted_rows:
                    cursor.execute("""
                        INSERT INTO brief_creators (brief_id, creator_id, status, added_at)
                        VALUES (?, ?, ?, ?)
                    """, (brief_id, creator_id, status, added_at))
                    print(f"  Fixed: brief_id={brief_id}, creator_id={creator_id}")

                print("brief_creators table data fix complete!")
        except Exception as e:
            print(f"brief_creators data fix warning: {e}")

    def _migrate_natural_alignment_columns(self, cursor):
        """Add natural_alignment_score columns to post_analysis and creator_reports tables"""
        try:
            # Check post_analysis table
            if not self.db_adapter.check_column_exists(cursor, "post_analysis", "natural_alignment_score"):
                cursor.execute("ALTER TABLE post_analysis ADD COLUMN natural_alignment_score REAL")
                print("Added column: natural_alignment_score to post_analysis")

            # Check creator_reports table
            if not self.db_adapter.check_column_exists(cursor, "creator_reports", "natural_alignment_score"):
                cursor.execute("ALTER TABLE creator_reports ADD COLUMN natural_alignment_score REAL")
                print("Added column: natural_alignment_score to creator_reports")

        except Exception as e:
            print(f"Natural alignment migration warning: {e}")

    # === User Management ===

    def create_user(self, email: str, username: str, password_hash: str, full_name: str = "") -> Optional[int]:
        """Create a new user and return user ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                # PostgreSQL requires RETURNING clause to get the inserted ID
                cursor.execute("""
                    INSERT INTO users (email, username, password_hash, full_name)
                    VALUES (?, ?, ?, ?)
                    RETURNING id
                """, (email, username, password_hash, full_name))
                result = cursor.fetchone()
                user_id = result['id'] if result else None
            else:
                # SQLite uses lastrowid
                cursor.execute("""
                    INSERT INTO users (email, username, password_hash, full_name)
                    VALUES (?, ?, ?, ?)
                """, (email, username, password_hash, full_name))
                user_id = cursor.lastrowid

            self.db_adapter.commit()
            return user_id
        except Exception as e:
            # Handle integrity errors (duplicate username/email)
            if "UNIQUE" in str(e) or "IntegrityError" in str(type(e).__name__):
                print(f"User creation failed - duplicate username or email: {e}")
            else:
                print(f"Error creating user: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT id, email, username, password_hash, full_name, created_at, last_login
                FROM users
                WHERE username = ?
            """, (username,))

            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'email': row['email'],
                    'username': row['username'],
                    'password_hash': row['password_hash'],
                    'full_name': row['full_name'],
                    'created_at': row['created_at'],
                    'last_login': row['last_login']
                }
            return None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT id, email, username, password_hash, full_name, created_at, last_login
                FROM users
                WHERE email = ?
            """, (email,))

            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'email': row['email'],
                    'username': row['username'],
                    'password_hash': row['password_hash'],
                    'full_name': row['full_name'],
                    'created_at': row['created_at'],
                    'last_login': row['last_login']
                }
            return None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None

    def update_last_login(self, user_id: int) -> bool:
        """Update user's last login timestamp"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                UPDATE users
                SET last_login = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (user_id,))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error updating last login: {e}")
            return False

    def get_all_users(self) -> List[Dict]:
        """Get all users (admin function)"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT id, email, username, full_name, created_at, last_login
                FROM users
                ORDER BY created_at DESC
            """)

            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row['id'],
                    'email': row['email'],
                    'username': row['username'],
                    'full_name': row['full_name'],
                    'created_at': row['created_at'],
                    'last_login': row['last_login']
                })

            return users
        except Exception as e:
            print(f"Error getting all users: {e}")
            return []

    # === CUJ Operations ===

    def save_cuj(self, user_id: int, cuj_id: str, task: str, expectation: str) -> bool:
        """Save or update a CUJ for a specific user"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                INSERT INTO cujs (id, user_id, task, expectation, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    task = excluded.task,
                    expectation = excluded.expectation,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (cuj_id, user_id, task, expectation, user_id))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error saving CUJ: {e}")
            return False

    def get_cujs(self, user_id: int) -> pd.DataFrame:
        """Get all CUJs for a specific user as DataFrame"""
        return self._read_sql_query(
            "SELECT id, task, expectation FROM cujs WHERE user_id = ? ORDER BY created_at",
            params=(user_id,)
        )

    def delete_cuj(self, user_id: int, cuj_id: str) -> bool:
        """Delete a CUJ for a specific user"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("DELETE FROM cujs WHERE id = ? AND user_id = ?", (cuj_id, user_id))
            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error deleting CUJ: {e}")
            return False

    def bulk_save_cujs(self, user_id: int, cujs_df: pd.DataFrame) -> bool:
        """Bulk save CUJs from DataFrame for a specific user"""
        try:
            saved_count = 0
            skipped_count = 0

            for _, row in cujs_df.iterrows():
                # Validate required fields are not None, NaN, or empty
                cuj_id = row.get('id')
                task = row.get('task')
                expectation = row.get('expectation')

                # Check if any required field is None, NaN, or empty string
                if pd.isna(cuj_id) or pd.isna(task) or pd.isna(expectation):
                    skipped_count += 1
                    continue

                if not str(cuj_id).strip() or not str(task).strip() or not str(expectation).strip():
                    skipped_count += 1
                    continue

                self.save_cuj(user_id, str(cuj_id).strip(), str(task).strip(), str(expectation).strip())
                saved_count += 1

            if skipped_count > 0:
                print(f"Skipped {skipped_count} CUJ(s) with missing required fields (id, task, or expectation)")

            return True
        except Exception as e:
            print(f"Error bulk saving CUJs: {e}")
            return False

    # === Video Operations ===

    def save_video(self, user_id: int, name: str, file_path: str, duration_seconds: float,
                   file_size_mb: float, resolution: str = "", description: str = "") -> int:
        """Save video metadata for a specific user and return video ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO videos (user_id, name, file_path, status, description,
                                      duration_seconds, file_size_mb, resolution, source)
                    VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, 'local')
                    RETURNING id
                """, (user_id, name, file_path, description, duration_seconds, file_size_mb, resolution))
                result = cursor.fetchone()
                video_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO videos (user_id, name, file_path, status, description,
                                      duration_seconds, file_size_mb, resolution, source)
                    VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, 'local')
                """, (user_id, name, file_path, description, duration_seconds, file_size_mb, resolution))
                video_id = cursor.lastrowid

            self.db_adapter.commit()
            return video_id
        except Exception as e:
            print(f"Error saving video: {e}")
            return -1

    def save_drive_video(self, user_id: int, name: str, drive_file_id: str, drive_web_link: str,
                        file_path: str, duration_seconds: float, file_size_mb: float,
                        resolution: str = "", description: str = "") -> int:
        """Save Drive video metadata for a specific user and return video ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO videos (user_id, name, file_path, drive_file_id, drive_web_link,
                                      source, status, description, duration_seconds,
                                      file_size_mb, resolution)
                    VALUES (?, ?, ?, ?, ?, 'drive', 'ready', ?, ?, ?, ?)
                    RETURNING id
                """, (user_id, name, file_path, drive_file_id, drive_web_link, description,
                      duration_seconds, file_size_mb, resolution))
                result = cursor.fetchone()
                video_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO videos (user_id, name, file_path, drive_file_id, drive_web_link,
                                      source, status, description, duration_seconds,
                                      file_size_mb, resolution)
                    VALUES (?, ?, ?, ?, ?, 'drive', 'ready', ?, ?, ?, ?)
                """, (user_id, name, file_path, drive_file_id, drive_web_link, description,
                      duration_seconds, file_size_mb, resolution))
                video_id = cursor.lastrowid

            self.db_adapter.commit()
            return video_id
        except Exception as e:
            print(f"Error saving Drive video: {e}")
            return -1

    def get_videos(self, user_id: int) -> pd.DataFrame:
        """Get all videos for a specific user as DataFrame"""
        return self._read_sql_query("""
            SELECT id, name, file_path, status, description,
                   duration_seconds as duration, file_size_mb as size_mb,
                   resolution, uploaded_at
            FROM videos
            WHERE user_id = ?
            ORDER BY uploaded_at DESC
        """, params=(user_id,))

    def delete_video(self, user_id: int, video_id: int) -> bool:
        """Delete a video for a specific user"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("DELETE FROM videos WHERE id = ? AND user_id = ?", (video_id, user_id))
            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error deleting video: {e}")
            return False

    def bulk_save_videos(self, videos_df: pd.DataFrame) -> bool:
        """Bulk save videos from DataFrame"""
        try:
            for _, row in videos_df.iterrows():
                if row.get('file_path') and pd.notna(row.get('file_path')):
                    self.save_video(
                        row['name'],
                        row['file_path'],
                        row.get('duration', 0),
                        row.get('size_mb', 0),
                        row.get('description', ''),
                        row.get('description', '')
                    )
            return True
        except Exception as e:
            print(f"Error bulk saving videos: {e}")
            return False

    # === Analysis Results Operations ===

    def save_analysis(self, cuj_id: str, video_id: int, model_used: str,
                     status: str, friction_score: int, observation: str,
                     recommendation: str, cost: float = 0.0,
                     raw_response: str = "", confidence_score: int = None,
                     key_moments: str = None) -> int:
        """Save analysis result and return analysis ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO analysis_results
                    (cuj_id, video_id, model_used, status, friction_score, confidence_score,
                     observation, recommendation, key_moments, cost, raw_response)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                """, (cuj_id, video_id, model_used, status, friction_score, confidence_score,
                      observation, recommendation, key_moments, cost, raw_response))
                result = cursor.fetchone()
                analysis_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO analysis_results
                    (cuj_id, video_id, model_used, status, friction_score, confidence_score,
                     observation, recommendation, key_moments, cost, raw_response)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (cuj_id, video_id, model_used, status, friction_score, confidence_score,
                      observation, recommendation, key_moments, cost, raw_response))
                analysis_id = cursor.lastrowid

            self.db_adapter.commit()
            return analysis_id
        except Exception as e:
            print(f"Error saving analysis: {e}")
            return -1

    def get_analysis_results(self, user_id: int, limit: Optional[int] = None) -> pd.DataFrame:
        """Get analysis results for a specific user as DataFrame"""
        query = """
            SELECT
                ar.id,
                ar.cuj_id,
                c.task as cuj_task,
                ar.video_id,
                v.name as video_name,
                ar.model_used,
                ar.status,
                ar.friction_score,
                ar.confidence_score,
                ar.observation,
                ar.recommendation,
                ar.key_moments,
                ar.cost,
                ar.human_verified,
                ar.human_override_status,
                ar.human_override_friction,
                ar.human_notes,
                ar.analyzed_at,
                ar.verified_at
            FROM analysis_results ar
            JOIN cujs c ON ar.cuj_id = c.id
            JOIN videos v ON ar.video_id = v.id
            WHERE c.user_id = ?
            ORDER BY ar.analyzed_at DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        return self._read_sql_query(query, params=(user_id,))

    def get_latest_results(self, user_id: int) -> Dict:
        """Get latest analysis results for a specific user as dictionary keyed by CUJ ID"""
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        # Get most recent analysis for each CUJ belonging to the user
        cursor.execute("""
            SELECT
                ar.id,
                ar.cuj_id,
                ar.video_id,
                v.name as video_name,
                v.file_path as video_path,
                ar.model_used,
                ar.status,
                ar.friction_score,
                ar.confidence_score,
                ar.observation,
                ar.recommendation,
                ar.key_moments,
                ar.cost,
                ar.human_verified,
                ar.human_override_status,
                ar.human_override_friction,
                ar.human_notes
            FROM analysis_results ar
            JOIN videos v ON ar.video_id = v.id
            JOIN cujs c ON ar.cuj_id = c.id
            WHERE c.user_id = ? AND ar.id IN (
                SELECT MAX(ar2.id)
                FROM analysis_results ar2
                JOIN cujs c2 ON ar2.cuj_id = c2.id
                WHERE c2.user_id = ?
                GROUP BY ar2.cuj_id
            )
        """, (user_id, user_id))

        results = {}
        for row in cursor.fetchall():
            results[row['cuj_id']] = {
                'analysis_id': row['id'],
                'video_used': row['video_name'],
                'video_id': row['video_id'],
                'video_path': row['video_path'],
                'model_used': row['model_used'],
                'status': row['status'],
                'friction_score': row['friction_score'],
                'confidence_score': row['confidence_score'],
                'observation': row['observation'],
                'recommendation': row['recommendation'],
                'key_moments': row['key_moments'],
                'cost': row['cost'],
                'human_verified': row['human_verified'],
                'human_override_status': row['human_override_status'],
                'human_override_friction': row['human_override_friction'],
                'human_notes': row['human_notes']
            }

        return results

    def delete_analysis_results(self, cuj_id: str = None, video_id: int = None) -> bool:
        """Delete analysis results by CUJ or video"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if cuj_id:
                cursor.execute("DELETE FROM analysis_results WHERE cuj_id = ?", (cuj_id,))
            elif video_id:
                cursor.execute("DELETE FROM analysis_results WHERE video_id = ?", (video_id,))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error deleting analysis results: {e}")
            return False

    def verify_analysis(self, analysis_id: int, override_status: str = None,
                       override_friction: int = None, notes: str = "") -> bool:
        """
        Mark an analysis as human-verified with optional overrides

        Args:
            analysis_id: ID of the analysis to verify
            override_status: Optional human override for status (Pass/Fail/Partial)
            override_friction: Optional human override for friction score (1-5)
            notes: Human notes about the verification

        Returns:
            True if successful
        """
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                UPDATE analysis_results
                SET human_verified = 1,
                    human_override_status = ?,
                    human_override_friction = ?,
                    human_notes = ?,
                    verified_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (override_status, override_friction, notes, analysis_id))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error verifying analysis: {e}")
            return False

    # === Export Operations ===

    def export_results_to_csv(self, filename: str = None) -> str:
        """Export analysis results to CSV"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_results_{timestamp}.csv"

        Path(EXPORT_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
        filepath = Path(EXPORT_STORAGE_PATH) / filename

        df = self.get_analysis_results()
        df.to_csv(filepath, index=False)

        return str(filepath)

    def export_results_to_json(self, filename: str = None) -> str:
        """Export analysis results to JSON"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_results_{timestamp}.json"

        Path(EXPORT_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
        filepath = Path(EXPORT_STORAGE_PATH) / filename

        df = self.get_analysis_results()
        df.to_json(filepath, orient='records', indent=2, date_format='iso')

        return str(filepath)

    # === Session Management ===

    def create_session(self, name: str = None) -> int:
        """Create a new analysis session"""
        if not name:
            name = f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("INSERT INTO sessions (name) VALUES (?) RETURNING id", (name,))
                result = cursor.fetchone()
                session_id = result['id'] if result else -1
            else:
                cursor.execute("INSERT INTO sessions (name) VALUES (?)", (name,))
                session_id = cursor.lastrowid

            self.db_adapter.commit()
            return session_id
        except Exception as e:
            print(f"Error creating session: {e}")
            return -1

    def complete_session(self, session_id: int, total_cost: float):
        """Mark session as completed"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                UPDATE sessions
                SET total_cost = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (total_cost, session_id))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error completing session: {e}")
            return False

    # === Settings Management ===

    def save_setting(self, user_id: int, key: str, value: str) -> bool:
        """Save a setting for a specific user"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                INSERT INTO settings (user_id, key, value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, key, value))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error saving setting: {e}")
            return False

    def get_setting(self, user_id: int, key: str, default: str = None) -> Optional[str]:
        """Get a setting value for a specific user"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key))
            row = cursor.fetchone()

            return row['value'] if row else default
        except Exception as e:
            print(f"Error getting setting: {e}")
            return default

    # === YouTube API Key Management ===

    def save_youtube_api_key(self, user_id: int, api_key: str, key_name: str = "Primary Key") -> int:
        """Save a YouTube API key for a user and return key ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO youtube_api_keys (user_id, api_key, key_name)
                    VALUES (?, ?, ?)
                    RETURNING id
                """, (user_id, api_key, key_name))
                result = cursor.fetchone()
                key_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO youtube_api_keys (user_id, api_key, key_name)
                    VALUES (?, ?, ?)
                """, (user_id, api_key, key_name))
                key_id = cursor.lastrowid
            self.db_adapter.commit()
            return key_id
        except Exception as e:
            print(f"Error saving YouTube API key: {e}")
            return -1

    def get_youtube_api_keys(self, user_id: int) -> List[str]:
        """Get all YouTube API keys for a user (returns list of key strings only)"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("SELECT api_key FROM youtube_api_keys WHERE user_id = ? ORDER BY created_at", (user_id,))
            keys = [row['api_key'] for row in cursor.fetchall()]
            return keys
        except Exception as e:
            print(f"Error getting YouTube API keys: {e}")
            return []

    def get_youtube_api_keys_with_info(self, user_id: int) -> List[Dict]:
        """Get all YouTube API keys for a user with metadata"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("""
                SELECT id, key_name, api_key, quota_used, created_at
                FROM youtube_api_keys
                WHERE user_id = ?
                ORDER BY created_at
            """, (user_id,))
            keys = []
            for row in cursor.fetchall():
                keys.append({
                    'id': row['id'],
                    'key_name': row['key_name'],
                    'api_key': row['api_key'],
                    'quota_used': row['quota_used'],
                    'created_at': row['created_at']
                })
            return keys
        except Exception as e:
            print(f"Error getting YouTube API key info: {e}")
            return []

    def delete_youtube_api_key(self, user_id: int, key_id: int) -> bool:
        """Delete a YouTube API key"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("DELETE FROM youtube_api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error deleting YouTube API key: {e}")
            return False

    # === Statistics ===

    def get_statistics(self, user_id: int) -> Dict:
        """Get statistics for a specific user"""
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        # Total counts for creator analysis
        cursor.execute("SELECT COUNT(*) as count FROM briefs WHERE user_id = ?", (user_id,))
        total_briefs = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM creators WHERE user_id = ?", (user_id,))
        total_creators = cursor.fetchone()['count']

        cursor.execute("""
            SELECT COUNT(*) as count
            FROM creator_reports cr
            JOIN briefs b ON cr.brief_id = b.id
            WHERE b.user_id = ?
        """, (user_id,))
        total_analyses = cursor.fetchone()['count']

        # Total cost from creator analyses
        cursor.execute("""
            SELECT SUM(cr.analysis_cost) as total
            FROM creator_reports cr
            JOIN briefs b ON cr.brief_id = b.id
            WHERE b.user_id = ?
        """, (user_id,))
        total_cost = cursor.fetchone()['total'] or 0.0

        # Average brand fit score
        cursor.execute("""
            SELECT AVG(cr.overall_score) as avg
            FROM creator_reports cr
            JOIN briefs b ON cr.brief_id = b.id
            WHERE b.user_id = ?
        """, (user_id,))
        avg_brand_fit = cursor.fetchone()['avg'] or 0.0

        # Legacy stats (kept for backwards compatibility, return 0)
        cursor.execute("""
            SELECT ar.status, COUNT(*) as count
            FROM analysis_results ar
            INNER JOIN cujs c ON ar.cuj_id = c.id
            LEFT JOIN videos v ON ar.video_id = v.id
            WHERE c.user_id = ?
            GROUP BY ar.status
        """, (user_id,))
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}


        return {
            'total_briefs': total_briefs,
            'total_creators': total_creators,
            'total_analyses': total_analyses,
            'total_cost': total_cost,
            'avg_brand_fit_score': avg_brand_fit,
            # Legacy fields for backwards compatibility
            'total_cujs': 0,
            'total_videos': 0,
            'avg_friction_score': 0.0,
            'status_counts': status_counts
        }

    def get_cost_history(self, user_id: int, days: int = 30) -> List[Dict]:
        """Get daily cost aggregations for a specific user for charting

        Args:
            user_id: User ID to filter by
            days: Number of days to look back (default 30)

        Returns:
            List of dicts with 'date' and 'cost' keys, ordered chronologically
        """
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        cursor.execute("""
            SELECT
                DATE(ar.analyzed_at) as date,
                SUM(ar.cost) as daily_cost
            FROM analysis_results ar
            JOIN cujs c ON ar.cuj_id = c.id
            WHERE c.user_id = ? AND ar.analyzed_at >= DATE('now', '-' || ? || ' days')
            GROUP BY DATE(ar.analyzed_at)
            ORDER BY date ASC
        """, (user_id, days))

        results = cursor.fetchall()

        # Convert to list of dicts
        cost_history = [
            {'date': row['date'], 'cost': row['daily_cost'] or 0.0}
            for row in results
        ]

        return cost_history

    # === Brand/Talent Analysis Operations ===

    # --- Brief Operations ---

    def save_brief(self, user_id: int, name: str, description: str = "",
                   brand_context: str = "", status: str = "active") -> int:
        """Save or create a brief and return brief ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO briefs (user_id, name, description, brand_context, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    RETURNING id
                """, (user_id, name, description, brand_context, status))
                result = cursor.fetchone()
                brief_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO briefs (user_id, name, description, brand_context, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, name, description, brand_context, status))
                brief_id = cursor.lastrowid

            self.db_adapter.commit()
            return brief_id
        except Exception as e:
            print(f"Error saving brief: {e}")
            return -1

    def get_briefs(self, user_id: int) -> pd.DataFrame:
        """Get all briefs for a specific user"""
        return self._read_sql_query("""
            SELECT id, name, description, brand_context, status, created_at, updated_at
            FROM briefs
            WHERE user_id = ?
            ORDER BY updated_at DESC
        """, params=(user_id,))

    def get_brief(self, brief_id: int) -> Optional[Dict]:
        """Get a specific brief by ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT id, user_id, name, description, brand_context, status, created_at, updated_at
                FROM briefs
                WHERE id = ?
            """, (brief_id,))

            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'user_id': row['user_id'],
                    'name': row['name'],
                    'description': row['description'],
                    'brand_context': row['brand_context'],
                    'status': row['status'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            return None
        except Exception as e:
            print(f"Error getting brief: {e}")
            return None

    def update_brief(self, brief_id: int, name: str = None, description: str = None,
                    brand_context: str = None, status: str = None) -> bool:
        """Update a brief"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            updates = []
            params = []

            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            if brand_context is not None:
                updates.append("brand_context = ?")
                params.append(brand_context)
            if status is not None:
                updates.append("status = ?")
                params.append(status)

            if not updates:
                return False

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(brief_id)

            query = f"UPDATE briefs SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error updating brief: {e}")
            return False

    def delete_brief(self, user_id: int, brief_id: int) -> bool:
        """Delete a brief"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("DELETE FROM briefs WHERE id = ? AND user_id = ?", (brief_id, user_id))
            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error deleting brief: {e}")
            return False

    # --- Creator Operations ---

    def save_creator(self, user_id: int, name: str, primary_platform: str,
                    notes: str = "", tags: str = "") -> int:
        """Save a creator and return creator ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO creators (user_id, name, primary_platform, notes, tags, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    RETURNING id
                """, (user_id, name, primary_platform, notes, tags))
                result = cursor.fetchone()
                creator_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO creators (user_id, name, primary_platform, notes, tags, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, name, primary_platform, notes, tags))
                creator_id = cursor.lastrowid

            self.db_adapter.commit()
            return creator_id
        except Exception as e:
            print(f"Error saving creator: {e}")
            return -1

    def get_creators(self, user_id: int) -> pd.DataFrame:
        """Get all creators for a specific user"""
        return self._read_sql_query("""
            SELECT id, name, primary_platform, notes, tags, created_at, updated_at
            FROM creators
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, params=(user_id,))

    def get_creator(self, creator_id: int) -> Optional[Dict]:
        """Get a specific creator by ID"""
        try:
            # Convert numpy types to native Python int (pandas DataFrames return numpy.int64)
            creator_id = int(creator_id)

            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT id, user_id, name, primary_platform, notes, tags, created_at, updated_at
                FROM creators
                WHERE id = ?
            """, (creator_id,))

            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'user_id': row['user_id'],
                    'name': row['name'],
                    'primary_platform': row['primary_platform'],
                    'notes': row['notes'],
                    'tags': row['tags'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            return None
        except Exception as e:
            print(f"[ERROR] Error getting creator {creator_id}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_creators_for_brief(self, brief_id: int) -> pd.DataFrame:
        """Get all creators linked to a specific brief"""
        return self._read_sql_query("""
            SELECT c.id, c.name, c.primary_platform, c.notes, c.tags, bc.status as brief_status, bc.added_at
            FROM creators c
            JOIN brief_creators bc ON c.id = bc.creator_id
            WHERE bc.brief_id = ?
            ORDER BY bc.added_at DESC
        """, params=(brief_id,))

    def delete_creator(self, user_id: int, creator_id: int) -> bool:
        """Delete a creator"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("DELETE FROM creators WHERE id = ? AND user_id = ?", (creator_id, user_id))
            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error deleting creator: {e}")
            return False

    # --- Social Account Operations ---

    def save_social_account(self, creator_id: int, platform: str, profile_url: str,
                          platform_user_id: str = "", handle: str = "",
                          verified: bool = False, discovery_method: str = "manual") -> int:
        """Save a social account and return account ID"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO social_accounts
                    (creator_id, platform, platform_user_id, handle, profile_url, verified, discovery_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                """, (creator_id, platform, platform_user_id, handle, profile_url, verified, discovery_method))
                result = cursor.fetchone()
                account_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO social_accounts
                    (creator_id, platform, platform_user_id, handle, profile_url, verified, discovery_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (creator_id, platform, platform_user_id, handle, profile_url, verified, discovery_method))
                account_id = cursor.lastrowid

            self.db_adapter.commit()
            return account_id
        except Exception as e:
            print(f"Error saving social account: {e}")
            return -1

    def get_social_accounts(self, creator_id: int) -> pd.DataFrame:
        """Get all social accounts for a creator"""
        # Convert numpy types to native Python int
        creator_id = int(creator_id)

        return self._read_sql_query("""
            SELECT id, platform, platform_user_id, handle, profile_url,
                   verified, discovery_method, last_fetched_at, created_at
            FROM social_accounts
            WHERE creator_id = ?
            ORDER BY created_at
        """, params=(creator_id,))

    def update_social_account_fetch_time(self, account_id: int) -> bool:
        """Update last_fetched_at timestamp for a social account"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("""
                UPDATE social_accounts
                SET last_fetched_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (account_id,))
            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error updating fetch time: {e}")
            return False

    # --- Platform Analytics Operations ---

    def save_platform_analytics(self, social_account_id: int, analytics_data: Dict) -> int:
        """Save platform analytics snapshot"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO platform_analytics
                    (social_account_id, snapshot_date, followers_count, following_count,
                     total_posts, avg_likes, avg_comments, avg_shares, engagement_rate,
                     demographics_data, raw_data, data_source)
                    VALUES (?, DATE('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                """, (
                    social_account_id,
                    analytics_data.get('followers_count', 0),
                    analytics_data.get('following_count', 0),
                    analytics_data.get('total_posts', 0),
                    analytics_data.get('avg_likes', 0.0),
                    analytics_data.get('avg_comments', 0.0),
                    analytics_data.get('avg_shares', 0.0),
                    analytics_data.get('engagement_rate', 0.0),
                    json.dumps(analytics_data.get('demographics', {})),
                    json.dumps(analytics_data.get('raw_data', {})),
                    analytics_data.get('data_source', 'unknown')
                ))
                result = cursor.fetchone()
                analytics_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO platform_analytics
                    (social_account_id, snapshot_date, followers_count, following_count,
                     total_posts, avg_likes, avg_comments, avg_shares, engagement_rate,
                     demographics_data, raw_data, data_source)
                    VALUES (?, DATE('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    social_account_id,
                    analytics_data.get('followers_count', 0),
                    analytics_data.get('following_count', 0),
                    analytics_data.get('total_posts', 0),
                    analytics_data.get('avg_likes', 0.0),
                    analytics_data.get('avg_comments', 0.0),
                    analytics_data.get('avg_shares', 0.0),
                    analytics_data.get('engagement_rate', 0.0),
                    json.dumps(analytics_data.get('demographics', {})),
                    json.dumps(analytics_data.get('raw_data', {})),
                    analytics_data.get('data_source', 'unknown')
                ))
                analytics_id = cursor.lastrowid

            self.db_adapter.commit()
            return analytics_id
        except Exception as e:
            print(f"Error saving platform analytics: {e}")
            return -1

    def update_analytics_engagement_rate(self, social_account_id: int, engagement_rate: float) -> bool:
        """Update the engagement rate for the most recent analytics entry"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                UPDATE platform_analytics
                SET engagement_rate = ?
                WHERE social_account_id = ?
                AND snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM platform_analytics
                    WHERE social_account_id = ?
                )
            """, (engagement_rate, social_account_id, social_account_id))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error updating engagement rate: {e}")
            return False

    def get_latest_analytics(self, social_account_id: int) -> Optional[Dict]:
        """Get the most recent analytics snapshot for a social account"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT * FROM platform_analytics
                WHERE social_account_id = ?
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (social_account_id,))

            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'social_account_id': row['social_account_id'],
                    'snapshot_date': row['snapshot_date'],
                    'followers_count': row['followers_count'],
                    'following_count': row['following_count'],
                    'total_posts': row['total_posts'],
                    'avg_likes': row['avg_likes'],
                    'avg_comments': row['avg_comments'],
                    'avg_shares': row['avg_shares'],
                    'engagement_rate': row['engagement_rate'],
                    'demographics_data': json.loads(row['demographics_data']) if row['demographics_data'] else {},
                    'raw_data': json.loads(row['raw_data']) if row['raw_data'] else {},
                    'data_source': row['data_source']
                }
            return None
        except Exception as e:
            print(f"Error getting latest analytics: {e}")
            return None

    # --- Brief-Creator Link Operations ---

    def link_creator_to_brief(self, brief_id: int, creator_id: int, status: str = "pending") -> bool:
        """Link a creator to a brief"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            # Check if link already exists
            cursor.execute("""
                SELECT id FROM brief_creators
                WHERE brief_id = ? AND creator_id = ?
            """, (brief_id, creator_id))

            existing = cursor.fetchone()
            if existing:
                print(f"Creator {creator_id} is already linked to brief {brief_id}")
                return False

            cursor.execute("""
                INSERT INTO brief_creators (brief_id, creator_id, status)
                VALUES (?, ?, ?)
            """, (brief_id, creator_id, status))

            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error linking creator to brief: {e}")
            import traceback
            traceback.print_exc()
            return False

    def unlink_creator_from_brief(self, brief_id: int, creator_id: int) -> bool:
        """Unlink a creator from a brief"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()
            cursor.execute("""
                DELETE FROM brief_creators
                WHERE brief_id = ? AND creator_id = ?
            """, (brief_id, creator_id))
            self.db_adapter.commit()
            return True
        except Exception as e:
            print(f"Error unlinking creator from brief: {e}")
            return False

    # --- Creator Report Operations ---

    def save_creator_report(self, brief_id: int, creator_id: int, report_data: Dict) -> int:
        """Save a creator analysis report"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO creator_reports
                    (brief_id, creator_id, overall_score, natural_alignment_score, summary, strengths, concerns,
                     recommendations, analysis_cost, model_used, video_insights)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                """, (
                    brief_id,
                    creator_id,
                    report_data.get('overall_score', 0.0),
                    report_data.get('natural_alignment_score', 0.0),
                    report_data.get('summary', ''),
                    json.dumps(report_data.get('strengths', [])),
                    json.dumps(report_data.get('concerns', [])),
                    json.dumps(report_data.get('recommendations', [])),
                    report_data.get('analysis_cost', 0.0),
                    report_data.get('model_used', ''),
                    json.dumps(report_data.get('video_insights', []))
                ))
                result = cursor.fetchone()
                report_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO creator_reports
                    (brief_id, creator_id, overall_score, natural_alignment_score, summary, strengths, concerns,
                     recommendations, analysis_cost, model_used, video_insights)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    brief_id,
                    creator_id,
                    report_data.get('overall_score', 0.0),
                    report_data.get('natural_alignment_score', 0.0),
                    report_data.get('summary', ''),
                    json.dumps(report_data.get('strengths', [])),
                    json.dumps(report_data.get('concerns', [])),
                    json.dumps(report_data.get('recommendations', [])),
                    report_data.get('analysis_cost', 0.0),
                    report_data.get('model_used', ''),
                    json.dumps(report_data.get('video_insights', []))
                ))
                report_id = cursor.lastrowid

            self.db_adapter.commit()
            return report_id
        except Exception as e:
            print(f"Error saving creator report: {e}")
            return -1

    def get_creator_report(self, brief_id: int, creator_id: int) -> Optional[Dict]:
        """Get the most recent report for a creator in a brief"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT * FROM creator_reports
                WHERE brief_id = ? AND creator_id = ?
                ORDER BY generated_at DESC
                LIMIT 1
            """, (brief_id, creator_id))

            row = cursor.fetchone()

            if row:
                return {
                    'id': row['id'],
                    'brief_id': row['brief_id'],
                    'creator_id': row['creator_id'],
                    'overall_score': row['overall_score'],
                    'natural_alignment_score': row['natural_alignment_score'],
                    'summary': row['summary'],
                    'strengths': json.loads(row['strengths']) if row['strengths'] else [],
                    'concerns': json.loads(row['concerns']) if row['concerns'] else [],
                    'recommendations': json.loads(row['recommendations']) if row['recommendations'] else [],
                    'analysis_cost': row['analysis_cost'],
                    'model_used': row['model_used'],
                    'generated_at': row['generated_at']
                }
            return None
        except Exception as e:
            print(f"Error getting creator report: {e}")
            return None

    def get_reports_for_brief(self, brief_id: int) -> pd.DataFrame:
        """Get all reports for a brief"""
        return self._read_sql_query("""
            SELECT cr.*, c.name as creator_name, c.primary_platform
            FROM creator_reports cr
            JOIN creators c ON cr.creator_id = c.id
            WHERE cr.brief_id = ?
            ORDER BY cr.generated_at DESC
        """, params=(brief_id,))

    def delete_creator_report(self, report_id: int, user_id: int) -> bool:
        """
        Delete a creator report

        Args:
            report_id: Report ID to delete
            user_id: User ID (for authorization check)

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            # Verify the report belongs to the user (through the brief)
            cursor.execute("""
                SELECT cr.id
                FROM creator_reports cr
                JOIN briefs b ON cr.brief_id = b.id
                WHERE cr.id = ? AND b.user_id = ?
            """, (report_id, user_id))

            if not cursor.fetchone():
                print(f"Report {report_id} not found or doesn't belong to user {user_id}")
                return False

            # Delete the report
            cursor.execute("DELETE FROM creator_reports WHERE id = ?", (report_id,))
            self.db_adapter.commit()
            return True

        except Exception as e:
            print(f"Error deleting report: {e}")
            return False

    # --- Post Analysis Operations ---

    def save_post_analysis(self, social_account_id: int, post_data: Dict) -> int:
        """Save post analysis data"""
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            if self.db_adapter.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO post_analysis
                    (social_account_id, post_id, post_url, post_date, post_type, caption,
                     likes_count, comments_count, shares_count, views_count, duration_seconds,
                     sentiment_score, content_themes, brand_safety_score, natural_alignment_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                """, (
                    social_account_id,
                    post_data.get('post_id', ''),
                    post_data.get('post_url', ''),
                    post_data.get('post_date'),
                    post_data.get('post_type', ''),
                    post_data.get('caption', ''),
                    post_data.get('likes_count', 0),
                    post_data.get('comments_count', 0),
                    post_data.get('shares_count', 0),
                    post_data.get('views_count', 0),
                    post_data.get('duration_seconds', 0.0),
                    post_data.get('sentiment_score', 0.0),
                    json.dumps(post_data.get('content_themes', [])),
                    post_data.get('brand_safety_score', 0.0),
                    post_data.get('natural_alignment_score', 0.0)
                ))
                result = cursor.fetchone()
                post_analysis_id = result['id'] if result else -1
            else:
                cursor.execute("""
                    INSERT INTO post_analysis
                    (social_account_id, post_id, post_url, post_date, post_type, caption,
                     likes_count, comments_count, shares_count, views_count, duration_seconds,
                     sentiment_score, content_themes, brand_safety_score, natural_alignment_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    social_account_id,
                    post_data.get('post_id', ''),
                    post_data.get('post_url', ''),
                    post_data.get('post_date'),
                    post_data.get('post_type', ''),
                    post_data.get('caption', ''),
                    post_data.get('likes_count', 0),
                    post_data.get('comments_count', 0),
                    post_data.get('shares_count', 0),
                    post_data.get('views_count', 0),
                    post_data.get('duration_seconds', 0.0),
                    post_data.get('sentiment_score', 0.0),
                    json.dumps(post_data.get('content_themes', [])),
                    post_data.get('brand_safety_score', 0.0),
                    post_data.get('natural_alignment_score', 0.0)
                ))
                post_analysis_id = cursor.lastrowid

            self.db_adapter.commit()
            return post_analysis_id
        except Exception as e:
            print(f"Error saving post analysis: {e}")
            return -1

    def get_posts_for_account(self, social_account_id: int, limit: int = 50) -> pd.DataFrame:
        """Get analyzed posts for a social account"""
        return self._read_sql_query("""
            SELECT * FROM post_analysis
            WHERE social_account_id = ?
            ORDER BY post_date DESC
            LIMIT ?
        """, params=(social_account_id, limit))

    # === Deep Research Methods ===

    def save_deep_research_query(self, query_data: Dict) -> int:
        """
        Save a Deep Research query and result to database

        Args:
            query_data: Dictionary with keys:
                - query_hash: Unique hash of query
                - query_text: Full query text
                - query_type: 'demographics' | 'background' | 'market'
                - creator_id: Creator ID (optional)
                - social_account_id: Social account ID (optional)
                - interaction_id: Gemini interaction ID
                - status: 'pending' | 'running' | 'completed' | 'failed'
                - result_data: JSON result (optional)
                - citations: JSON citations (optional)
                - cost: Cost in USD
                - input_tokens: Number of input tokens
                - output_tokens: Number of output tokens
                - expires_at: Cache expiration datetime (optional)
                - error_message: Error message if failed (optional)

        Returns:
            Query ID
        """
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        if self.db_adapter.db_type == "postgresql":
            cursor.execute("""
                INSERT INTO deep_research_queries (
                    query_hash, query_text, query_type, creator_id, social_account_id,
                    interaction_id, status, result_data, citations, cost,
                    input_tokens, output_tokens, completed_at, expires_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """, (
                query_data['query_hash'],
                query_data['query_text'],
                query_data['query_type'],
                query_data.get('creator_id'),
                query_data.get('social_account_id'),
                query_data.get('interaction_id', ''),
                query_data.get('status', 'pending'),
                json.dumps(query_data.get('result_data')) if query_data.get('result_data') else None,
                json.dumps(query_data.get('citations')) if query_data.get('citations') else None,
                query_data.get('cost', 0.0),
                query_data.get('input_tokens', 0),
                query_data.get('output_tokens', 0),
                datetime.now() if query_data.get('status') == 'completed' else None,
                query_data.get('expires_at'),
                query_data.get('error_message')
            ))
            result = cursor.fetchone()
            query_id = result['id'] if result else -1
        else:
            cursor.execute("""
                INSERT INTO deep_research_queries (
                    query_hash, query_text, query_type, creator_id, social_account_id,
                    interaction_id, status, result_data, citations, cost,
                    input_tokens, output_tokens, completed_at, expires_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query_data['query_hash'],
                query_data['query_text'],
                query_data['query_type'],
                query_data.get('creator_id'),
                query_data.get('social_account_id'),
                query_data.get('interaction_id', ''),
                query_data.get('status', 'pending'),
                json.dumps(query_data.get('result_data')) if query_data.get('result_data') else None,
                json.dumps(query_data.get('citations')) if query_data.get('citations') else None,
                query_data.get('cost', 0.0),
                query_data.get('input_tokens', 0),
                query_data.get('output_tokens', 0),
                datetime.now() if query_data.get('status') == 'completed' else None,
                query_data.get('expires_at'),
                query_data.get('error_message')
            ))
            query_id = cursor.lastrowid

        self.db_adapter.commit()
        return query_id

    def get_cached_deep_research(self, query_hash: str) -> Optional[Dict]:
        """
        Get cached Deep Research result by query hash

        Args:
            query_hash: Query hash

        Returns:
            Query result dictionary or None if not found/expired
        """
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        cursor.execute("""
            SELECT * FROM deep_research_queries
            WHERE query_hash = ?
            AND status = 'completed'
            AND (expires_at IS NULL OR expires_at > datetime('now'))
            ORDER BY completed_at DESC
            LIMIT 1
        """, (query_hash,))

        row = cursor.fetchone()

        if row:
            return {
                'id': row['id'],
                'query_hash': row['query_hash'],
                'query_text': row['query_text'],
                'query_type': row['query_type'],
                'creator_id': row['creator_id'],
                'social_account_id': row['social_account_id'],
                'interaction_id': row['interaction_id'],
                'status': row['status'],
                'result_data': json.loads(row['result_data']) if row['result_data'] else {},
                'citations': json.loads(row['citations']) if row['citations'] else [],
                'cost': row['cost'],
                'input_tokens': row['input_tokens'],
                'output_tokens': row['output_tokens'],
                'created_at': row['created_at'],
                'completed_at': row['completed_at'],
                'expires_at': row['expires_at']
            }
        return None

    def get_deep_research_by_creator(self, creator_id: int, query_type: Optional[str] = None) -> pd.DataFrame:
        """
        Get all Deep Research queries for a creator

        Args:
            creator_id: Creator ID
            query_type: Optional filter by query type

        Returns:
            DataFrame of queries
        """
        if query_type:
            return self._read_sql_query("""
                SELECT * FROM deep_research_queries
                WHERE creator_id = ? AND query_type = ?
                ORDER BY created_at DESC
            """, params=(creator_id, query_type))
        else:
            return self._read_sql_query("""
                SELECT * FROM deep_research_queries
                WHERE creator_id = ?
                ORDER BY created_at DESC
            """, params=(creator_id,))

    def save_demographics_data(self, social_account_id: int, demographics: Dict):
        """
        Update demographics_data in platform_analytics

        Args:
            social_account_id: Social account ID
            demographics: Demographics dictionary
        """
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            # Check if there's an existing analytics record for today
            cursor.execute("""
                SELECT id FROM platform_analytics
                WHERE social_account_id = ?
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (social_account_id,))

            row = cursor.fetchone()
            demographics_json = json.dumps(demographics)

            if row:
                # Update existing record
                cursor.execute("""
                    UPDATE platform_analytics
                    SET demographics_data = ?
                    WHERE id = ?
                """, (demographics_json, row['id']))
                print(f"  [DB] Updated demographics for platform_analytics id={row['id']}")
            else:
                # Create new record
                cursor.execute("""
                    INSERT INTO platform_analytics (
                        social_account_id, snapshot_date, demographics_data, data_source
                    ) VALUES (?, date('now'), ?, 'deep_research')
                """, (social_account_id, demographics_json))
                print(f"  [DB] Created new platform_analytics record with demographics for account_id={social_account_id}")

            self.db_adapter.commit()
        except Exception as e:
            print(f"  [DB ERROR] Failed to save demographics: {type(e).__name__}: {e}")
            raise

    def get_demographics_data(self, social_account_id: int) -> Optional[Dict]:
        """
        Get most recent demographics data for a social account

        Args:
            social_account_id: Social account ID

        Returns:
            Demographics dictionary or None
        """
        try:
            conn = self._get_connection()
            cursor = self.db_adapter.cursor()

            cursor.execute("""
                SELECT demographics_data, snapshot_date
                FROM platform_analytics
                WHERE social_account_id = ?
                AND demographics_data IS NOT NULL
                AND demographics_data != ''
                AND demographics_data != '{}'
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (social_account_id,))

            row = cursor.fetchone()

            if row and row['demographics_data']:
                try:
                    demographics = json.loads(row['demographics_data'])
                    # Filter out empty demographics
                    if not demographics or (isinstance(demographics, dict) and not any(demographics.values())):
                        return None
                    demographics['snapshot_date'] = row['snapshot_date']
                    return demographics
                except json.JSONDecodeError as e:
                    print(f"  [DB ERROR] Failed to parse demographics JSON: {e}")
                    return None
            return None
        except Exception as e:
            print(f"  [DB ERROR] Failed to retrieve demographics: {type(e).__name__}: {e}")
            return None

    # ========== Campaign Assets Methods ==========

    def save_campaign_asset(
        self,
        user_id: int,
        brief_id: int,
        creator_id: int,
        asset_type: str,
        asset_subtype: str,
        file_path: str,
        thumbnail_path: str,
        prompt_used: str,
        model_used: str,
        generation_params: dict,
        cost: float,
        status: str = 'completed',
        error_message: str = None,
        metadata: dict = None
    ) -> int:
        """
        Save a generated campaign asset to database

        Args:
            user_id: User ID
            brief_id: Brief ID
            creator_id: Creator ID
            asset_type: 'image' or 'video'
            asset_subtype: 'concept' or 'stats'
            file_path: Path to saved asset file
            thumbnail_path: Path to thumbnail (for videos)
            prompt_used: The prompt used for generation
            model_used: Model name used for generation
            generation_params: JSON dict of generation parameters
            cost: Cost of generation
            status: Status ('pending', 'generating', 'completed', 'failed')
            error_message: Error message if failed
            metadata: JSON dict of metadata

        Returns:
            Asset ID
        """
        import json
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        if self.db_adapter.db_type == "postgresql":
            cursor.execute("""
                INSERT INTO campaign_assets (
                    user_id, brief_id, creator_id, asset_type, asset_subtype,
                    file_path, thumbnail_path, prompt_used, model_used,
                    generation_params, cost, status, error_message, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """, (
                user_id, brief_id, creator_id, asset_type, asset_subtype,
                file_path, thumbnail_path, prompt_used, model_used,
                json.dumps(generation_params) if generation_params else None,
                cost, status, error_message,
                json.dumps(metadata) if metadata else None
            ))
            result = cursor.fetchone()
            asset_id = result['id'] if result else -1
        else:
            cursor.execute("""
                INSERT INTO campaign_assets (
                    user_id, brief_id, creator_id, asset_type, asset_subtype,
                    file_path, thumbnail_path, prompt_used, model_used,
                    generation_params, cost, status, error_message, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, brief_id, creator_id, asset_type, asset_subtype,
                file_path, thumbnail_path, prompt_used, model_used,
                json.dumps(generation_params) if generation_params else None,
                cost, status, error_message,
                json.dumps(metadata) if metadata else None
            ))
            asset_id = cursor.lastrowid

        self.db_adapter.commit()

        return asset_id

    def get_campaign_assets(
        self,
        user_id: int,
        brief_id: int = None,
        creator_id: int = None,
        asset_type: str = None
    ) -> pd.DataFrame:
        """
        Get campaign assets with optional filters

        Args:
            user_id: User ID
            brief_id: Optional brief ID filter
            creator_id: Optional creator ID filter
            asset_type: Optional asset type filter ('image' or 'video')

        Returns:
            DataFrame of assets
        """
        query = "SELECT * FROM campaign_assets WHERE user_id = ?"
        params = [user_id]

        if brief_id is not None:
            query += " AND brief_id = ?"
            params.append(brief_id)

        if creator_id is not None:
            query += " AND creator_id = ?"
            params.append(creator_id)

        if asset_type is not None:
            query += " AND asset_type = ?"
            params.append(asset_type)

        query += " ORDER BY created_at DESC"

        return self._read_sql_query(query, params=tuple(params))

    def get_campaign_asset(self, asset_id: int) -> Optional[dict]:
        """
        Get a single campaign asset by ID

        Args:
            asset_id: Asset ID

        Returns:
            Asset dict or None
        """
        import json
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        cursor.execute("SELECT * FROM campaign_assets WHERE id = ?", (asset_id,))
        row = cursor.fetchone()

        if row:
            columns = [
                'id', 'user_id', 'brief_id', 'creator_id', 'asset_type',
                'asset_subtype', 'file_path', 'thumbnail_path', 'prompt_used',
                'model_used', 'generation_params', 'cost', 'status',
                'error_message', 'metadata', 'created_at'
            ]
            asset = dict(zip(columns, row))

            # Parse JSON fields
            if asset['generation_params']:
                try:
                    asset['generation_params'] = json.loads(asset['generation_params'])
                except:
                    pass

            if asset['metadata']:
                try:
                    asset['metadata'] = json.loads(asset['metadata'])
                except:
                    pass

            return asset

        return None

    def delete_campaign_asset(self, user_id: int, asset_id: int) -> bool:
        """
        Delete a campaign asset

        Args:
            user_id: User ID (for security)
            asset_id: Asset ID

        Returns:
            True if deleted
        """
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        cursor.execute(
            "DELETE FROM campaign_assets WHERE id = ? AND user_id = ?",
            (asset_id, user_id)
        )

        deleted = cursor.rowcount > 0
        self.db_adapter.commit()

        return deleted

    def update_asset_status(
        self,
        asset_id: int,
        status: str,
        error_message: str = None
    ) -> bool:
        """
        Update asset generation status

        Args:
            asset_id: Asset ID
            status: New status
            error_message: Optional error message

        Returns:
            True if updated
        """
        conn = self._get_connection()
        cursor = self.db_adapter.cursor()

        cursor.execute(
            "UPDATE campaign_assets SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, asset_id)
        )

        updated = cursor.rowcount > 0
        self.db_adapter.commit()

        return updated


# Singleton instance
_db_instance = None


def get_db() -> DatabaseManager:
    """Get singleton database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance
