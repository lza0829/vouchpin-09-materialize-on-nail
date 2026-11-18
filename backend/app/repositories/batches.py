from __future__ import annotations

import sqlite3
from typing import Any


def list_batches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM redeem_batches ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM redeem_batches WHERE id=?", (int(batch_id),)
    ).fetchone()
    return dict(row) if row else None


def create_batch(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO redeem_batches("
        "business_day, status, fact_count, total_amount, sealed_at, note, "
        "policy, event_scan_count, materialized_count, materialized_event_ids) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            fields["business_day"],
            fields.get("status") or "sealed",
            int(fields.get("fact_count") or 0),
            float(fields.get("total_amount") or 0),
            fields.get("sealed_at"),
            fields.get("note") or "",
            fields.get("policy") or "materialize_on_nail",
            int(fields.get("event_scan_count") or 0),
            int(fields.get("materialized_count") or 0),
            fields.get("materialized_event_ids") or "[]",
        ),
    )
    return int(cur.lastrowid)


def insert_item(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO redeem_batch_items("
        "batch_id, fact_id, event_id, coupon_code, campaign_code, amount, "
        "business_day, source) VALUES(?,?,?,?,?,?,?,?)",
        (
            int(fields["batch_id"]),
            int(fields["fact_id"]),
            int(fields["event_id"]),
            fields["coupon_code"],
            fields["campaign_code"],
            float(fields["amount"]),
            fields["business_day"],
            fields["source"],
        ),
    )
    return int(cur.lastrowid)


def list_items(conn: sqlite3.Connection, batch_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM redeem_batch_items WHERE batch_id=? ORDER BY event_id",
        (int(batch_id),),
    ).fetchall()
    return [dict(r) for r in rows]
