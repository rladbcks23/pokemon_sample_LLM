<script setup>
import { computed } from 'vue'

// 페이지 번호: « ‹ 1 2 … 10 › »  (10개씩 묶어서 보여 줌: 1~10, 11~20 …)
const props = defineProps({
  page: { type: Number, required: true },
  pages: { type: Number, required: true },
})
const emit = defineEmits(['go'])
const BLOCK = 10

const buttons = computed(() => {
  const start = Math.floor((props.page - 1) / BLOCK) * BLOCK + 1
  const end = Math.min(props.pages, start + BLOCK - 1)
  return Array.from({ length: end - start + 1 }, (_, i) => start + i)
})
const go = (p) => { if (p >= 1 && p <= props.pages && p !== props.page) emit('go', p) }
</script>

<template>
  <div v-if="pages > 1" class="pager">
    <button class="mono" title="첫 페이지" :disabled="page === 1" @click="go(1)">«</button>
    <button class="mono" title="이전 페이지" :disabled="page === 1" @click="go(page - 1)">‹</button>
    <button v-for="p in buttons" :key="p" class="mono" :class="{ on: p === page }" @click="go(p)">{{ p }}</button>
    <button class="mono" title="다음 페이지" :disabled="page === pages" @click="go(page + 1)">›</button>
    <button class="mono" title="마지막 페이지" :disabled="page === pages" @click="go(pages)">»</button>
  </div>
</template>

<style scoped>
.pager { display: flex; justify-content: center; align-items: center; gap: 6px; }
.pager button { min-width: 36px; height: 36px; padding: 0 6px; border-radius: 6px; border: 1px solid var(--c-line); background: #fff; font-size: 13px; }
.pager button.on { border-color: var(--c-primary); background: var(--c-primary); color: #fbfbf9; }
.pager button:disabled:not(.on) { color: var(--c-faint); cursor: default; }
</style>
