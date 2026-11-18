from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        sys.modules.pop(mod)
    from fastapi.testclient import TestClient

    main = importlib.import_module("app.main")
    return TestClient(main.app)


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "clipbond.db")
    conn.row_factory = sqlite3.Row
    return conn


def _day(client) -> str:
    return client.get("/api/settings/day").json()["business_day"]


def test_ingest_writes_no_facts(client, tmp_path):
    day = _day(client)
    assert client.get("/api/facts").json() == []
    r = client.post(
        "/api/events",
        json={"event_type": "redeem", "coupon_code": "C-7777", "campaign_code": "TEA5"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fact_id"] is None
    facts = client.get("/api/facts", params={"business_day": day}).json()
    assert all(f["event_id"] != body["event_id"] for f in facts)
    conn = _db(tmp_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM redeem_facts WHERE event_id=?", (body["event_id"],)
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_seal_materializes_scanned_events_into_batch_items(client, tmp_path):
    day = _day(client)
    preview = client.get("/api/redeem/preview").json()
    assert preview["materialize_count"] == preview["open_count"] == 2
    assert preview["existing_fact_count"] == 0

    r = client.post("/api/redeem/seal", json={})
    assert r.status_code == 200, r.text
    seal = r.json()
    assert seal["materialized_count"] == 2
    assert sorted(seal["materialized_event_ids"]) == sorted(
        f["event_id"] for f in preview["facts"]
    )

    detail = client.get(f"/api/batches/{seal['batch_id']}").json()
    assert len(detail["items"]) == seal["fact_count"] == 2
    assert round(sum(i["amount"] for i in detail["items"]), 2) == seal["total_amount"]
    assert all(i["source"] == "materialize_on_nail" for i in detail["items"])

    conn = _db(tmp_path)
    try:
        # one fact per event, every fact sealed into the batch
        assert conn.execute(
            "SELECT event_id, COUNT(*) c FROM redeem_facts GROUP BY event_id HAVING c>1"
        ).fetchall() == []
        assert conn.execute(
            "SELECT COUNT(*) FROM redeem_facts WHERE status!='sealed' OR batch_id IS NULL"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM redeem_facts").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM redeem_facts f LEFT JOIN redeem_batch_items i ON i.fact_id=f.id WHERE i.id IS NULL").fetchone()[0] == 0
    finally:
        conn.close()

    dash = client.get("/api/dashboard").json()
    assert dash["day_sealed"] is True
    assert dash["fact_count"] == dash["sealed_item_count"] == 2
    assert dash["redeem_total_today"] == dash["sealed_item_total"] == seal["total_amount"]
    assert dash["unmaterialized_event_count"] == 0


def test_repin_after_stragglers_does_not_double_count(client, tmp_path):
    day = _day(client)
    first = client.post("/api/redeem/seal", json={})
    assert first.status_code == 200, first.text

    conn = _db(tmp_path)
    try:
        # straggler A: event with an open fact already materialized elsewhere
        cur = conn.execute(
            "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) "
            "VALUES('redeem','C-3001','TEA5',5,?,'2026-01-01T00:00:00')",
            (day,),
        )
        ev_a = cur.lastrowid
        conn.execute(
            "INSERT INTO redeem_facts(coupon_code, campaign_code, amount, business_day, event_id, status) "
            "VALUES('C-3001','TEA5',5,?,?,'open')",
            (day, ev_a),
        )
        # straggler B: event only, no fact yet
        cur = conn.execute(
            "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) "
            "VALUES('redeem','C-3002','TEA5',5,?,'2026-01-01T00:00:00')",
            (day,),
        )
        ev_b = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    preview = client.get("/api/redeem/preview").json()
    assert preview["open_count"] == 2
    assert preview["existing_fact_count"] == 1
    assert preview["materialize_count"] == 1

    second = client.post("/api/redeem/seal", json={})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["materialized_event_ids"] == [ev_b]
    assert body["existing_fact_count"] == 1
    assert body["fact_count"] == 2

    detail = client.get(f"/api/batches/{body['batch_id']}").json()
    assert sorted(i["source"] for i in detail["items"]) == ["existing_fact", "materialize_on_nail"]
    assert sorted(i["event_id"] for i in detail["items"]) == sorted([ev_a, ev_b])

    conn = _db(tmp_path)
    try:
        # no event appears twice in facts or batch items
        assert conn.execute(
            "SELECT event_id, COUNT(*) c FROM redeem_facts GROUP BY event_id HAVING c>1"
        ).fetchall() == []
        assert conn.execute(
            "SELECT event_id, COUNT(*) c FROM redeem_batch_items GROUP BY event_id HAVING c>1"
        ).fetchall() == []
        assert conn.execute("SELECT SUM(amount) FROM redeem_facts").fetchone()[0] == pytest.approx(40.0)
        assert conn.execute("SELECT SUM(amount) FROM redeem_batch_items").fetchone()[0] == pytest.approx(40.0)
        assert conn.execute("SELECT SUM(total_amount) FROM redeem_batches").fetchone()[0] == pytest.approx(40.0)
    finally:
        conn.close()

    dash = client.get("/api/dashboard").json()
    assert dash["redeem_total_today"] == pytest.approx(40.0)
    assert dash["sealed_item_total"] == pytest.approx(40.0)
    assert dash["fact_count"] == dash["sealed_item_count"] == 4

    # nothing left to nail: the whole day is accounted for, not silently redone
    assert client.post("/api/redeem/seal", json={}).status_code == 409


def test_unmaterializable_event_rolls_back_entire_seal(client, tmp_path):
    day = _day(client)
    conn = _db(tmp_path)
    try:
        conn.execute(
            "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) "
            "VALUES('redeem','BAD-1','NOPE',0,?,'2026-01-01T00:00:00')",
            (day,),
        )
        conn.commit()
    finally:
        conn.close()

    preview = client.get("/api/redeem/preview").json()
    assert preview["cannot_materialize_count"] == 1

    r = client.post("/api/redeem/seal", json={})
    assert r.status_code == 409
    assert "整笔回滚" in r.json()["detail"]

    conn = _db(tmp_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM redeem_batches").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM redeem_facts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM redeem_batch_items").fetchone()[0] == 0
    finally:
        conn.close()


def test_duplicate_coupon_redeems_cannot_be_materialized(client, tmp_path):
    day = _day(client)
    conn = _db(tmp_path)
    try:
        conn.execute(
            "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) "
            "VALUES('redeem','C-1001','NEW10',10,?,'2026-01-01T00:10:00')",
            (day,),
        )
        conn.commit()
    finally:
        conn.close()

    preview = client.get("/api/redeem/preview").json()
    assert preview["cannot_materialize_count"] >= 1
    r = client.post("/api/redeem/seal", json={})
    assert r.status_code == 409

    conn = _db(tmp_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM redeem_facts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM redeem_batch_items").fetchone()[0] == 0
    finally:
        conn.close()


def test_late_redeem_event_nails_into_followup_batch(client):
    first = client.post("/api/redeem/seal", json={})
    assert first.status_code == 200, first.text
    first_body = first.json()

    late = client.post(
        "/api/events",
        json={"event_type": "redeem", "coupon_code": "C-9999", "campaign_code": "TEA5"},
    )
    assert late.status_code == 200, late.text
    late_body = late.json()
    assert late_body["fact_id"] is None
    assert late_body["day_already_sealed"] is True

    preview = client.get("/api/redeem/preview").json()
    assert preview["open_count"] == 1
    assert preview["materialize_count"] == 1
    assert preview["previously_sealed_event_count"] == first_body["fact_count"]

    second = client.post("/api/redeem/seal", json={})
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["materialized_event_ids"] == [late_body["event_id"]]
    assert second_body["previously_sealed_event_count"] == first_body["fact_count"]

    first_detail = client.get(f"/api/batches/{first_body['batch_id']}").json()
    second_detail = client.get(f"/api/batches/{second_body['batch_id']}").json()
    assert len(first_detail["items"]) == first_body["fact_count"]
    assert [i["event_id"] for i in second_detail["items"]] == [late_body["event_id"]]

    dash = client.get("/api/dashboard").json()
    assert dash["fact_count"] == dash["sealed_item_count"] == first_body["fact_count"] + 1
    assert dash["redeem_total_today"] == dash["sealed_item_total"]
    assert dash["unmaterialized_event_count"] == 0

    # duplicate coupons are rejected at ingest, before they can ever reach a nail
    dup = client.post(
        "/api/events",
        json={"event_type": "redeem", "coupon_code": "C-1001", "campaign_code": "NEW10"},
    )
    assert dup.status_code == 409


def test_coupon_with_fact_from_another_day_blocks_seal(client, tmp_path):
    """A legacy redeem event whose coupon already has a sealed fact cannot be
    materialized one-to-one; the nail must fail loudly, not write a second fact."""
    day = _day(client)
    conn = _db(tmp_path)
    try:
        conn.execute(
            "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) "
            "VALUES('redeem','C-OLD','TEA5',5,'2026-01-04','2026-01-04T10:00:00')"
        )
        conn.execute(
            "INSERT INTO redeem_batches(business_day,status,fact_count,total_amount,sealed_at) "
            "VALUES('2026-01-04','sealed',1,5,'2026-01-04T23:00:00')"
        )
        conn.execute(
            "INSERT INTO redeem_facts(coupon_code,campaign_code,amount,business_day,event_id,batch_id,status) "
            "VALUES('C-OLD','TEA5',5,'2026-01-04',1,1,'sealed')"
        )
        cur = conn.execute(
            "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) "
            "VALUES('redeem','C-OLD','TEA5',5,?,'2026-01-05T10:00:00')",
            (day,),
        )
        conn.commit()
        new_event = cur.lastrowid
    finally:
        conn.close()

    preview = client.get("/api/redeem/preview").json()
    blocked = {r["event_id"]: r for r in preview["facts"]}
    assert "已有事实" in "".join(blocked[new_event]["invalid_reasons"])

    assert client.post("/api/redeem/seal", json={}).status_code == 409
    conn = _db(tmp_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM redeem_facts WHERE business_day=?", (day,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM redeem_batch_items WHERE business_day=?", (day,)
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_open_fact_must_match_event(client, tmp_path):
    """Reusing an open fact is only safe when it describes the same redemption."""
    day = _day(client)
    conn = _db(tmp_path)
    try:
        cur = conn.execute(
            "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) "
            "VALUES('redeem','C-5555','TEA5',5,?,'2026-01-02T10:00:00')",
            (day,),
        )
        eid = cur.lastrowid
        conn.execute(
            "INSERT INTO redeem_facts(coupon_code, campaign_code, amount, business_day, event_id, status) "
            "VALUES('C-5555','TEA5',7,?,?,'open')",
            (day, eid),
        )
        conn.commit()
    finally:
        conn.close()

    preview = client.get("/api/redeem/preview").json()
    by_event = {r["event_id"]: r for r in preview["facts"]}
    assert "金额与事件金额不一致" in "".join(by_event[eid]["invalid_reasons"])
    assert client.post("/api/redeem/seal", json={}).status_code == 409


def test_legacy_database_migrates_batch_items_and_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db = tmp_path / "clipbond.db"
    conn = sqlite3.connect(db)
    # legacy schema: UNIQUE coupon_code, no policy columns, sealed fact w/o detail
    conn.executescript(
        """
        CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE campaigns(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL, face_value REAL NOT NULL, min_spend REAL NOT NULL DEFAULT 0);
        CREATE TABLE coupon_events(id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
          coupon_code TEXT NOT NULL, campaign_code TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0,
          business_day TEXT NOT NULL, occurred_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE redeem_facts(id INTEGER PRIMARY KEY AUTOINCREMENT, coupon_code TEXT NOT NULL UNIQUE,
          campaign_code TEXT NOT NULL, amount REAL NOT NULL, business_day TEXT NOT NULL,
          event_id INTEGER NOT NULL, batch_id INTEGER, status TEXT NOT NULL DEFAULT 'open');
        CREATE TABLE redeem_batches(id INTEGER PRIMARY KEY AUTOINCREMENT, business_day TEXT NOT NULL,
          status TEXT NOT NULL, fact_count INTEGER NOT NULL DEFAULT 0,
          total_amount REAL NOT NULL DEFAULT 0, sealed_at TEXT, note TEXT NOT NULL DEFAULT '');
        INSERT INTO campaigns(code,title,face_value,min_spend) VALUES('NEW10','新人立减10',10,30);
        INSERT INTO coupon_events(event_type,coupon_code,campaign_code,amount,business_day,occurred_at)
          VALUES('redeem','C-OLD','NEW10',10,'2026-01-05','2026-01-05T10:00:00');
        INSERT INTO redeem_batches(business_day,status,fact_count,total_amount,sealed_at)
          VALUES('2026-01-05','sealed',1,10,'2026-01-05T23:00:00');
        INSERT INTO redeem_facts(coupon_code,campaign_code,amount,business_day,event_id,batch_id,status)
          VALUES('C-OLD','NEW10',10,'2026-01-05',1,1,'sealed');
        """
    )
    conn.commit()
    conn.close()

    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        sys.modules.pop(mod)
    app_db = importlib.import_module("app.db")
    app_db.init_db()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(redeem_batches)")}
        assert {"policy", "event_scan_count", "materialized_count"} <= cols
        items = conn.execute("SELECT * FROM redeem_batch_items").fetchall()
        assert len(items) == 1
        assert items[0]["fact_id"] == 1 and items[0]["batch_id"] == 1
        assert items[0]["source"] == "existing_fact"
        # one fact per event still enforced
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO redeem_facts(coupon_code,campaign_code,amount,business_day,event_id,status) "
                "VALUES('C-NEW','NEW10',10,'2026-01-05',1,'open')"
            )
        conn.rollback()
    finally:
        conn.close()
