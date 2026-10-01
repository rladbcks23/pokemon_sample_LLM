<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { useSettings } from '@/stores/settings'
import { STATS, TYPES, TYPE_KO } from '@/utils/pokemon'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'
import RankChange from '@/components/RankChange.vue'
import PagerNav from '@/components/PagerNav.vue'

const settings = useSettings()
const router = useRouter()
const list = ref([])
const loading = ref(true)
const error = ref('')

const q = ref('')
const megaOnly = ref(false)
const types = ref([])
const sort = ref('use')
// 스피드 순은 따로 만들 스피드 표에서
const SORTS = [['use', '사용률'], ['total', '종족값 합계']]
const PAGE_SIZE = 30
const page = ref(1)

watch(() => settings.format, async (fmt) => {
  loading.value = true
  error.value = ''
  try {
    list.value = (await api.pokemonList(fmt)).items
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}, { immediate: true })

const byRank = (a, b) => (a.rank ?? 9999) - (b.rank ?? 9999) || a.num - b.num
const SORT_FN = {
  use: byRank,
  total: (a, b) => b.bst - a.bst || byRank(a, b),
}

const rows = computed(() => {
  const k = q.value.trim().toLowerCase()
  return list.value
    .filter((p) => !k || p.name_ko.toLowerCase().includes(k) || p.name.toLowerCase().includes(k) || p.id.includes(k))
    .filter((p) => !megaOnly.value || p.has_mega)
    .filter((p) => !types.value.length || p.types.some((t) => types.value.includes(t)))
    .sort(SORT_FN[sort.value])
})

const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / PAGE_SIZE)))
const pageRows = computed(() => rows.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
// 검색·필터·정렬·포맷이 바뀌면 1페이지로
watch([q, megaOnly, types, sort, () => settings.format], () => { page.value = 1 })
function goPage(p) {
  page.value = p
  window.scrollTo({ top: 0 })
}

function toggleType(t) {
  types.value = types.value.includes(t) ? types.value.filter((x) => x !== t) : [...types.value, t]
}
const statClass = (s, v) => ({ hi: v >= 120 })
</script>

<template>
  <section class="page">
    <div class="title"><h2>포켓몬</h2><span>{{ rows.length }}마리 · {{ settings.rulesetLabel }} 기준</span></div>

    <div class="controls">
      <input v-model="q" class="search" placeholder="⌕ 이름 검색 (한글/영문)">
      <button class="toggle" :class="{ on: megaOnly }" @click="megaOnly = !megaOnly">메가 가능만</button>
      <div class="sort">
        <span>정렬</span>
        <div class="seg">
          <button v-for="[k, label] in SORTS" :key="k" :class="{ on: sort === k }" @click="sort = k">{{ label }}</button>
        </div>
      </div>
    </div>

    <div class="chips">
      <span class="lbl">타입</span>
      <button v-for="t in TYPES" :key="t" :class="{ on: types.includes(t) }" @click="toggleType(t)">{{ TYPE_KO[t] }}</button>
      <button v-if="types.length" class="clear" @click="types = []">초기화</button>
    </div>

    <div class="table">
      <div class="thead mono">
        <span>순위</span><span>포켓몬</span><span>타입</span>
        <span>H</span><span>A</span><span>B</span><span>C</span><span>D</span><span>S</span>
        <span>합계</span><span class="r">변동</span>
      </div>
      <p v-if="loading" class="empty">불러오는 중…</p>
      <p v-else-if="error" class="empty err">{{ error }}</p>
      <template v-else>
        <div v-for="p in pageRows" :key="p.id" class="trow" @click="router.push(`/pokemon/${p.id}`)">
          <span class="rank mono">{{ p.rank ?? '—' }}</span>
          <div class="who">
            <PokemonImg :id="p.id" :size="44" />
            <strong>{{ p.name_ko }}</strong>
            <span v-if="p.has_mega" class="mega mono">MEGA</span>
          </div>
          <div class="types"><TypeBadge v-for="t in p.types" :key="t" :type="t" :width="60" /></div>
          <span v-for="s in STATS" :key="s" class="stat mono" :class="statClass(s, p.stats[s])">{{ p.stats[s] }}</span>
          <strong class="mono">{{ p.bst }}</strong>
          <span class="r"><RankChange v-if="p.rank" :change="p.change" :is-new="p.change === null" /></span>
        </div>
        <p v-if="!rows.length" class="empty">조건에 맞는 포켓몬이 없습니다</p>
      </template>
    </div>
    <PagerNav :page="page" :pages="pages" @go="goPage" />
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 24px; }
.title { display: flex; align-items: baseline; gap: 12px; }
.title h2 { margin: 0; font-size: 28px; font-weight: 700; }
.title span { font-size: 14px; color: var(--c-muted); }

.controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.search { width: 320px; height: 42px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 14px; font-size: 14px; }
.toggle { height: 42px; padding: 0 14px; border-radius: 6px; border: 1px solid var(--c-line-strong); background: #fff; font-size: 13px; }
.toggle.on { border-color: var(--c-primary); background: var(--c-primary); color: #fbfbf9; }
.sort { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.sort > span { font-size: 12px; color: var(--c-muted); }
.seg { display: flex; border: 1px solid var(--c-line-strong); border-radius: 6px; overflow: hidden; }
.seg button { border: 0; height: 40px; padding: 0 14px; font-size: 13px; background: #fff; }
.seg button.on { background: var(--c-primary); color: #fbfbf9; }

.chips { display: flex; flex-wrap: nowrap; gap: 4px; align-items: center; }
.chips .lbl { font-size: 12px; color: var(--c-muted); margin-right: 6px; white-space: nowrap; flex: none; }
.chips button { height: 30px; flex: 1 1 0; min-width: 0; padding: 0; white-space: nowrap; border-radius: 4px; border: 1px solid var(--c-line); background: #fff; font-size: 12px; }
.chips button.on { border-color: var(--c-primary); background: var(--c-primary); color: #fbfbf9; }
.chips .clear { flex: none; border: 0; background: none; font-size: 12px; color: var(--c-primary); text-decoration: underline; padding: 0 4px; }

.table { border: 1px solid var(--c-line); border-radius: 8px; overflow: hidden; }
.thead, .trow { display: grid; grid-template-columns: 72px minmax(0, 1fr) 140px repeat(6, 48px) 56px 72px; gap: 12px; padding: 12px 24px; align-items: center; }
.thead { background: var(--c-head); font-size: 12px; color: var(--c-muted); }
.trow { padding: 10px 24px; border-top: 1px solid var(--c-line-row); cursor: pointer; font-size: 13px; }
.trow:hover { background: var(--c-hover); }
.rank { font-size: 15px; font-weight: 700; }
.who { display: flex; align-items: center; gap: 12px; min-width: 0; }
.who strong { font-size: 14px; }
.mega { font-size: 10px; border: 1px solid var(--c-text); border-radius: 3px; padding: 1px 5px; }
.types { display: flex; gap: 4px; }
.stat { color: var(--c-muted); }
.stat.hi { color: var(--c-text); font-weight: 600; }
.r { text-align: right; }
.empty { padding: 40px; text-align: center; color: var(--c-muted); font-size: 14px; border-top: 1px solid var(--c-line-row); margin: 0; }
.err { color: var(--c-danger); }
</style>
