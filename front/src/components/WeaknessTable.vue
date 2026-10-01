<script setup>
import { computed } from 'vue'
import { TYPES, TYPE_KO, mulText } from '@/utils/pokemon'

// 파티 약점표: 18타입 × 멤버, (showSum이면) 맨 아래 타입별 약점(×2 이상) 마리 수
// rows: [{ name, cells: { Fire: 2, ... } }]
const props = defineProps({
  rows: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false },
  showSum: { type: Boolean, default: true },   // 맨 아래 "약점 수" 줄
})

const cellStyle = (m) => ({
  4: { background: 'var(--c-x4)', color: '#fbfbf9' },
  2: { background: 'var(--c-x2)' },
  0.5: { background: 'var(--c-half)' },
  0.25: { background: 'var(--c-half)' },
  0: { background: 'var(--c-zero)' },
}[m] || {})
const sums = computed(() => TYPES.map((t) => props.rows.filter((r) => r.cells[t] > 1).length))
const sumStyle = (c) => (c >= 3 ? { background: 'var(--c-x4)', color: '#fbfbf9' } : c === 2 ? { background: 'var(--c-x2)' } : {})
</script>

<template>
  <div class="wt" :class="{ compact }">
    <span />
    <span v-for="t in TYPES" :key="t" class="th">{{ TYPE_KO[t] }}</span>
    <template v-for="(r, i) in rows" :key="i">
      <span class="name">{{ r.name }}</span>
      <span v-for="t in TYPES" :key="t" class="cell mono" :style="cellStyle(r.cells[t])">{{ mulText(r.cells[t]) }}</span>
    </template>
    <template v-if="showSum">
      <span class="name sum">약점 수</span>
      <span v-for="(c, i) in sums" :key="i" class="cell mono sum" :style="sumStyle(c)">{{ c || '' }}</span>
    </template>
  </div>
</template>

<style scoped>
.wt { display: grid; grid-template-columns: 96px repeat(18, minmax(0, 1fr)); font-size: 11px; border: 1px solid var(--c-line-soft); border-radius: 6px; overflow: hidden; }
.wt.compact { grid-template-columns: 80px repeat(18, minmax(0, 1fr)); font-size: 10px; border-radius: 0; }
.th { text-align: center; padding: 6px 0; color: var(--c-text-3); border-left: 1px solid var(--c-line-faint); white-space: nowrap; overflow: hidden; }
.name { padding: 6px 8px; border-top: 1px solid var(--c-line-faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.compact .name { font-size: 11px; }
.cell { text-align: center; padding: 6px 0; border-top: 1px solid var(--c-line-faint); border-left: 1px solid var(--c-line-faint); }
.sum { font-weight: 600; border-top-color: #9a978f; }
</style>
