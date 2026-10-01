<script setup>
import SpeedTable from '@/components/SpeedTable.vue'
</script>

<template>
  <section class="page">
    <div class="title"><h2>스피드표</h2><span>임시 표 · Lv50 스피드 실수치</span></div>
    <SpeedTable />
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 24px; }
.title { display: flex; align-items: baseline; gap: 12px; }
.title h2 { margin: 0; font-size: 28px; font-weight: 700; }
.title span { font-size: 14px; color: var(--c-muted); }
</style>
