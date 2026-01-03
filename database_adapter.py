"""
Database adapter layer for supporting both SQLite and PostgreSQL
"""
from typing import Any, Optional, Tuple, List
import config


class AdapterCursor:
    """Wrapper cursor that automatically converts SQL syntax"""

    def __init__(self, cursor, adapter):
        self.cursor = cursor
        self.adapter = adapter

    def execute(self, query, params=None):
        """Execute with automatic query conversion"""
        converted_query = self.adapter.convert_query(query)
        if params:
            self.cursor.execute(converted_query, params)
        else:
            self.cursor.execute(converted_query)

    def executemany(self, query, params_list):
        """Execute many with automatic query conversion"""
        converted_query = self.adapter.convert_query(query)
        self.cursor.executemany(converted_query, params_list)

    def fetchone(self):
        """Fetch one row"""
        row = self.cursor.fetchone()
        if row is None:
            return None
        # Return dict for both databases
        if self.adapter.db_type == "sqlite":
            return dict(row) if row else None
        elif self.adapter.db_type == "postgresql":
            return dict(row) if row else None

    def fetchall(self):
        """Fetch all rows"""
        rows = self.cursor.fetchall()
        # Return list of dicts for both databases
        if self.adapter.db_type == "sqlite":
            return [dict(row) for row in rows]
        elif self.adapter.db_type == "postgresql":
            return [dict(row) for row in rows]

    @property
    def lastrowid(self):
        """Get last row ID"""
        if self.adapter.db_type == "sqlite":
            return self.cursor.lastrowid
        elif self.adapter.db_type == "postgresql":
            # For PostgreSQL, this should use RETURNING clause
            # Return None to force using RETURNING
            return None

    @property
    def rowcount(self):
        """Get row count"""
        return self.cursor.rowcount


class DatabaseAdapter:
    """Abstract database operations to support both SQLite and PostgreSQL"""

    def __init__(self, db_type: str, connection_string: Optional[str] = None):
        """
        Initialize database adapter

        Args:
            db_type: 'sqlite' or 'postgresql'
            connection_string: For PostgreSQL, connection string; for SQLite, file path
        """
        self.db_type = db_type
        self.connection_string = connection_string
        self.conn = None

    def connect(self):
        """Establish database connection"""
        if self.db_type == "sqlite":
            import sqlite3
            self.conn = sqlite3.connect(self.connection_string, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        elif self.db_type == "postgresql":
            import psycopg2
            import psycopg2.extras
            self.conn = psycopg2.connect(self.connection_string)
            self.conn.autocommit = False
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")

        return self.conn

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def cursor(self):
        """Get database cursor with adapter wrapper"""
        if not self.conn:
            self.connect()

        if self.db_type == "sqlite":
            raw_cursor = self.conn.cursor()
        elif self.db_type == "postgresql":
            import psycopg2.extras
            raw_cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Wrap cursor to intercept execute calls
        return AdapterCursor(raw_cursor, self)

    def commit(self):
        """Commit transaction"""
        if self.conn:
            self.conn.commit()

    def rollback(self):
        """Rollback transaction"""
        if self.conn:
            self.conn.rollback()

    def convert_query(self, query: str) -> str:
        """
        Convert SQL query from SQLite syntax to PostgreSQL syntax

        Args:
            query: SQL query string

        Returns:
            Converted query string
        """
        if self.db_type == "sqlite":
            return query

        # Convert SQLite to PostgreSQL syntax
        converted = query

        # AUTOINCREMENT -> SERIAL
        converted = converted.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        converted = converted.replace("AUTOINCREMENT", "")

        # DATETIME -> TIMESTAMP
        converted = converted.replace("DATETIME", "TIMESTAMP")

        # Date/time functions
        converted = converted.replace("DATE('now')", "CURRENT_DATE")
        converted = converted.replace("date('now')", "CURRENT_DATE")
        converted = converted.replace("DATETIME('now')", "CURRENT_TIMESTAMP")
        converted = converted.replace("datetime('now')", "CURRENT_TIMESTAMP")

        # Parameter placeholders: ? -> %s
        if "?" in converted:
            # For PostgreSQL, we need to replace ? with %s
            converted = converted.replace("?", "%s")

        return converted

    def execute(self, cursor, query: str, params: Optional[Tuple] = None):
        """
        Execute a SQL query with parameters

        Args:
            cursor: Database cursor
            query: SQL query
            params: Query parameters
        """
        converted_query = self.convert_query(query)

        if params:
            cursor.execute(converted_query, params)
        else:
            cursor.execute(converted_query)

    def executemany(self, cursor, query: str, params_list: List[Tuple]):
        """
        Execute a SQL query multiple times with different parameters

        Args:
            cursor: Database cursor
            query: SQL query
            params_list: List of parameter tuples
        """
        converted_query = self.convert_query(query)
        cursor.executemany(converted_query, params_list)

    def fetchone(self, cursor) -> Optional[dict]:
        """
        Fetch one row from cursor

        Returns:
            Dictionary of column name -> value
        """
        row = cursor.fetchone()
        if row is None:
            return None

        if self.db_type == "sqlite":
            return dict(row)
        elif self.db_type == "postgresql":
            return dict(row)

    def fetchall(self, cursor) -> List[dict]:
        """
        Fetch all rows from cursor

        Returns:
            List of dictionaries of column name -> value
        """
        rows = cursor.fetchall()

        if self.db_type == "sqlite":
            return [dict(row) for row in rows]
        elif self.db_type == "postgresql":
            return [dict(row) for row in rows]

    def check_column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        """
        Check if a column exists in a table

        Args:
            cursor: Database cursor (AdapterCursor or raw cursor)
            table_name: Name of the table
            column_name: Name of the column

        Returns:
            True if column exists, False otherwise
        """
        # Get the raw cursor if wrapped
        raw_cursor = cursor.cursor if isinstance(cursor, AdapterCursor) else cursor

        if self.db_type == "sqlite":
            raw_cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in raw_cursor.fetchall()]
            return column_name in columns
        elif self.db_type == "postgresql":
            raw_cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
            """, (table_name, column_name))
            return raw_cursor.fetchone() is not None

    def get_autoincrement_syntax(self) -> str:
        """
        Get auto-increment syntax for primary key

        Returns:
            Auto-increment syntax
        """
        if self.db_type == "sqlite":
            return "INTEGER PRIMARY KEY AUTOINCREMENT"
        elif self.db_type == "postgresql":
            return "SERIAL PRIMARY KEY"

    def get_boolean_type(self) -> str:
        """
        Get boolean column type

        Returns:
            Boolean type syntax
        """
        if self.db_type == "sqlite":
            return "INTEGER"  # SQLite uses 0/1 for boolean
        elif self.db_type == "postgresql":
            return "BOOLEAN"

    def get_datetime_type(self) -> str:
        """
        Get datetime column type

        Returns:
            Datetime type syntax
        """
        if self.db_type == "sqlite":
            return "DATETIME"
        elif self.db_type == "postgresql":
            return "TIMESTAMP"


def get_database_adapter() -> DatabaseAdapter:
    """
    Factory function to create appropriate database adapter

    Returns:
        DatabaseAdapter instance configured for current environment
    """
    if config.DATABASE_TYPE == "postgresql":
        return DatabaseAdapter("postgresql", config.DATABASE_URL)
    else:
        return DatabaseAdapter("sqlite", config.DATABASE_PATH)
