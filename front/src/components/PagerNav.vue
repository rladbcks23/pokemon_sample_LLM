<script setup>
import { computed } from 'vue'

// 페이지 번호: ‹ 1 … 4 5 [6] 7 8 … 140 ›
const props = defineProps({
  page: { type: Number, required: true },
  pages: { type: Number, required: true },
})
const emit = defineEmits(['go'])

const buttons = computed(() => {
  const n = props.pages
  const p = props.page
  const set = new Set([1, n, p - 2, p - 1, p, p + 1, p + 2].filter((x) => x >= 1 && x <= n))
  const out = []
  let prev = 0
  for (const x of [...set].sort((a, b) => a - b)) {
    if (x - prev > 1) out.push('…')
    out.push(x)
    prev = x
  }
  return out
})
const go = (p) => { if (p >= 1 && p <= props.pages && p !== props.page) emit('go', p) }
</script>

<template>
  <div v-if="pages > 1" class="pager">
    <button class="mono" :disabled="page === 1" @click="go(page - 1)">‹</button>
    <button v-for="(p, i) in buttons" :key="i" class="mono" :class="{ on: p === page, gap: p === '…' }"
            :disabled="p === '…'" @click="go(p)">{{ p }}</button>
    <button class="mono" :disabled="page === pages" @click="go(page + 1)">›</button>
  </div>
</template>

<style scoped>
.pager { display: flex; justify-content: center; align-items: center; gap: 6px; }
.pager button { min-width: 36px; height: 36px; padding: 0 6px; border-radius: 6px; border: 1px solid var(--c-line); background: #fff; font-size: 13px; }
.pager button.on { border-color: var(--c-primary); background: var(--c-primary); color: #fbfbf9; }
.pager button:disabled:not(.on) { color: var(--c-faint); cursor: default; }
.pager button.gap { border-color: transparent; }
</style>
