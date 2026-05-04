from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import get_settings


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    path = get_settings().db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              email TEXT,
              created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS google_credentials (
              id TEXT PRIMARY KEY,
              user_id TEXT,
              credentials_json TEXT NOT NULL,
              scopes_json TEXT,
              expires_at TEXT,
              created_at TEXT,
              updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_specs (
              id TEXT PRIMARY KEY,
              user_id TEXT,
              name TEXT,
              type TEXT,
              status TEXT,
              spec_json TEXT NOT NULL,
              created_at TEXT,
              updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_runs (
              id TEXT PRIMARY KEY,
              automation_id TEXT,
              status TEXT,
              input_json TEXT,
              output_json TEXT,
              error_message TEXT,
              started_at TEXT,
              finished_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candidate_records_cache (
              id TEXT PRIMARY KEY,
              automation_id TEXT,
              sheet_row_number INTEGER,
              candidate_name TEXT,
              email TEXT,
              phone TEXT,
              apply_date TEXT,
              status TEXT,
              cv_link TEXT,
              note_link TEXT,
              last_seen_hash TEXT,
              updated_at TEXT
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            ("default", None, utcnow()),
        )


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)
