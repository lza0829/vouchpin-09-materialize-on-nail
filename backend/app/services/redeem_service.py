from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.policy import SEAL_POLICY
from app.repositories import batches as batch_repo
from app.repositories import facts as fact_repo
from app.repositories import settings as settings_repo
from app.services.nail_plan import build_plan


def _normalize_batch(batch: dict[str, Any]) -> dict[str, Any]:
    out = dict(batch)
    raw = out.get("materialized_event_ids")
    if isinstance(raw, str):
        try:
            out["materialized_event_ids"] = json.loads(raw)
        except ValueError:
            out["materialized_event_ids"] = []
    return out


def list_facts(business_day: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        return fact_repo.list_facts(conn, day)
    finally:
        conn.close()


def preview(business_day: str | None = None) -> dict[str, Any]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        plan = build_plan(conn, day)
        return {
            "business_day": day,
            "policy": plan["policy"],
            "policy_label": plan["policy_label"],
            "already_sealed": plan["already_sealed"],
            "open_count": len(plan["valid_rows"]),
            "open_total": plan["pending_total"],
            "scanned_count": plan["scanned_count"],
            "materialize_count": len(plan["materialize_rows"]),
            "existing_fact_count": plan["existing_fact_count"],
            "redeem_event_count": plan["scan"]["redeem_event_count"],
            "previously_sealed_event_count": plan["scan"]["sealed_event_count"],
            "unmaterialized_event_count": plan["scan"]["unmaterialized_event_count"],
            "cannot_materialize_count": len(plan["errors"]),
            # All-or-nothing: an unmaterializable event aborts the nail, so
            # nothing is ever silently skipped.
            "blocked_event_ids": [int(r["event_id"]) for r in plan["errors"]],
            "sealed_item_count": plan["sealed_item_count"],
            "sealed_total": plan["sealed_total"],
            "facts": plan["rows"],
        }
    finally:
        conn.close()


def seal(body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        day = body.get("business_day") or settings_repo.get(conn, "business_day")
        plan = build_plan(conn, day)
        if plan["errors"]:
            detail = "; ".join(
                f"事件 #{r['event_id']}: {'，'.join(r['invalid_reasons'])}"
                for r in plan["errors"]
            )
            raise HTTPException(409, f"钉扎失败，整笔回滚，未写入批次或事实: {detail}")
        if not plan["valid_rows"]:
            if plan["already_sealed"]:
                raise HTTPException(409, f"业务日 {day} 已钉扎，且无未入批的 redeem 事件")
            raise HTTPException(400, "无可钉扎的 redeem 事件")

        rows = plan["valid_rows"]
        materialized_ids = [int(r["event_id"]) for r in plan["materialize_rows"]]
        bid = batch_repo.create_batch(
            conn,
            business_day=day,
            status="sealed",
            fact_count=len(rows),
            total_amount=plan["pending_total"],
            sealed_at=datetime.now().replace(microsecond=0).isoformat(),
            note=body.get("note") or "",
            policy=SEAL_POLICY,
            event_scan_count=plan["scan"]["redeem_event_count"],
            materialized_count=len(materialized_ids),
            materialized_event_ids=json.dumps(materialized_ids),
        )

        fact_ids: list[int] = []
        for r in rows:
            fact_id = r["fact_id"]
            if fact_id is None:
                try:
                    fact_id = fact_repo.insert_fact(
                        conn,
                        coupon_code=r["coupon_code"],
                        campaign_code=r["campaign_code"],
                        amount=r["amount"],
                        business_day=day,
                        event_id=r["event_id"],
                        status="open",
                    )
                except sqlite3.IntegrityError as exc:
                    raise HTTPException(
                        409, f"事件 #{r['event_id']} 物化失败，整笔回滚: {exc}"
                    ) from exc
            batch_repo.insert_item(
                conn,
                batch_id=bid,
                fact_id=fact_id,
                event_id=r["event_id"],
                coupon_code=r["coupon_code"],
                campaign_code=r["campaign_code"],
                amount=r["amount"],
                business_day=day,
                source=r["source"],
            )
            fact_ids.append(int(fact_id))

        fact_repo.mark_batched(conn, fact_ids, bid)
        conn.commit()
        return {
            "batch_id": bid,
            "business_day": day,
            "policy": SEAL_POLICY,
            "status": "sealed",
            "fact_count": len(rows),
            "total_amount": plan["pending_total"],
            "event_scan_count": plan["scan"]["redeem_event_count"],
            "materialized_count": len(materialized_ids),
            "materialized_event_ids": materialized_ids,
            "existing_fact_count": plan["existing_fact_count"],
            "previously_sealed_event_count": plan["scan"]["sealed_event_count"],
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_batches() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [_normalize_batch(b) for b in batch_repo.list_batches(conn)]
    finally:
        conn.close()


def batch_detail(batch_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if batch is None:
            raise HTTPException(404, "批次不存在")
        return {
            "batch": _normalize_batch(batch),
            "items": batch_repo.list_items(conn, batch_id),
        }
    finally:
        conn.close()
