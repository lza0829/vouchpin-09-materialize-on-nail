<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const preview = ref(null)
const msg = ref('')
const err = ref('')
const busy = ref(false)

const blocked = computed(() => {
  const p = preview.value
  if (!p) return true
  return p.cannot_materialize_count > 0 || p.open_count === 0
})

async function load() {
  err.value = ''
  try { preview.value = await api.preview() } catch (e) { err.value = e.message }
}
async function seal() {
  if (busy.value) return
  busy.value = true
  msg.value = ''; err.value = ''
  try {
    const r = await api.seal({})
    msg.value =
      `已钉扎批次 #${r.batch_id} · ${r.fact_count} 笔 · 合计 ${r.total_amount}` +
      ` · 补物化 ${r.materialized_count} 笔（事件 ${r.materialized_event_ids.join(', ') || '无'}）` +
      (r.existing_fact_count ? ` · 复用既有事实 ${r.existing_fact_count} 笔` : '')
    await load()
  } catch (e) { err.value = e.message } finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <div class="panel" v-if="preview">
    <div class="grid">
      <div class="stat"><div class="k">业务日</div><div class="v">{{ preview.business_day }}</div></div>
      <div class="stat"><div class="k">待钉 redeem 事件</div><div class="v ticket">{{ preview.open_count }}</div></div>
      <div class="stat"><div class="k">待钉合计</div><div class="v ticket">{{ preview.open_total }}</div></div>
      <div class="stat"><div class="k">其中需补物化</div><div class="v ticket">{{ preview.materialize_count }}</div></div>
      <div class="stat"><div class="k">复用既有事实</div><div class="v">{{ preview.existing_fact_count }}</div></div>
      <div class="stat"><div class="k">已在其他批次</div><div class="v">{{ preview.previously_sealed_event_count }}</div></div>
    </div>
    <div class="grid">
      <div class="stat"><div class="k">核销事件总数</div><div class="v">{{ preview.redeem_event_count }}</div></div>
      <div class="stat"><div class="k">未物化事件</div><div class="v">{{ preview.unmaterialized_event_count }}</div></div>
      <div class="stat"><div class="k">无法物化</div><div class="v" :class="{ ticket: preview.cannot_materialize_count > 0 }">{{ preview.cannot_materialize_count }}</div></div>
      <div class="stat"><div class="k">已钉明细</div><div class="v">{{ preview.sealed_item_count }}</div></div>
      <div class="stat"><div class="k">已钉合计</div><div class="v ticket">{{ preview.sealed_total }}</div></div>
      <div class="stat"><div class="k">钉扎策略</div><div class="v policy">{{ preview.policy_label }}</div></div>
    </div>
    <div class="row">
      <button type="button" @click="seal" :disabled="busy || blocked">钉扎本日核销</button>
      <button type="button" class="ghost" @click="load">刷新预览</button>
    </div>
    <p class="msg" v-if="blocked && preview.cannot_materialize_count === 0 && !preview.already_sealed && preview.open_count === 0">本日没有待钉的 redeem 事件。</p>
    <p class="msg" v-if="preview.cannot_materialize_count > 0">
      有 {{ preview.cannot_materialize_count }} 条 redeem 事件无法物化，钉扎会整笔回滚。请先修正事件湖。
    </p>
    <p class="msg" v-if="msg">{{ msg }}</p>
    <p class="msg err" v-if="err">{{ err }}</p>
  </div>
  <div class="panel">
    <h2 class="sect">钉扎计划（与批次明细同源）</h2>
    <table>
      <thead>
        <tr><th>事件ID</th><th>事实ID</th><th>券码</th><th>活动</th><th>金额</th><th>来源</th><th>问题</th></tr>
      </thead>
      <tbody>
        <tr v-for="f in (preview?.facts || [])" :key="f.event_id">
          <td>{{ f.event_id }}</td>
          <td>{{ f.fact_id ?? '—' }}</td>
          <td>{{ f.coupon_code }}</td>
          <td>{{ f.campaign_code }}</td>
          <td>{{ f.amount }}</td>
          <td>
            <span class="tag" :class="f.source === 'existing_fact' ? 'ok' : 'warn'">
              {{ f.source === 'existing_fact' ? '既有 open 事实' : '钉扎时补物化' }}
            </span>
          </td>
          <td><span v-if="f.invalid_reasons.length" class="msg err">{{ f.invalid_reasons.join('；') }}</span></td>
        </tr>
        <tr v-if="!(preview?.facts || []).length"><td colspan="7" class="msg">无待钉事件。</td></tr>
      </tbody>
    </table>
  </div>
</template>
