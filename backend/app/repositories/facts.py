from __future__ import annotations
import sqlite3
from typing import Any


def list_facts(conn: sqlite3.Connection, business_day: str | None = None) -> list[dict[str, Any]]:
    if business_day:
        rows = conn.execute(
            "SELECT * FROM redeem_facts WHERE business_day=? ORDER BY id",
            (business_day,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM redeem_facts ORDER BY id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


def insert_fact(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO redeem_facts(coupon_code, campaign_code, amount, business_day, event_id, status) VALUES(?,?,?,?,?,?)",
        (
            fields["coupon_code"],
            fields["campaign_code"],
            float(fields["amount"]),
            fields["business_day"],
            int(fields["event_id"]),
            fields.get("status") or "open",
        ),
    )
    return int(cur.lastrowid)


def facts_for_coupons(
    conn: sqlite3.Connection, coupon_codes: list[str]
) -> dict[str, dict[str, Any]]:
    """Any existing fact per coupon code, regardless of day or status."""
    if not coupon_codes:
        return {}
    marks = ",".join("?" for _ in coupon_codes)
    rows = conn.execute(
        f"SELECT * FROM redeem_facts WHERE coupon_code IN ({marks})",
        [str(c) for c in coupon_codes],
    ).fetchall()
    return {str(r["coupon_code"]): dict(r) for r in rows}


def unbatched_redeem_events(conn: sqlite3.Connection, business_day: str) -> list[dict[str, Any]]:
    """Redeem events of the day not yet accounted for by any batch detail.

    The batch item table is the accounting ledger: an event with an item is
    sealed and never scanned again, whatever its fact status.  An event with no
    item is owed, and is either reused (existing fact) or materialized inside
    the nail transaction.
    """
    rows = conn.execute(
        """
        SELECT e.id AS event_id, e.coupon_code, e.campaign_code, e.amount,
               e.business_day, e.occurred_at,
               f.id AS fact_id, f.status AS fact_status, f.amount AS fact_amount,
               f.batch_id AS fact_batch_id,
               f.coupon_code AS fact_coupon_code, f.campaign_code AS fact_campaign_code,
               f.business_day AS fact_business_day
        FROM coupon_events e
        LEFT JOIN redeem_facts f ON f.event_id = e.id
        LEFT JOIN redeem_batch_items i ON i.event_id = e.id
        WHERE e.event_type='redeem' AND e.business_day=?
          AND i.id IS NULL
        ORDER BY e.id
        """,
        (business_day,),
    ).fetchall()
    return [dict(r) for r in rows]


def sealed_events_for_day(conn: sqlite3.Connection, business_day: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM redeem_batch_items WHERE business_day=? ORDER BY event_id",
        (business_day,),
    ).fetchall()
    return [dict(r) for r in rows]


def event_scan_for_day(conn: sqlite3.Connection, business_day: str) -> dict[str, int]:
    """Single source for event-side counts used by preview, seal and dashboard."""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "COUNT(CASE WHEN f.id IS NULL THEN 1 END) AS unmaterialized, "
        "COUNT(CASE WHEN i.id IS NOT NULL THEN 1 END) AS sealed "
        "FROM coupon_events e "
        "LEFT JOIN redeem_facts f ON f.event_id=e.id "
        "LEFT JOIN redeem_batch_items i ON i.event_id=e.id "
        "WHERE e.event_type='redeem' AND e.business_day=?",
        (business_day,),
    ).fetchone()
    return {
        "redeem_event_count": int(row["total"]),
        "unmaterialized_event_count": int(row["unmaterialized"]),
        "sealed_event_count": int(row["sealed"]),
    }


def mark_batched(conn: sqlite3.Connection, fact_ids: list[int], batch_id: int) -> None:
    for fid in fact_ids:
        conn.execute(
            "UPDATE redeem_facts SET status='sealed', batch_id=? WHERE id=?",
            (batch_id, fid),
        )


def day_is_sealed(conn: sqlite3.Connection, business_day: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM redeem_batches WHERE business_day=? AND status='sealed' LIMIT 1",
        (business_day,),
    ).fetchone()
    return row is not None
