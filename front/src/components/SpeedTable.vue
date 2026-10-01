<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { useSettings } from '@/stores/settings'
import { SP_MAX_PER_STAT, calcStats } from '@/utils/pokemon'
import PokemonImg from '@/components/PokemonImg.vue'
import FormatToggle from '@/components/FormatToggle.vue'

// 스피드표: Lv50 스피드 실수치 (최속·준속·무보정·최저 + 스카프). 메가 폼도 따로 한 줄
const settings = useSettings()
const router = useRouter()
const list = ref([])
const error = ref('')
const q = ref('')
const rankedOnly = ref(true)    // 사용률 순위에 있는 포켓몬만

watch(() => settings.format, async (fmt) => {
  error.value = ''
  try {
    list.value = (await api.pokemonList(fmt)).items
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true })

const spe = (base, sp, plus, minus) => calcStats({ spe: base }, { spe: sp }, plus, minus).spe
const COLS = [
  ['max', '최속', 'SP 32 · 성격↑'],
  ['semi', '준속', 'SP 32'],
  ['zero', '무보정', 'SP 0'],
  ['min', '최저', 'SP 0 · 성격↓'],
  ['scarf', '최속 스카프', '×1.5'],
]

const rows = computed(() => {
  const k = q.value.trim().toLowerCase()
  const out = []
  for (const p of list.value) {
    if (rankedOnly.value && !p.rank) continue
    for (const f of [p, ...(p.megas || [])]) {
      if (k && !f.name_ko.toLowerCase().includes(k) && !f.name.toLowerCase().includes(k)) continue
      const b = f.stats.spe
      const max = spe(b, SP_MAX_PER_STAT, 'spe', null)
      out.push({
        id: f.id, base: p.id, name_ko: f.name_ko, rank: p.rank, mega: f !== p, b,
        max, semi: spe(b, SP_MAX_PER_STAT), zero: spe(b, 0), min: spe(b, 0, null, 'spe'), scarf: Math.floor(max * 1.5),
      })
    }
  }
  return out.sort((a, b) => b.max - a.max || b.b - a.b || (a.rank ?? 9999) - (b.rank ?? 9999))
})
</script>

<template>
  <div class="speed">
    <div class="controls">
      <FormatToggle />
      <input v-model="q" class="search" placeholder="⌕ 포켓몬 검색 (한글/영문)">
      <button class="toggle" :class="{ on: rankedOnly }" @click="rankedOnly = !rankedOnly">사용률 순위권만</button>
      <span class="note">Lv50 기준 · 최속 순 · 메가 폼 포함</span>
    </div>
    <p v-if="error" class="empty err">{{ error }}</p>
    <div v-else class="table">
      <div class="thead">
        <span>포켓몬</span><span class="c">순위</span><span class="c">종족값</span>
        <span v-for="[k, label, sub] in COLS" :key="k" class="c">{{ label }}<small>{{ sub }}</small></span>
      </div>
      <div v-for="r in rows" :key="r.id" class="trow" @click="router.push(`/pokemon/${r.id}`)">
        <div class="who">
          <PokemonImg :id="r.id" :size="36" /><strong>{{ r.name_ko }}</strong>
          <span v-if="r.mega" class="mega mono">MEGA</span>
        </div>
        <span class="c mono muted">{{ r.rank ?? '—' }}</span>
        <span class="c mono muted">{{ r.b }}</span>
        <strong v-for="[k] in COLS" :key="k" class="c mono" :class="k">{{ r[k] }}</strong>
      </div>
      <p v-if="!rows.length && list.length" class="empty">조건에 맞는 포켓몬이 없습니다</p>
      <p v-else-if="!list.length" class="empty">불러오는 중…</p>
    </div>
  </div>
</template>

<style scoped>
.speed { display: flex; flex-direction: column; gap: 16px; }
.controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.search { width: 280px; height: 42px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 14px; font-size: 14px; }
.toggle { height: 42px; padding: 0 14px; border-radius: 6px; border: 1px solid var(--c-line-strong); background: #fff; font-size: 13px; }
.toggle.on { border-color: var(--c-primary); background: var(--c-primary); color: #fbfbf9; }
.note { margin-left: auto; font-size: 12px; color: var(--c-muted); }
.table { border: 1px solid var(--c-line); border-radius: 8px; overflow: hidden; }
.thead, .trow { display: grid; grid-template-columns: minmax(0, 1fr) 64px 72px repeat(5, 96px); gap: 8px; padding: 10px 24px; align-items: center; }
.thead { background: var(--c-head); font-size: 12px; color: var(--c-muted); }
.thead small { display: block; font-size: 10px; color: var(--c-faint); }
.trow { padding: 6px 24px; border-top: 1px solid var(--c-line-row); cursor: pointer; font-size: 14px; }
.trow:hover { background: var(--c-hover); }
.who { display: flex; align-items: center; gap: 10px; min-width: 0; }
.who strong { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mega { font-size: 10px; border: 1px solid var(--c-text); border-radius: 3px; padding: 1px 5px; }
.c { text-align: center; }
.muted { color: var(--c-muted); font-weight: 400; }
.max { color: var(--c-heart); }
.scarf { color: var(--c-primary); }
.empty { padding: 40px; text-align: center; color: var(--c-muted); font-size: 14px; border-top: 1px solid var(--c-line-row); margin: 0; }
.err { color: var(--c-danger); }
</style>
