<script setup>
import SpeedTiers from '@/components/SpeedTiers.vue'
</script>

<template>
  <section class="page">
    <div class="title"><h2>스피드표</h2><span>Lv50 스피드 실수치 · 빠른 순</span></div>
    <SpeedTiers />
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 20px; }
.title { display: flex; align-items: baseline; gap: 12px; }
.title h2 { margin: 0; font-size: 28px; font-weight: 700; }
.title span { font-size: 14px; color: var(--c-muted); }
</style>
