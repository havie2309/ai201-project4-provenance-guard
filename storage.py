"""
storage.py — structured audit log backed by SQLite.

Every attribution decision and every appeal gets a row here. This is the
single source of truth the /log endpoint reads from and the README's
audit-log evidence is pulled from.
"""

import sqlite3
import json
from datetime import datetime, timezone

DB_PATH = "audit_log.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT NOT NULL,
            creator_id TEXT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,          -- "classification" or "appeal"
            attribution TEXT,                  -- likely_ai / uncertain / likely_human
            confidence REAL,
            llm_score REAL,
            stylometric_score REAL,
            label TEXT,
            status TEXT,                       -- "classified" or "under_review"
            appeal_reasoning TEXT,
            text_excerpt TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_classification(content_id, creator_id, text, attribution, confidence,
                        llm_score, stylometric_score, label):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO audit_log
        (content_id, creator_id, timestamp, event_type, attribution,
         confidence, llm_score, stylometric_score, label, status, text_excerpt)
        VALUES (?, ?, ?, 'classification', ?, ?, ?, ?, ?, 'classified', ?)
    """, (
        content_id, creator_id, datetime.now(timezone.utc).isoformat(),
        attribution, confidence, llm_score, stylometric_score, label,
        text[:200]
    ))
    conn.commit()
    conn.close()


def log_appeal(content_id, creator_reasoning):
    """Appends an appeal entry and flips the original entry's status."""
    conn = sqlite3.connect(DB_PATH)

    # Update the original classification row's status
    conn.execute("""
        UPDATE audit_log SET status = 'under_review'
        WHERE content_id = ? AND event_type = 'classification'
    """, (content_id,))

    # Append a linked appeal entry
    conn.execute("""
        INSERT INTO audit_log
        (content_id, timestamp, event_type, status, appeal_reasoning)
        VALUES (?, ?, 'appeal', 'under_review', ?)
    """, (content_id, datetime.now(timezone.utc).isoformat(), creator_reasoning))

    conn.commit()
    conn.close()


def content_exists(content_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM audit_log WHERE content_id = ? AND event_type = 'classification'",
        (content_id,)
    ).fetchone()
    conn.close()
    return row is not None


def get_log(limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]