<script setup>
import { computed } from 'vue'

// 직전 시즌 대비 순위 변동: ▲3 / ▼1 / – / NEW
const props = defineProps({
  change: { type: Number, default: null },
  isNew: { type: Boolean, default: false },
})
const view = computed(() => {
  if (props.isNew || props.change === null) return { text: 'NEW', cls: 'new' }
  if (props.change > 0) return { text: `▲${props.change}`, cls: 'up' }
  if (props.change < 0) return { text: `▼${-props.change}`, cls: 'down' }
  return { text: '–', cls: 'same' }
})
</script>

<template>
  <span class="rc mono" :class="view.cls">{{ view.text }}</span>
</template>

<style scoped>
.rc { font-weight: 600; line-height: 1; }
.up { color: var(--c-ok); }
.down { color: var(--c-danger); }
.same { color: var(--c-faint); }
.new { color: var(--c-primary); font-size: .8em; }
</style>
