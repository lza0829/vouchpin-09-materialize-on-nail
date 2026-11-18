from __future__ import annotations
from datetime import datetime
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo
from app.repositories import events as event_repo
from app.repositories import facts as fact_repo
from app.repositories import campaigns as camp_repo


def list_campaigns() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return camp_repo.list_all(conn)
    finally:
        conn.close()


def list_events(business_day: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        return event_repo.list_events(conn, day)
    finally:
        conn.close()


def add_event(body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        day = body.get("business_day") or settings_repo.get(conn, "business_day")
        et = body.get("event_type")
        if et not in {"issue", "redeem", "void"}:
            raise HTTPException(400, "event_type 须为 issue/redeem/void")
        code = (body.get("coupon_code") or "").strip()
        camp = (body.get("campaign_code") or "").strip()
        if not code or not camp:
            raise HTTPException(400, "coupon_code / campaign_code 必填")
        amount = float(body.get("amount") or 0)
        if et == "redeem" and amount <= 0:
            # default face value from campaign
            camps = {c["code"]: c for c in camp_repo.list_all(conn)}
            if camp in camps:
                amount = float(camps[camp]["face_value"])
        if et == "redeem":
            dup = conn.execute(
                "SELECT id FROM coupon_events WHERE event_type='redeem' AND coupon_code=? LIMIT 1",
                (code,),
            ).fetchone()
            if dup:
                raise HTTPException(409, f"券码 {code} 已有核销事件 #{dup['id']}")
        occurred = body.get("occurred_at") or datetime.now().replace(microsecond=0).isoformat()
        eid = event_repo.insert_event(
            conn,
            event_type=et,
            coupon_code=code,
            campaign_code=camp,
            amount=amount,
            business_day=day,
            occurred_at=occurred,
            note=body.get("note") or "",
        )
        # Nail policy: redeem events are only recorded in the lake.  The fact
        # is derived inside the seal transaction, never on ingest.  Late events
        # on an already-sealed day are allowed and picked up by the next nail
        # as a follow-up batch, without touching the sealed batch's details.
        conn.commit()
        return {
            "event_id": eid,
            "fact_id": None,
            "business_day": day,
            "policy": "materialize_on_nail",
            "day_already_sealed": fact_repo.day_is_sealed(conn, day),
        }
    finally:
        conn.close()
