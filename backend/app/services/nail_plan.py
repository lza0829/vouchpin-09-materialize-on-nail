"""The one nail plan shared by preview, seal and dashboard.

Policy (global, exclusive): materialize-on-nail.

A redeem event enters the lake with no fact.  The nail transaction scans every
redeem event of the business day that has no batch detail yet, materializes the
missing facts and writes both header and item details before marking facts
sealed.  Events already present in a batch detail are never part of the plan,
so re-nailing cannot double count.  A pre-existing open fact is reused after
checking it describes the same redemption; it is never materialized twice.

Nothing may materialize a fact outside the nail transaction, and every
materialized fact must appear as a batch item.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.policy import SEAL_POLICY, SEAL_POLICY_LABEL
from app.repositories import campaigns as camp_repo
from app.repositories import facts as fact_repo


def build_plan(conn: sqlite3.Connection, day: str) -> dict[str, Any]:
    events = fact_repo.unbatched_redeem_events(conn, day)
    campaigns = {str(c["code"]) for c in camp_repo.list_all(conn)}
    scan = fact_repo.event_scan_for_day(conn, day)
    sealed_items = fact_repo.sealed_events_for_day(conn, day)

    # coupon_code is unique across facts, so two redeem events for one coupon
    # can never become two facts, and an event whose coupon already carries a
    # fact (from another event or another day) can never be materialized.
    # Fail the whole nail instead of dropping one or writing a second fact.
    coupon_counts: dict[str, int] = {}
    for ev in events:
        key = str(ev["coupon_code"])
        coupon_counts[key] = coupon_counts.get(key, 0) + 1

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    need_fact_coupons = [str(ev["coupon_code"]) for ev in events if ev["fact_id"] is None]
    existing_by_coupon = fact_repo.facts_for_coupons(conn, need_fact_coupons)

    for ev in events:
        has_fact = ev["fact_id"] is not None
        amount = float(ev["amount"])
        coupon = str(ev["coupon_code"])
        reasons: list[str] = []
        if not has_fact:
            if amount <= 0:
                reasons.append("核销金额须大于 0")
            if str(ev["campaign_code"]) not in campaigns:
                reasons.append(f"活动 {ev['campaign_code']} 不存在")
            if coupon_counts[coupon] > 1:
                reasons.append(f"券码 {coupon} 存在多条核销事件，无法一对一物化")
            elif coupon in existing_by_coupon:
                reasons.append(
                    f"券码 {coupon} 已有事实 #{existing_by_coupon[coupon]['id']}，无法再物化"
                )
        else:
            # A reused fact must be open and unbatched; if it already belongs to
            # a batch, pulling it in here would double count those totals.
            if str(ev["fact_status"]) != "open" or ev["fact_batch_id"] is not None:
                reasons.append(
                    f"既有事实 #{ev['fact_id']} 已属于批次，明细缺失，请先修复"
                )
            # A reused open fact must describe the same redemption as its event,
            # or the batch detail (event side) and the fact would disagree.
            if float(ev["fact_amount"]) != amount:
                reasons.append("既有事实金额与事件金额不一致")
            if str(ev["fact_coupon_code"]) != coupon:
                reasons.append("既有事实券码与事件不一致")
            if str(ev["fact_campaign_code"]) != str(ev["campaign_code"]):
                reasons.append("既有事实活动与事件不一致")
            if str(ev["fact_business_day"]) != str(ev["business_day"]):
                reasons.append("既有事实业务日与事件不一致")
        row = {
            "event_id": int(ev["event_id"]),
            "fact_id": int(ev["fact_id"]) if has_fact else None,
            "coupon_code": ev["coupon_code"],
            "campaign_code": ev["campaign_code"],
            "amount": amount,
            "business_day": ev["business_day"],
            "occurred_at": ev["occurred_at"],
            "source": "existing_fact" if has_fact else "materialize_on_nail",
            "invalid_reasons": reasons,
        }
        rows.append(row)
        if reasons:
            errors.append(row)

    valid_rows = [r for r in rows if not r["invalid_reasons"]]
    materialize_rows = [r for r in valid_rows if r["fact_id"] is None]

    return {
        "business_day": day,
        "policy": SEAL_POLICY,
        "policy_label": SEAL_POLICY_LABEL,
        "rows": rows,
        "errors": errors,
        "valid_rows": valid_rows,
        "materialize_rows": materialize_rows,
        "scanned_count": len(rows),
        "pending_total": round(sum(float(r["amount"]) for r in valid_rows), 2),
        "existing_fact_count": len(valid_rows) - len(materialize_rows),
        "already_sealed": fact_repo.day_is_sealed(conn, day),
        "scan": scan,
        "sealed_item_count": len(sealed_items),
        "sealed_total": round(sum(float(i["amount"]) for i in sealed_items), 2),
    }
