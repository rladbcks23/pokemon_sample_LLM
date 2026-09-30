<script setup>
import { computed, ref, watch } from 'vue'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'

// 슬롯에 넣을 포켓몬 고르기 (현재 포맷 사용률 순). 이미 파티에 있는 포켓몬은 흐리게
const props = defineProps({
  open: Boolean,
  slot: { type: Number, default: 0 },
  list: { type: Array, default: () => [] },       // 포켓몬 목록 (api.pokemonList items)
  inParty: { type: Array, default: () => [] },    // 이미 들어간 포켓몬 id
  formatLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:open', 'pick'])
const q = ref('')
watch(() => props.open, (v) => { if (v) q.value = '' })

const rows = computed(() => {
  const k = q.value.trim().toLowerCase()
  return props.list
    .filter((p) => !k || p.name_ko.toLowerCase().includes(k) || p.name.toLowerCase().includes(k))
    .slice().sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999) || a.num - b.num)
})
function pick(p) {
  if (props.inParty.includes(p.id)) return
  emit('pick', p.id)
  emit('update:open', false)
}
</script>

<template>
  <el-dialog :model-value="open" width="760px" :show-close="false" align-center class="picker"
             @update:model-value="(v) => emit('update:open', v)">
    <template #header>
      <div class="head">
        <div><strong>슬롯 {{ slot + 1 }}에 포켓몬 추가</strong><span>{{ formatLabel }} 사용률 순 · 고르면 샘플 제작으로 이동합니다</span></div>
        <button class="x" @click="emit('update:open', false)">✕</button>
      </div>
    </template>
    <input v-model="q" class="search" placeholder="⌕ 포켓몬 검색 (한글/영문)">
    <div class="grid">
      <button v-for="p in rows" :key="p.id" class="pk" :class="{ dim: inParty.includes(p.id) }" @click="pick(p)">
        <span class="rk mono">{{ p.rank ? `${p.rank}위` : '순위 없음' }}</span>
        <PokemonImg :id="p.id" :size="64" />
        <strong>{{ p.name_ko }}</strong>
        <div class="types"><TypeBadge v-for="t in p.types" :key="t" :type="t" :width="48" /></div>
        <span v-if="inParty.includes(p.id)" class="in">이미 파티에 있음</span>
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
</style>
