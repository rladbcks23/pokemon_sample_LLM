<script setup>
import { useRouter } from 'vue-router'

// 목록으로 돌아가기: 목록에서 들어왔으면 뒤로 가기(페이지·검색 그대로), 아니면 목록 첫 화면
const props = defineProps({
  to: { type: String, required: true },     // 목록 주소 (예: /pokemon)
  label: { type: String, default: '목록으로' },
})
const router = useRouter()
function back() {
  const prev = window.history.state?.back
  if (prev && prev.split('?')[0] === props.to) router.back()
  else router.push(props.to)
}
</script>

<template>
  <button class="back" @click="back">← {{ label }}</button>
</template>

<style scoped>
.back { height: 34px; padding: 0 14px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; font-size: 13px; color: var(--c-text); }
.back:hover { border-color: var(--c-primary); color: var(--c-primary); }
</style>
