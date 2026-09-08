"""SQLite access layer for Cutter.

Weigh-ins live in one table for all time. A camp is a named date range with a
target, so camp views are derived by filtering rather than duplicating rows —
one source of truth, no chance of two copies disagreeing.
"""

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

CREATE TABLE IF NOT EXISTS camps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    start_date    TEXT    NOT NULL,
    fight_date    TEXT    NOT NULL,
    target_weight REAL    NOT NULL,
    ended_on      TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_camps_start ON camps(start_date);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
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


# --- weigh-ins -------------------------------------------------------------

def list_entries():
    """Every weigh-in ever recorded, oldest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, weight, note FROM entries ORDER BY date ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_entry(entry_date):
    """The weigh-in saved for a date, if there is one."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT date, weight, note FROM entries WHERE date = ?", (entry_date,)
        ).fetchone()
    return dict(row) if row else None


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


# --- camps -----------------------------------------------------------------

def list_camps():
    """All camps, most recent first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM camps ORDER BY start_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def active_camp():
    """The camp currently being run, if any."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM camps WHERE ended_on IS NULL ORDER BY start_date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_camp(camp_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM camps WHERE id = ?", (camp_id,)).fetchone()
    return dict(row) if row else None


def create_camp(name, start_date, fight_date, target_weight):
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO camps (name, start_date, fight_date, target_weight)
            VALUES (?, ?, ?, ?)
            """,
            (name, start_date, fight_date, target_weight),
        )
        return cur.lastrowid


def update_camp(camp_id, name, start_date, fight_date, target_weight):
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE camps
               SET name = ?, start_date = ?, fight_date = ?, target_weight = ?
             WHERE id = ?
            """,
            (name, start_date, fight_date, target_weight, camp_id),
        )
        return cur.rowcount > 0


def end_camp(camp_id, ended_on):
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE camps SET ended_on = ? WHERE id = ? AND ended_on IS NULL",
            (ended_on, camp_id),
        )
        return cur.rowcount > 0


def reopen_camp(camp_id):
    with get_connection() as conn:
        cur = conn.execute("UPDATE camps SET ended_on = NULL WHERE id = ?", (camp_id,))
        return cur.rowcount > 0


def delete_camp(camp_id):
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM camps WHERE id = ?", (camp_id,))
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