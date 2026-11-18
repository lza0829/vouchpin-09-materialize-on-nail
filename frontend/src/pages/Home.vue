<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const d = ref(null)
const err = ref('')
async function load() {
  err.value = ''
  try { d.value = await api.dashboard() } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
<template>
  <div class="panel">
    <div class="grid" v-if="d">
      <div class="stat"><div class="k">业务日</div><div class="v">{{ d.business_day }}</div></div>
      <div class="stat"><div class="k">核销事件</div><div class="v">{{ d.redeem_event_count }}</div></div>
      <div class="stat"><div class="k">核销事实</div><div class="v">{{ d.fact_count }}</div></div>
      <div class="stat"><div class="k">未物化事件</div><div class="v ticket">{{ d.unmaterialized_event_count }}</div></div>
      <div class="stat"><div class="k">待钉扫描</div><div class="v ticket">{{ d.pending_scan_count }}</div></div>
      <div class="stat"><div class="k">待钉合计</div><div class="v ticket">{{ d.pending_scan_total }}</div></div>
      <div class="stat"><div class="k">已钉明细</div><div class="v">{{ d.sealed_item_count }}</div></div>
      <div class="stat"><div class="k">已钉合计</div><div class="v">{{ d.sealed_item_total }}</div></div>
      <div class="stat"><div class="k">今日核销额</div><div class="v ticket">{{ d.redeem_total_today }}</div></div>
      <div class="stat"><div class="k">日已钉扎</div><div class="v">{{ d.day_sealed ? '是' : '否' }}</div></div>
    </div>
    <p class="msg" v-if="!err">
      钉扎策略：<strong>{{ d?.policy_label }}</strong>。核销事件先入湖，钉扎时在同一事务内补物化事实并写入批次明细；
      未入批事件永不跳过，物化失败则整笔回滚。今日核销额 = 待钉合计 + 已钉明细合计。
    </p>
    <p class="msg err" v-if="err">{{ err }}</p>
  </div>
</template>
