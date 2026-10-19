"""Migration: add `role` column to contributors table.

Run once against your existing database:

    python scripts/migrate_add_role.py

What this does (safely, without data loss):
  1. Adds `role TEXT NOT NULL DEFAULT 'member'` column.
  2. Back-fills every existing row to role='member'.
  3. Drops the old unique index on email alone.
  4. Creates the new composite unique index on (email, role).

SQLite does not support DROP CONSTRAINT, so we handle step 3 by
rebuilding the index rather than altering the table.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "axxspace.db"


def column_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def index_exists(cur: sqlite3.Cursor, index_name: str) -> bool:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
    )
    return cur.fetchone() is not None


def main() -> None:
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        sys.exit(1)

    print(f"Migrating: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # --- Step 1: Add role column if missing ----------------------------------
    if column_exists(cur, "contributors", "role"):
        print("[SKIP] 'role' column already exists.")
    else:
        print("[ADD ] Adding 'role' column with default 'member' …")
        cur.execute(
            "ALTER TABLE contributors ADD COLUMN role TEXT NOT NULL DEFAULT 'member'"
        )
        print("[OK  ] Column added.")

    # --- Step 2: Back-fill existing rows -------------------------------------
    cur.execute("UPDATE contributors SET role = 'member' WHERE role IS NULL OR role = ''")
    updated = cur.rowcount
    if updated:
        print(f"[FILL] Back-filled {updated} row(s) to role='member'.")
    else:
        print("[SKIP] No rows needed back-filling.")

    # --- Step 3: Drop old single-column email unique index if it exists ------
    # SQLite names auto-created unique indexes as sqlite_autoindex_<table>_<n>
    # or by a custom name. We drop any unique index on email alone.
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='contributors'"
    )
    indexes = cur.fetchall()
    for (idx_name,) in indexes:
        # Inspect the index columns
        cur.execute(f"PRAGMA index_info({idx_name})")
        cols = [row[2] for row in cur.fetchall()]
        if cols == ["email"]:
            print(f"[DROP] Dropping old unique index '{idx_name}' on (email) …")
            cur.execute(f"DROP INDEX IF EXISTS \"{idx_name}\"")
            print("[OK  ] Dropped.")

    # --- Step 4: Create composite unique index (email, role) -----------------
    composite_idx = "uq_contributor_email_role"
    if index_exists(cur, composite_idx):
        print(f"[SKIP] Composite index '{composite_idx}' already exists.")
    else:
        print(f"[ADD ] Creating composite unique index '{composite_idx}' on (email, role) …")
        cur.execute(
            f"CREATE UNIQUE INDEX \"{composite_idx}\" "
            "ON contributors (email, role) WHERE email IS NOT NULL"
        )
        print("[OK  ] Index created.")

    con.commit()
    con.close()
    print("\nMigration complete. ✓")


if __name__ == "__main__":
    main()
