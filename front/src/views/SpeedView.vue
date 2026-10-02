<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SpeedTiers from '@/components/SpeedTiers.vue'
import SpeedTable from '@/components/SpeedTable.vue'

// 스피드 라인(값끼리 묶은 표) / 전체 계산표
const route = useRoute()
const router = useRouter()
const tab = computed(() => (route.query.tab === 'table' ? 'table' : 'tiers'))
const setTab = (t) => router.replace({ query: t === 'tiers' ? {} : { tab: t } })
</script>

<template>
  <section class="page">
    <div class="title"><h2>스피드표</h2><span>Lv50 스피드 실수치</span></div>
    <div class="tabs">
      <button :class="{ on: tab === 'tiers' }" @click="setTab('tiers')">스피드 라인</button>
      <button :class="{ on: tab === 'table' }" @click="setTab('table')">전체 계산표</button>
    </div>
    <SpeedTiers v-if="tab === 'tiers'" />
    <SpeedTable v-else />
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 20px; }
.title { display: flex; align-items: baseline; gap: 12px; }
.title h2 { margin: 0; font-size: 28px; font-weight: 700; }
.title span { font-size: 14px; color: var(--c-muted); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--c-line); }
.tabs button { border: 0; background: none; padding: 10px 16px; font-size: 14px; color: var(--c-text-3); border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tabs button.on { font-weight: 600; color: var(--c-primary); border-bottom-color: var(--c-primary); }
</style>
