from __future__ import annotations

import sqlite3

from app.config import DB_PATH
from app.policy import SEAL_POLICY

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  face_value REAL NOT NULL,
  min_spend REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS coupon_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  coupon_code TEXT NOT NULL,
  campaign_code TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  business_day TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS redeem_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  coupon_code TEXT NOT NULL UNIQUE,
  campaign_code TEXT NOT NULL,
  amount REAL NOT NULL,
  business_day TEXT NOT NULL,
  event_id INTEGER NOT NULL,
  batch_id INTEGER,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS redeem_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  business_day TEXT NOT NULL,
  status TEXT NOT NULL,
  fact_count INTEGER NOT NULL DEFAULT 0,
  total_amount REAL NOT NULL DEFAULT 0,
  sealed_at TEXT,
  note TEXT NOT NULL DEFAULT '',
  policy TEXT NOT NULL DEFAULT 'materialize_on_nail',
  event_scan_count INTEGER NOT NULL DEFAULT 0,
  materialized_count INTEGER NOT NULL DEFAULT 0,
  materialized_event_ids TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS redeem_batch_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL,
  fact_id INTEGER NOT NULL,
  event_id INTEGER NOT NULL,
  coupon_code TEXT NOT NULL,
  campaign_code TEXT NOT NULL,
  amount REAL NOT NULL,
  business_day TEXT NOT NULL,
  source TEXT NOT NULL
);
'''

INDEXES = '''
CREATE INDEX IF NOT EXISTS idx_coupon_events_day_type
  ON coupon_events(business_day, event_type);
CREATE UNIQUE INDEX IF NOT EXISTS ux_redeem_facts_event
  ON redeem_facts(event_id);
CREATE INDEX IF NOT EXISTS idx_redeem_facts_day_status
  ON redeem_facts(business_day, status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_redeem_batch_items_fact
  ON redeem_batch_items(fact_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_redeem_batch_items_event
  ON redeem_batch_items(event_id);
'''

BATCH_EXTRA_COLUMNS = {
    "policy": f"TEXT NOT NULL DEFAULT '{SEAL_POLICY}'",
    "event_scan_count": "INTEGER NOT NULL DEFAULT 0",
    "materialized_count": "INTEGER NOT NULL DEFAULT 0",
    "materialized_event_ids": "TEXT NOT NULL DEFAULT '[]'",
}

FACT_COLUMNS = (
    "id, coupon_code, campaign_code, amount, business_day, event_id, batch_id, status"
)


def connect(immediate: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if immediate:
        conn.execute("BEGIN IMMEDIATE")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_redeem_batches(conn: sqlite3.Connection) -> None:
    have = _columns(conn, "redeem_batches")
    for name, decl in BATCH_EXTRA_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE redeem_batches ADD COLUMN {name} {decl}")


def _backfill_batch_items(conn: sqlite3.Connection) -> None:
    """Make legacy sealed facts visible as batch details (one source of truth)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO redeem_batch_items(
          batch_id, fact_id, event_id, coupon_code, campaign_code, amount,
          business_day, source
        )
        SELECT f.batch_id, f.id, f.event_id, f.coupon_code, f.campaign_code,
               f.amount, f.business_day, 'existing_fact'
        FROM redeem_facts f
        JOIN redeem_batches b ON b.id = f.batch_id
        WHERE f.batch_id IS NOT NULL
        """
    )


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate_redeem_batches(conn)
        conn.executescript(INDEXES)
        _backfill_batch_items(conn)
        conn.commit()
    finally:
        conn.close()
