<script setup>
import { computed, ref, watch } from 'vue'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'

// 슬롯에 넣을 포켓몬 고르기 (현재 포맷 사용률 순). 이미 파티에 있는 포켓몬은 흐리게
// "내 샘플" 탭: 만든 샘플·찜한 샘플을 바로 슬롯에 넣음
const props = defineProps({
  open: Boolean,
  slot: { type: Number, default: 0 },
  list: { type: Array, default: () => [] },       // 포켓몬 목록 (api.pokemonList items)
  inParty: { type: Array, default: () => [] },    // 이미 들어간 포켓몬 id
  formatLabel: { type: String, default: '' },
  samples: { type: Array, default: () => [] },    // [{ sample, member }] (member: MemberCard 모양)
})
const emit = defineEmits(['update:open', 'pick', 'pick-sample'])
const q = ref('')
const tab = ref('pokemon')
watch(() => props.open, (v) => { if (v) { q.value = ''; tab.value = 'pokemon' } })

const sampleRows = computed(() => {
  const k = q.value.trim().toLowerCase()
  return props.samples.filter(({ member }) => !k || member.pokemon.name_ko.toLowerCase().includes(k))
})
function pickSample(x) {
  if (props.inParty.includes(x.sample.pokemon)) return
  emit('pick-sample', x.sample)
  emit('update:open', false)
}

const rows = computed(() => {
  const k = q.value.trim().toLowerCase()
  // 메가 폼은 기본 폼 바로 뒤에 (랭킹 순위 없음). 고르면 기본 폼 + 메가스톤
  return props.list.slice().sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999) || a.num - b.num)
    .flatMap((p) => [p, ...(p.megas || []).map((m) => ({ ...m, mega: true, base: p.id }))])
    .filter((p) => !k || p.name_ko.toLowerCase().includes(k) || p.name.toLowerCase().includes(k))
})
const baseOf = (p) => (p.mega ? p.base : p.id)
function pick(p) {
  if (props.inParty.includes(baseOf(p))) return
  emit('pick', p.mega ? { pokemon: p.base, item: p.item } : { pokemon: p.id })
  emit('update:open', false)
}
</script>

<template>
  <el-dialog :model-value="open" width="760px" :show-close="false" align-center class="picker"
             @update:model-value="(v) => emit('update:open', v)">
    <template #header>
      <div class="head">
        <div><strong>슬롯 {{ slot + 1 }}에 포켓몬 추가</strong>
          <span v-if="tab === 'pokemon'">{{ formatLabel }} 사용률 순 · 고르면 샘플 제작으로 이동합니다</span>
          <span v-else>내가 만든 샘플·찜한 샘플 · 고르면 바로 슬롯에 들어갑니다</span></div>
        <button class="x" @click="emit('update:open', false)">✕</button>
      </div>
    </template>
    <div class="tabs">
      <button :class="{ on: tab === 'pokemon' }" @click="tab = 'pokemon'">포켓몬</button>
      <button :class="{ on: tab === 'sample' }" @click="tab = 'sample'">내 샘플<span class="mono">{{ samples.length }}</span></button>
    </div>
    <input v-model="q" class="search" placeholder="⌕ 포켓몬 검색 (한글/영문)">
    <div v-if="tab === 'sample'" class="sgrid">
      <button v-for="(x, i) in sampleRows" :key="i" class="sk" :class="{ dim: inParty.includes(x.sample.pokemon) }" @click="pickSample(x)">
        <PokemonImg :id="x.member.pokemon.id" :size="48" />
        <div class="si">
          <div class="sn"><strong>{{ x.member.pokemon.name_ko }}</strong><span v-if="x.member.is_mega" class="mega mono">MEGA</span></div>
          <span>{{ x.member.item?.name_ko || '도구 없음' }} · {{ x.member.nature?.name_ko || '성격 —' }}</span>
          <span class="mv">{{ x.member.moves.filter(Boolean).map((m) => m.name_ko).join(' / ') || '기술 없음' }}</span>
        </div>
        <span v-if="inParty.includes(x.sample.pokemon)" class="in">이미 파티에 있음</span>
      </button>
      <p v-if="!sampleRows.length" class="none">{{ samples.length ? '검색 결과가 없습니다' : '저장한 샘플이 없습니다. 샘플 제작에서 저장하면 여기에 나옵니다.' }}</p>
    </div>
    <div v-else class="grid">
      <button v-for="p in rows" :key="p.id" class="pk" :class="{ dim: inParty.includes(baseOf(p)) }" @click="pick(p)">
        <span class="rk mono">{{ p.mega ? 'MEGA' : p.rank ? `${p.rank}위` : '순위 없음' }}</span>
        <PokemonImg :id="p.id" :size="64" />
        <strong>{{ p.name_ko }}</strong>
        <div class="types"><TypeBadge v-for="t in p.types" :key="t" :type="t" :width="48" /></div>
        <span v-if="inParty.includes(baseOf(p))" class="in">이미 파티에 있음</span>
      </button>
    </div>
  </el-dialog>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; }
.head div { display: flex; flex-direction: column; gap: 2px; }
.head strong { font-size: 18px; }
.head span { font-size: 12px; color: var(--c-muted); }
.x { margin-left: auto; width: 32px; height: 32px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; }
.search { width: 100%; height: 42px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 14px; font-size: 14px; margin-bottom: 14px; }
.grid { max-height: 560px; overflow: auto; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.pk { border: 1px solid var(--c-line); border-radius: 10px; background: #fff; padding: 12px; display: flex; flex-direction: column; align-items: center; gap: 6px; color: var(--c-text); }
.pk:hover { border-color: var(--c-primary); background: var(--c-hover); }
.pk.dim { opacity: .45; cursor: default; }
.rk { align-self: flex-start; font-size: 11px; color: var(--c-muted); }
.pk strong { font-size: 13px; }
.types { display: flex; gap: 4px; }
.in { font-size: 10px; color: var(--c-danger); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--c-line); margin-bottom: 14px; }
.tabs button { border: 0; background: none; padding: 8px 14px; font-size: 14px; color: var(--c-text-3); border-bottom: 2px solid transparent; margin-bottom: -1px; display: flex; gap: 6px; align-items: baseline; }
.tabs button.on { font-weight: 600; color: var(--c-primary); border-bottom-color: var(--c-primary); }
.tabs .mono { font-size: 12px; color: var(--c-faint); }
.sgrid { max-height: 560px; overflow: auto; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.sk { border: 1px solid var(--c-line); border-radius: 10px; background: #fff; padding: 12px; display: flex; align-items: center; gap: 12px; text-align: left; color: var(--c-text); }
.sk:hover { border-color: var(--c-primary); background: var(--c-hover); }
.sk.dim { opacity: .45; cursor: default; }
.si { display: flex; flex-direction: column; gap: 3px; min-width: 0; font-size: 12px; color: var(--c-text-3); }
.sn { display: flex; align-items: center; gap: 6px; }
.sn strong { font-size: 14px; color: var(--c-text); }
.mega { font-size: 10px; border: 1px solid var(--c-text); border-radius: 3px; padding: 1px 5px; color: var(--c-text); }
.mv { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.none { grid-column: 1 / -1; text-align: center; color: var(--c-muted); font-size: 13px; padding: 32px; margin: 0; }
</style>
