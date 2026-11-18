<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const rows = ref([])
const detail = ref(null)
const err = ref('')

async function load() {
  err.value = ''
  try { rows.value = await api.batches() } catch (e) { err.value = e.message }
}
async function open(id) {
  err.value = ''
  try { detail.value = await api.batch(id) } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
<template>
  <div class="panel">
    <p class="msg err" v-if="err">{{ err }}</p>
    <table>
      <thead>
        <tr>
          <th>批次</th><th>业务日</th><th>状态</th><th>笔数</th><th>合计</th>
          <th>扫描事件</th><th>补物化</th><th>钉扎时刻</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="b in rows" :key="b.id">
          <td>{{ b.id }}</td>
          <td>{{ b.business_day }}</td>
          <td><span class="tag ok">{{ b.status }}</span></td>
          <td>{{ b.fact_count }}</td>
          <td>{{ b.total_amount }}</td>
          <td>{{ b.event_scan_count }}</td>
          <td>{{ b.materialized_count }}</td>
          <td>{{ b.sealed_at }}</td>
          <td><button type="button" class="ghost" @click="open(b.id)">明细</button></td>
        </tr>
        <tr v-if="!rows.length"><td colspan="9" class="msg">暂无批次。</td></tr>
      </tbody>
    </table>
  </div>
  <div class="panel" v-if="detail">
    <h2 class="sect">批次 #{{ detail.batch.id }} 明细（{{ detail.batch.policy }}）</h2>
    <p class="msg">
      批头 笔数 {{ detail.batch.fact_count }} / 合计 {{ detail.batch.total_amount }}；
      明细 {{ detail.items.length }} 行 / 合计
      {{ detail.items.reduce((s, i) => s + Number(i.amount), 0).toFixed(2) }}
    </p>
    <table>
      <thead><tr><th>事实ID</th><th>事件ID</th><th>券码</th><th>活动</th><th>金额</th><th>来源</th></tr></thead>
      <tbody>
        <tr v-for="i in detail.items" :key="i.id">
          <td>{{ i.fact_id }}</td>
          <td>{{ i.event_id }}</td>
          <td>{{ i.coupon_code }}</td>
          <td>{{ i.campaign_code }}</td>
          <td>{{ i.amount }}</td>
          <td><span class="tag" :class="i.source === 'existing_fact' ? 'ok' : 'warn'">{{ i.source }}</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
