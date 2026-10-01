<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import TeamCard from '@/components/TeamCard.vue'
import PagerNav from '@/components/PagerNav.vue'

const route = useRoute()
const router = useRouter()

// 필터·페이지는 주소(쿼리)에 둠 → 상세에서 뒤로 와도 유지
const fmt = computed(() => route.query.format || '')
const src = computed(() => route.query.source || '')
const page = computed(() => Number(route.query.page) || 1)
const q = ref(route.query.q || '')

const data = ref(null)
const error = ref('')
const PAGE_SIZE = 10    // back TeamPagination.page_size와 같음

const FORMATS = [['', '전체'], ['singles', '싱글'], ['doubles', '더블']]
const SOURCES = [['', '전체'], ['opgg_replica', 'OP.GG 레플리카'], ['showdown_replay', '리플레이']]

function setQuery(patch) {
  const next = { ...route.query, ...patch }
  if (!('page' in patch)) delete next.page      // 필터가 바뀌면 1페이지로
  Object.keys(next).forEach((k) => (next[k] === '' || next[k] == null) && delete next[k])
  router.replace({ query: next })
}

let timer
watch(q, (v) => {
  clearTimeout(timer)
  timer = setTimeout(() => setQuery({ q: v.trim() }), 300)
})

watch(() => route.query, async () => {
  if (route.name !== 'teams') return
  error.value = ''
  try {
    data.value = await api.teams({ format: fmt.value, source: src.value, q: route.query.q, page: page.value })
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true, deep: true })

const pages = computed(() => Math.max(1, Math.ceil((data.value?.count || 0) / PAGE_SIZE)))
</script>

<template>
  <section class="page">
    <div class="title"><h2>파티</h2><span v-if="data">{{ data.count.toLocaleString() }}개</span></div>

    <div class="controls">
      <div class="seg">
        <button v-for="[k, label] in FORMATS" :key="k" :class="{ on: fmt === k }" @click="setQuery({ format: k })">{{ label }}</button>
      </div>
      <div class="srcs">
        <span>출처</span>
        <button v-for="[k, label] in SOURCES" :key="k" :class="{ on: src === k }" @click="setQuery({ source: k })">{{ label }}</button>
      </div>
      <input v-model="q" class="search" placeholder="⌕ 포함 포켓몬 (예: 망나뇽)">
    </div>

    <p v-if="error" class="empty err">{{ error }}</p>
    <p v-else-if="!data" class="muted">불러오는 중…</p>
    <template v-else>
      <div v-if="data.results.length" class="grid">
        <TeamCard v-for="t in data.results" :key="t.id" :team="t" @click="router.push(`/teams/${t.id}`)" />
      </div>
      <div v-else class="empty">조건에 맞는 파티가 없습니다</div>

      <PagerNav :page="page" :pages="pages" @go="(p) => setQuery({ page: p })" />
    </template>
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 24px; }
.title { display: flex; align-items: baseline; gap: 12px; }
.title h2 { margin: 0; font-size: 28px; font-weight: 700; }
.title span { font-size: 14px; color: var(--c-muted); }
.muted { color: var(--c-muted); }
.controls { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.seg { display: flex; border: 1px solid var(--c-primary); border-radius: 6px; overflow: hidden; }
.seg button { border: 0; height: 38px; padding: 0 16px; font-size: 13px; background: #fff; color: var(--c-primary); }
.seg button.on { background: var(--c-primary); color: #fbfbf9; }
.srcs { display: flex; gap: 6px; align-items: center; }
.srcs span { font-size: 12px; color: var(--c-muted); margin-right: 4px; }
.srcs button { height: 32px; padding: 0 12px; border-radius: 16px; border: 1px solid var(--c-line-strong); background: #fff; font-size: 12px; }
.srcs button.on { border-color: var(--c-primary); background: var(--c-primary-soft); color: var(--c-primary); }
.search { margin-left: auto; width: 280px; height: 38px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 12px; font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.empty { padding: 48px; text-align: center; color: var(--c-muted); font-size: 14px; border: 1.5px dashed var(--c-line-strong); border-radius: 12px; margin: 0; }
.err { color: var(--c-danger); }
</style>
