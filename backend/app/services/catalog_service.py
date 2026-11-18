from __future__ import annotations
from typing import Any
from app.db import connect
from app.policy import SEAL_POLICY, SEAL_POLICY_LABEL
from app.repositories import settings as settings_repo
from app.repositories import facts as fact_repo
from app.repositories import batches as batch_repo
from app.repositories import events as event_repo
from app.services.nail_plan import build_plan


def dashboard() -> dict[str, Any]:
    """Overview numbers use the same nail plan as preview & seal."""
    conn = connect()
    try:
        day = settings_repo.get(conn, "business_day")
        plan = build_plan(conn, day)
        facts = fact_repo.list_facts(conn, day)
        open_n = sum(1 for f in facts if f["status"] == "open")
        sealed_n = sum(1 for f in facts if f["status"] == "sealed")
        events = event_repo.list_events(conn, day)
        batches = batch_repo.list_batches(conn)
        pending_total = round(sum(float(r["amount"]) for r in plan["rows"]), 2)
        return {
            "business_day": day,
            "policy": SEAL_POLICY,
            "policy_label": SEAL_POLICY_LABEL,
            "event_count": len(events),
            "redeem_event_count": plan["scan"]["redeem_event_count"],
            "fact_count": len(facts),
            "open_fact_count": open_n,
            "sealed_fact_count": sealed_n,
            "unmaterialized_event_count": plan["scan"]["unmaterialized_event_count"],
            "pending_scan_count": len(plan["rows"]),
            "pending_scan_total": pending_total,
            "materialize_needed_count": len(plan["materialize_rows"]),
            "existing_fact_count": plan["existing_fact_count"],
            "cannot_materialize_count": len(plan["errors"]),
            "sealed_item_count": plan["sealed_item_count"],
            "sealed_item_total": plan["sealed_total"],
            "redeem_total_today": round(sum(float(i["amount"]) for i in plan["rows"]) + plan["sealed_total"], 2),
            "fact_total": round(sum(float(f["amount"]) for f in facts), 2),
            "batch_count": len(batches),
            "day_sealed": plan["already_sealed"],
        }
    finally:
        conn.close()
