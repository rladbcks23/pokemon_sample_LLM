<script setup>
import { computed, ref } from 'vue'
import { img } from '@/api'
import { TYPE_KO } from '@/utils/pokemon'

// 나무위키 스타일 타입 배지 (assets/types/*.png, 120×40 → 가로:세로 3:1)
const props = defineProps({
  type: { type: String, required: true },
  width: { type: Number, default: 60 },
})
const broken = ref(false)
const style = computed(() => ({ width: props.width + 'px', height: Math.round(props.width / 3) + 'px' }))
</script>

<template>
  <img v-if="!broken" class="tbadge" :src="img.type(type)" :alt="TYPE_KO[type]" :title="TYPE_KO[type]"
       :style="style" @error="broken = true">
  <span v-else class="tbadge fallback" :style="style">{{ TYPE_KO[type] || type }}</span>
</template>

<style scoped>
.tbadge { flex: none; display: inline-block; border-radius: 3px; }
.fallback {
  display: inline-flex; align-items: center; justify-content: center; font-size: 11px;
  border: 1px solid var(--c-line-strong); background: var(--c-chip);
}
</style>
