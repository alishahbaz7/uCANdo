"""Persistence layer — a thin, thread-safe SQLite store.

This is the rail the later pillars ride on:

* **oem_profiles** — the India-first OEM CAN database (Pillar A): per
  ``(oem, model, year-range, bus)`` signal definitions + a frame *signature*
  used to auto-identify a vehicle from live traffic.
* **vehicles** — the fleet/telematics vehicle registry.
* **captures** — an index of recorded logs (the files live on disk; this is
  metadata + a pointer).
* **jobs** — automation jobs (scheduled/triggered captures, scans, exports).
* **settings** — a key→JSON store backing app config and saved profiles.

The app is multi-threaded (logger recv thread, scheduler, replay), so a single
connection is opened with ``check_same_thread=False`` in WAL mode and every
mutation is serialized through one lock. Reads are cheap and concurrent under
WAL. The schema is a plain list of ``CREATE TABLE IF NOT EXISTS`` statements —
add a table by appending one entry, no migration framework required yet.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional

# Each entry is an idempotent DDL statement. Append to extend the schema.
SCHEMA: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL              -- JSON-encoded
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oem_profiles (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        oem        TEXT NOT NULL,
        platform   TEXT DEFAULT '',
        model      TEXT DEFAULT '',
        year_min   INTEGER,
        year_max   INTEGER,
        bus        TEXT DEFAULT 'CAN',
        bitrate    INTEGER DEFAULT 500000,
        name       TEXT NOT NULL,
        dbc        TEXT DEFAULT '',       -- the signal definitions (DBC text)
        signature  TEXT DEFAULT '{}',     -- JSON frame fingerprint for auto-ID
        version    INTEGER DEFAULT 1,
        status     TEXT DEFAULT 'draft',  -- draft | reviewed | shipped
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vehicles (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        oem        TEXT DEFAULT '',
        model      TEXT DEFAULT '',
        year       INTEGER,
        vin        TEXT DEFAULT '',
        profile_id INTEGER,               -- FK -> oem_profiles.id (matched profile)
        meta       TEXT DEFAULT '{}',     -- JSON
        created_at REAL NOT NULL,
        FOREIGN KEY (profile_id) REFERENCES oem_profiles(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS captures (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        path       TEXT NOT NULL,
        format     TEXT DEFAULT '',
        vehicle_id INTEGER,
        frames     INTEGER DEFAULT 0,
        duration_s REAL DEFAULT 0,
        meta       TEXT DEFAULT '{}',
        created_at REAL NOT NULL,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        kind       TEXT NOT NULL,         -- capture | scan | export | rule
        schedule   TEXT DEFAULT '',       -- cron-like or '' for trigger-only
        spec       TEXT DEFAULT '{}',     -- JSON job parameters
        enabled    INTEGER DEFAULT 1,
        last_run   REAL,
        created_at REAL NOT NULL
    )
    """,
]

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "canforge.db"
)


class Storage:
    """Thread-safe SQLite wrapper with small per-table conveniences."""

    def __init__(self, path: str = DEFAULT_DB_PATH):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.init_schema()

    def init_schema(self) -> None:
        with self._lock:
            for ddl in SCHEMA:
                self._conn.execute(ddl)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----- generic helpers -------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a write statement; returns ``lastrowid``."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def insert(self, table: str, **cols) -> int:
        """Insert a row from kwargs; stamps ``created_at`` if the column exists."""
        cols.setdefault("created_at", round(time.time(), 3))
        keys = list(cols)
        placeholders = ", ".join("?" for _ in keys)
        sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})"
        return self.execute(sql, tuple(cols[k] for k in keys))

    def list(self, table: str, order: str = "id") -> list[dict]:
        return self.query(f"SELECT * FROM {table} ORDER BY {order}")

    def get(self, table: str, row_id: int) -> Optional[dict]:
        return self.query_one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))

    def delete(self, table: str, row_id: int) -> None:
        self.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    # ----- settings / config (key -> JSON) ---------------------------------
    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def all_settings(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.list("settings", order="key")}
