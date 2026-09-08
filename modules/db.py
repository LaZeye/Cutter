"""SQLite access layer for Cutter."""

import os
import sqlite3
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database", "cutter.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL UNIQUE,
    weight     REAL    NOT NULL,
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(date);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "target_weight": "155.0",
    "fight_date": "",
    "camp_start": "",
    "alpha": "0.10",
    "unit": "lb",
}


def get_connection():
    """Open a connection with row access by column name."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables and seed default settings. Safe to call repeatedly."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


# --- entries ---------------------------------------------------------------

def list_entries():
    """All weigh-ins, oldest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, weight, note FROM entries ORDER BY date ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_entry(entry_date, weight, note=None):
    """Insert a weigh-in, or overwrite the existing one for that date."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO entries (date, weight, note)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                weight = excluded.weight,
                note   = excluded.note
            """,
            (entry_date, weight, note),
        )


def delete_entry(entry_date):
    """Remove the weigh-in for a date. Returns True if a row was deleted."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM entries WHERE date = ?", (entry_date,))
        return cur.rowcount > 0


# --- settings --------------------------------------------------------------

def get_settings():
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    settings.update({r["key"]: r["value"] for r in rows})
    return settings


def save_settings(values):
    """Persist any subset of known settings keys."""
    allowed = set(DEFAULT_SETTINGS)
    with get_connection() as conn:
        for key, value in values.items():
            if key in allowed:
                conn.execute(
                    """
                    INSERT INTO settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, str(value)),
                )


def today_iso():
    return date.today().isoformat()