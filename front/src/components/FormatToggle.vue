<script setup>
import { useSettings } from '@/stores/settings'

// 싱글/더블 전환 (사용률·순위·추천을 쓰는 페이지에만 둠). 모든 페이지가 같은 값을 씀
defineProps({ size: { type: String, default: 'md' } })
const settings = useSettings()
</script>

<template>
  <div class="fmt" :class="size">
    <button :class="{ on: settings.format === 'singles' }" @click="settings.format = 'singles'">싱글</button>
    <button :class="{ on: settings.format === 'doubles' }" @click="settings.format = 'doubles'">더블</button>
  </div>
</template>

<style scoped>
.fmt { display: flex; gap: 8px; background: var(--c-primary-soft); padding: 4px; border-radius: 8px; flex: none; }
.fmt button { border: 0; height: 36px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 600; background: transparent; color: var(--c-text-3); }
.fmt button.on { background: #fff; color: var(--c-text); }
.fmt.sm { gap: 4px; padding: 3px; }
.fmt.sm button { height: 30px; padding: 0 14px; font-size: 13px; }
</style>
