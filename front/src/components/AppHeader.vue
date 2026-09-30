<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSettings } from '@/stores/settings'

const settings = useSettings()
const route = useRoute()

const MENU = [
  { key: 'ranking', label: '랭킹', to: '/' },
  { key: 'pokemon', label: '포켓몬', to: '/pokemon' },
  { key: 'teams', label: '파티', to: '/teams' },
  { key: 'builder', label: '파티 빌딩', to: '/builder' },
  { key: 'sample', label: '샘플 제작', to: '/sample' },
  { key: 'mypage', label: '마이페이지', to: '/mypage' },
]
// 샘플 제작을 파티 빌딩 슬롯 편집으로 열었으면 "파티 빌딩"에 표시
const active = computed(() => (route.name === 'sample' && route.query.slot != null ? 'builder' : route.meta.nav))
</script>

<template>
  <header class="hd">
    <RouterLink to="/" class="logo"><span class="mark" /><strong>챔피언스 파티 빌더</strong></RouterLink>
    <nav class="nav">
      <RouterLink v-for="m in MENU" :key="m.key" :to="m.to" :class="{ on: active === m.key }">{{ m.label }}</RouterLink>
    </nav>
    <div class="right">
      <div class="reg"><span>레귤레이션</span><strong>{{ settings.rulesetLabel }}</strong><span>▾</span></div>
      <div class="seg">
        <button :class="{ on: settings.format === 'singles' }" @click="settings.format = 'singles'">싱글</button>
        <button :class="{ on: settings.format === 'doubles' }" @click="settings.format = 'doubles'">더블</button>
      </div>
    </div>
  </header>
</template>

<style scoped>
/* 스크롤해도 상단에 고정 (파티 빌딩의 채팅 패널이 이 아래에 붙음) */
.hd { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 40px; height: 64px; padding: 0 32px; border-bottom: 1px solid var(--c-line); background: #fff; }
.logo { display: flex; align-items: center; gap: 10px; }
.logo:hover { text-decoration: none; }
.mark { width: 26px; height: 26px; border: 1.5px solid var(--c-text); border-radius: 50%; }
.logo strong { font-size: 15px; }
.nav { display: flex; gap: 28px; font-size: 14px; align-self: stretch; }
.nav a { display: flex; align-items: center; color: var(--c-text-3); border-bottom: 2px solid transparent; }
.nav a:hover { color: var(--c-text); }
.nav a.on { border-bottom-color: var(--c-primary); color: var(--c-primary); font-weight: 600; }
.right { margin-left: auto; display: flex; gap: 12px; align-items: center; }
.reg { height: 34px; padding: 0 12px; border: 1px solid var(--c-line-strong); border-radius: 6px; display: flex; align-items: center; gap: 8px; font-size: 13px; }
.reg span:first-child { color: var(--c-muted); }
.seg { display: flex; border: 1px solid var(--c-primary); border-radius: 6px; overflow: hidden; }
.seg button { border: 0; padding: 0 14px; height: 32px; font-size: 13px; background: transparent; color: var(--c-text); }
.seg button.on { background: var(--c-primary); color: #fbfbf9; }
</style>
