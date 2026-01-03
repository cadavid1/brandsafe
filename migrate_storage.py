"""
Helper script to migrate storage.py to use database adapter
"""
import re

def migrate_storage_file(input_file, output_file):
    """Migrate storage.py to use database adapter"""

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Replace AUTOINCREMENT with adapter syntax in CREATE TABLE statements
    content = re.sub(
        r'INTEGER PRIMARY KEY AUTOINCREMENT',
        r'{self.db_adapter.get_autoincrement_syntax()}',
        content
    )

    # 2. Replace DATETIME with adapter syntax
    content = re.sub(
        r'\bDATETIME\b',
        r'{self.db_adapter.get_datetime_type()}',
        content
    )

    # 3. Replace cursor.execute( with self.db_adapter.execute(cursor,
    content = re.sub(
        r'cursor\.execute\(',
        r'self.db_adapter.execute(cursor, ',
        content
    )

    # 4. Replace cursor.lastrowid with handling for both databases
    # This requires RETURNING clause for PostgreSQL
    # We'll keep lastrowid but add a note that it needs manual fixes for INSERT statements

    # 5. Replace PRAGMA table_info with adapter method
    content = re.sub(
        r'cursor\.execute\(self\.db_adapter\.execute\(cursor, "PRAGMA table_info\(([^)]+)\)"\)',
        r'# Column check moved to adapter\n        # Original: PRAGMA table_info(\1)',
        content
    )

    # 6. Replace conn.cursor() with self.db_adapter.cursor()
    content = re.sub(
        r'conn\.cursor\(\)',
        r'self.db_adapter.cursor()',
        content
    )

    # 7. Replace conn.commit() with self.db_adapter.commit()
    content = re.sub(
        r'conn\.commit\(\)',
        r'self.db_adapter.commit()',
        content
    )

    # 8. Replace conn.close() with self.db_adapter.close()
    content = re.sub(
        r'conn\.close\(\)',
        r'# Connection managed by adapter',
        content
    )

    # 9. Replace fetchone() with self.db_adapter.fetchone(cursor)
    content = re.sub(
        r'cursor\.fetchone\(\)',
        r'self.db_adapter.fetchone(cursor)',
        content
    )

    # 10. Replace fetchall() with self.db_adapter.fetchall(cursor)
    content = re.sub(
        r'cursor\.fetchall\(\)',
        r'self.db_adapter.fetchall(cursor)',
        content
    )

    # 11. Fix double execute calls (from step 3 creating doubles)
    content = re.sub(
        r'self\.db_adapter\.execute\(cursor, self\.db_adapter\.execute\(cursor,',
        r'self.db_adapter.execute(cursor,',
        content
    )

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Migration complete. Output written to {output_file}")
    print("\nNOTE: Manual fixes still needed for:")
    print("1. INSERT statements with lastrowid (need RETURNING clause for PostgreSQL)")
    print("2. PRAGMA table_info statements (use adapter.check_column_exists)")
    print("3. ON CONFLICT DO UPDATE syntax")
    print("4. Date/time functions like CURRENT_TIMESTAMP, date('now'), etc.")
    print("5. Direct sqlite3.connect() calls in campaign asset methods")

if __name__ == "__main__":
    input_file = "storage.py"
    output_file = "storage_migrated.py"
    migrate_storage_file(input_file, output_file)
