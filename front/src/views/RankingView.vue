<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import { useSettings } from '@/stores/settings'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'
import RankChange from '@/components/RankChange.vue'
import FormatToggle from '@/components/FormatToggle.vue'

const settings = useSettings()
const data = ref(null)
const error = ref('')
const showAll = ref(false)
const FIRST = 50

watch(() => settings.format, async (fmt) => {
  data.value = null
  error.value = ''
  showAll.value = false
  try {
    data.value = await api.ranking(fmt)
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true })

const items = computed(() => data.value?.items || [])
const top3 = computed(() => items.value.slice(0, 3))
const rest = computed(() => items.value.slice(3, showAll.value ? undefined : FIRST))
// 순위는 OP.GG 갱신 때마다 저장한 스냅샷. 변동은 직전 스냅샷(보통 전날) 대비
const md = (iso) => { const d = new Date(iso); return `${d.getMonth() + 1}/${d.getDate()}` }
const hm = (iso) => new Date(iso).toTimeString().slice(0, 5)
const updated = computed(() => {
  const d = data.value
  if (!d?.captured_at) return ''
  const base = `${d.season.toUpperCase()} · ${md(d.captured_at)} ${hm(d.captured_at)} 갱신`
  return d.compared_to ? `${base} · ${md(d.compared_to)} 대비` : base
})
const prevText = (it) => {
  if (!data.value?.compared_to) return ''
  return it.prev_rank ? `${md(data.value.compared_to)} ${it.prev_rank}위` : '신규 진입'
}
</script>

<template>
  <section class="page">
    <div class="bar">
      <FormatToggle />
      <span v-if="updated" class="pill mono">{{ updated }}</span>
    </div>

    <p v-if="error" class="msg err">{{ error }}</p>
    <p v-else-if="!data" class="msg">불러오는 중…</p>
    <p v-else-if="!items.length" class="msg">사용률 데이터가 없습니다</p>

    <template v-else>
      <div class="top3">
        <RouterLink v-for="it in top3" :key="it.pokemon.id" :to="`/pokemon/${it.pokemon.id}`" class="card">
          <div class="rank-line">
            <span class="rank mono">{{ it.rank }}</span>
            <RankChange :change="it.change" :is-new="it.is_new" class="delta" />
          </div>
          <PokemonImg :id="it.pokemon.id" :size="128" class="big" />
          <div class="name-line">
            <strong>{{ it.pokemon.name_ko }}</strong>
            <span class="prev mono">{{ prevText(it) }}</span>
          </div>
          <div class="types"><TypeBadge v-for="t in it.pokemon.types" :key="t" :type="t" :width="72" /></div>
        </RouterLink>
      </div>

      <div class="rest">
        <RouterLink v-for="it in rest" :key="it.pokemon.id" :to="`/pokemon/${it.pokemon.id}`" class="row">
          <div class="rrank"><span class="mono">{{ it.rank }}</span><RankChange :change="it.change" :is-new="it.is_new" /></div>
          <PokemonImg :id="it.pokemon.id" :size="44" />
          <div class="rname">
            <strong>{{ it.pokemon.name_ko }}</strong>
            <div class="types"><TypeBadge v-for="t in it.pokemon.types" :key="t" :type="t" :width="48" /></div>
          </div>
          <span class="rprev mono">{{ prevText(it) }}</span>
        </RouterLink>
      </div>
      <button v-if="items.length > FIRST" class="more" @click="showAll = !showAll">
        {{ showAll ? '접기 ▴' : `전체 ${items.length}마리 보기 ▾` }}
      </button>
    </template>
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 28px; }
.bar { display: flex; align-items: center; justify-content: space-between; }
.pill { font-size: 12px; color: var(--c-muted); border: 1px solid var(--c-line); border-radius: 12px; padding: 5px 12px; }
.msg { color: var(--c-muted); font-size: 14px; }
.err { color: var(--c-danger); }

.top3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.card { border: 1px solid var(--c-line-card); border-radius: 12px; padding: 24px; background: #fff; display: flex; flex-direction: column; gap: 14px; }
.card:hover { border-color: var(--c-text); text-decoration: none; }
.rank-line { display: flex; align-items: baseline; gap: 10px; }
.rank { font-size: 44px; font-weight: 700; line-height: 1; }
.delta { font-size: 18px; }
.big { align-self: center; }
.name-line { display: flex; align-items: center; justify-content: space-between; }
.name-line strong { font-size: 18px; }
.prev { font-size: 13px; color: var(--c-muted); }
.types { display: flex; gap: 6px; }

.rest { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 20px; }
.row { display: flex; align-items: center; gap: 14px; padding: 10px 14px; border: 1px solid var(--c-line-soft); border-radius: 8px; background: #fff; }
.row:hover { border-color: var(--c-text); text-decoration: none; }
.rrank { display: flex; align-items: baseline; gap: 6px; width: 60px; flex: none; }
.rrank .mono { font-size: 18px; font-weight: 700; line-height: 1; }
.rrank :deep(.rc) { font-size: 12px; }
.rname { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.rname strong { font-size: 14px; }
.rname .types { gap: 4px; }
.rprev { margin-left: auto; font-size: 12px; color: var(--c-muted); }
.more { align-self: center; height: 36px; padding: 0 18px; border: 1px solid var(--c-line); border-radius: 6px; background: #fff; font-size: 13px; color: var(--c-primary); }
.more:hover { border-color: var(--c-primary); }
</style>
