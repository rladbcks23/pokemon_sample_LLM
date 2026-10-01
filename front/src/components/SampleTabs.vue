<script setup>
import { useRoute } from 'vue-router'

// 샘플 탭 위의 구분: 포켓몬 샘플(/samples) / 파티 샘플(/teams)
const route = useRoute()
</script>

<template>
  <div class="stabs">
    <RouterLink to="/samples" :class="{ on: route.name === 'samples' }">포켓몬 샘플</RouterLink>
    <RouterLink to="/teams" :class="{ on: route.name === 'teams' }">파티 샘플</RouterLink>
  </div>
</template>

<style scoped>
.stabs { display: flex; gap: 4px; border-bottom: 1px solid var(--c-line); }
.stabs a { padding: 10px 16px; font-size: 15px; color: var(--c-text-3); border-bottom: 2px solid transparent; margin-bottom: -1px; }
.stabs a:hover { text-decoration: none; color: var(--c-text); }
.stabs a.on { font-weight: 700; color: var(--c-primary); border-bottom-color: var(--c-primary); }
</style>
