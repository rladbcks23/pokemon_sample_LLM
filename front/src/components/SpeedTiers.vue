<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import PokemonImg from '@/components/PokemonImg.vue'

// 스피드 라인: 같은 스피드 실수치끼리 묶어 빠른 순으로 (싱글·더블 픽률 상위 포켓몬, 실제로 쓰는 투자·보정만)
const router = useRouter()
const TOPS = [[50, '50위까지'], [100, '100위까지'], [300, '전체']]   // 300 = 순위에 있는 포켓몬 전부
const top = ref(50)
const data = ref(null)
const error = ref('')
const q = ref('')

watch(top, async (n) => {
  data.value = null
  error.value = ''
  try {
    data.value = await api.speed(n)
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true })

// 검색하면 그 포켓몬이 있는 줄만
const rows = computed(() => {
  const k = q.value.trim()
  const all = data.value?.rows || []
  if (!k) return all
  return all.map((r) => ({ ...r, entries: r.entries.filter((e) => e.pokemon.name_ko.includes(k)) }))
    .filter((r) => r.entries.length)
})
</script>

<template>
  <div class="tiers">
    <div class="controls">
      <div class="seg">
        <span>픽률</span>
        <button v-for="[n, label] in TOPS" :key="n" :class="{ on: top === n }" @click="top = n">{{ label }}</button>
      </div>
      <input v-model="q" class="search" placeholder="⌕ 포켓몬 검색">
    </div>

    <div class="legend">
      <span><b>무보정</b> 종족값 + 20</span>
      <span><b>최저속</b> 무보정 × 0.9</span>
      <span><b>준속</b> 무보정 + 32</span>
      <span><b>최속</b> 준속 × 1.1</span>
      <span><b>스카프·1랭크업</b> × 1.5</span>
      <span><b>2랭크업·쓱쓱 등</b> × 2</span>
      <small>Lv50 · 싱글·더블 사용률에서 실제로 쓰는 투자·도구·특성·기술만</small>
    </div>

    <p v-if="error" class="msg err">{{ error }}</p>
    <p v-else-if="!data" class="msg">불러오는 중…</p>
    <p v-else-if="!rows.length" class="msg">{{ q ? '검색 결과가 없습니다' : '사용률 데이터가 없습니다' }}</p>
    <div v-else class="list">
      <div class="lhead mono"><span>순위</span><span>스피드</span><span>포켓몬 · 투자/보정</span></div>
      <div v-for="(r, i) in rows" :key="r.speed" class="row">
        <span class="no mono">{{ i + 1 }}</span>
        <strong class="spd mono">{{ r.speed }}</strong>
        <div class="ents">
          <div v-for="(e, i) in r.entries" :key="i" class="ent" :title="`${e.pokemon.name_ko} · 픽률 ${e.rank}위`"
               @click="router.push(`/pokemon/${e.pokemon.id}`)">
            <PokemonImg :id="e.pokemon.id" :size="44" />
            <div class="txt"><span class="nm">{{ e.pokemon.name_ko }}</span><span class="lb">{{ e.label }}</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tiers { display: flex; flex-direction: column; gap: 16px; }
.controls { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.seg { display: flex; align-items: center; gap: 6px; }
.seg span { font-size: 12px; color: var(--c-muted); margin-right: 4px; }
.seg button { height: 32px; padding: 0 12px; border-radius: 16px; border: 1px solid var(--c-line-strong); background: #fff; font-size: 12px; }
.seg button.on { border-color: var(--c-primary); background: var(--c-primary-soft); color: var(--c-primary); }
.search { margin-left: auto; width: 240px; height: 38px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 12px; font-size: 13px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: baseline; padding: 12px 16px; border-radius: 8px; background: var(--c-head); font-size: 13px; color: var(--c-text-3); }
.legend b { color: #c98a00; margin-right: 4px; }
.legend small { margin-left: auto; font-size: 11px; color: var(--c-muted); }
.msg { color: var(--c-muted); }
.err { color: var(--c-danger); }
/* 랭킹처럼 한 줄씩: 순위 · 스피드 · 그 스피드의 포켓몬들(가로로) */
.list { border: 1px solid var(--c-line); border-radius: 8px; overflow: hidden; background: #fff; }
.lhead, .row { display: grid; grid-template-columns: 56px 88px minmax(0, 1fr); gap: 12px; align-items: center; padding: 8px 20px; }
.lhead { background: var(--c-head); font-size: 12px; color: var(--c-muted); }
.row { border-top: 1px solid var(--c-line-row); }
.no { font-size: 14px; color: var(--c-muted); }
.spd { font-size: 24px; font-weight: 800; }
.ents { display: flex; flex-wrap: wrap; gap: 4px 6px; }
.ent { display: flex; align-items: center; gap: 6px; padding: 2px 10px 2px 2px; cursor: pointer; border-radius: 8px; border: 1px solid var(--c-line-faint); }
.ent:hover { background: var(--c-hover); border-color: var(--c-primary); }
.txt { display: flex; flex-direction: column; min-width: 0; }
.nm { font-size: 11px; color: var(--c-muted); }
.lb { font-size: 13px; font-weight: 600; }
</style>
