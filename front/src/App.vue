<script setup>
import AppHeader from '@/components/AppHeader.vue'
</script>

<template>
  <div class="app">
    <AppHeader />
    <main>
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
/* 디자인 기준 데스크톱 1280px */
.app { max-width: 1280px; margin: 0 auto; min-height: 100vh; background: #fff; }
</style>
