"""
database/connection.py
======================
Provides a thread-safe SQLite connection factory with:
  - WAL journal mode (better concurrent reads)
  - Foreign-key enforcement
  - Row factory returning sqlite3.Row objects (dict-like access)
  - Schema auto-initialisation helper
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# Resolve schema.sql relative to this file so it works from any cwd
_SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """
    Open (or create) a SQLite database at *db_path* and return
    a configured connection.

    Enables:
      PRAGMA journal_mode = WAL    → WAL mode for better concurrency
      PRAGMA foreign_keys = ON     → enforce FK constraints
      PRAGMA synchronous = NORMAL  → safe & fast under WAL

    The row_factory is set to ``sqlite3.Row`` so callers can access
    columns by name as well as index.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Enable WAL mode and FK enforcement at every connection
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")

    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """
    Execute database/schema.sql against *conn* to create tables and
    indexes if they do not already exist.  Safe to call on every
    startup because all statements use ``CREATE TABLE IF NOT EXISTS``.
    """
    sql = _SCHEMA_SQL.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def get_and_init(db_path: str | Path) -> sqlite3.Connection:
    """
    Convenience wrapper: open the DB, apply the schema, return the
    connection.  Suitable for one-liner initialisation in scripts.

        conn = get_and_init("data/supermarket.db")
    """
    conn = get_connection(db_path)
    init_schema(conn)
    return conn
