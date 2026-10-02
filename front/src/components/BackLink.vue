<script setup>
import { useRouter } from 'vue-router'

// 돌아가기: 이 앱 안의 이전 화면이 있으면 그리로(스피드표·목록의 페이지·검색 그대로), 없으면(주소로 바로 들어옴) to로
const props = defineProps({
  to: { type: String, required: true },     // 이전 화면이 없을 때 갈 곳 (예: /pokemon)
  label: { type: String, default: '돌아가기' },
})
const router = useRouter()
function back() {
  if (window.history.state?.back) router.back()
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
