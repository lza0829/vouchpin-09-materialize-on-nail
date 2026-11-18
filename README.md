# Vouchpin（券钉簿）

券事件入湖 → 核销事实钉扎 → 批次互证。

## 钉瞬间物化策略（全局唯一）

本项目只贯彻 **「钉时补物化」**（`materialize_on_nail`，见 `backend/app/policy.py`），
不提供任何批外物化入口。

- 核销事件写入事件湖时**不物化事实**（`fact_id` 恒为 `null`）。
- 钉扎事务（`BEGIN IMMEDIATE`）扫描该业务日**所有还没有批次明细的 redeem 事件**（批次明细即账本），在同一事务内补物化事实，写批头 + 批次明细，再将事实标为 `sealed`。
- 已经进入某条批次明细的事件**不在扫描范围内**，因此重钉不会与已 `sealed` 明细双计；
  若事件已有 `open` 事实，则复用该事实（校验金额/券码/活动/业务日一致）而不重复物化。
- 任一事件无法物化（金额 ≤ 0、活动不存在、同一券码多条核销事件）则整笔钉扎回滚：
  没有 sealed 批、没有半截事实、没有半截明细。
- 数据库唯一索引 `ux_redeem_facts_event(event_id)` 保证一个 redeem 事件至多一行事实；
  `ux_redeem_batch_items_event(event_id)` 保证一个事件至多进入一条明细。
- 预览、钉扎、总览、批次明细全部走同一个 `build_plan()`（`backend/app/services/nail_plan.py`），
  计数同源。

批头快照：

| 字段 | 含义 |
| --- | --- |
| `policy` | 固定 `materialize_on_nail` |
| `event_scan_count` | 钉扎时该业务日 redeem 事件总数 |
| `materialized_count` / `materialized_event_ids` | 本批补物化的事件 |

没有「跳过」快照，因为该策略从不跳过：任何无法物化的事件都会让整笔钉扎失败回滚。

## 本地运行

- API: `cd backend && python -m uvicorn app.main:app --port 10800`
- Web: `cd frontend && npm install && npm run dev`（5800）
- 测试: `cd backend && python -m pytest tests -q`

## 验证双计

```bash
cd backend && python -m pytest tests/test_nail_policy.py -q
```

覆盖：只写事件不物化 → 钉扎；补物化/补事件后重钉；无法物化整笔回滚；同券码多事件拒绝；
旧库迁移后批次明细补齐。断言事实数 = 明细数 = 已钉事件数，金额一致。
