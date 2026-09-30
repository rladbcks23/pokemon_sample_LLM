<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useBuilder } from '@/stores/builder'
import { useLibrary } from '@/stores/library'
import PokemonImg from '@/components/PokemonImg.vue'

// 샘플 하나를 파티에 추가: 1. 파티 선택 → 2. 가득 찼다면 뺄 포켓몬 선택
const props = defineProps({
  open: Boolean,
  sample: { type: Object, default: null },   // { pokemon, item, ... }
  label: { type: String, default: '' },      // 표시 이름 (예: 한카리아스)
  names: { type: Object, default: () => ({}) }, // pokemon id → 한글 이름
})
const emit = defineEmits(['update:open', 'done'])

const builder = useBuilder()
const library = useLibrary()
const router = useRouter()
const target = ref('builder')
const out = ref(null)

watch(() => props.open, (v) => { if (v) { target.value = 'builder'; out.value = null } })

const parties = computed(() => [
  { id: 'builder', name: '파티 빌딩 (편집 중)', sub: '파티 빌딩', slots: builder.slots },
  ...library.myTeams.map((t) => ({ id: t.id, name: t.name, sub: '내가 만든 파티', slots: t.slots })),
])
const current = computed(() => parties.value.find((p) => p.id === target.value))
const full = computed(() => current.value && current.value.slots.filter(Boolean).length >= 6)
const canAdd = computed(() => !full.value || out.value !== null)
const nameOf = (s) => (s ? props.names[s.pokemon] || s.pokemon : '빈 칸')
const summary = computed(() => {
  if (!full.value) return `빈 칸에 ${props.label}이(가) 들어갑니다`
  if (out.value === null) return '뺄 포켓몬을 선택하세요'
  return `${nameOf(current.value.slots[out.value])} → ${props.label}(으)로 교체`
})

function pick(id) {
  if (target.value !== id) { target.value = id; out.value = null }
}
function pickOut(p, i) {
  if (p.id === target.value && full.value && p.slots[i]) out.value = i
}
function close() { emit('update:open', false) }

function confirm() {
  if (!canAdd.value || !props.sample) return
  const p = current.value
  const i = full.value ? out.value : p.slots.findIndex((s) => !s)
  const sample = JSON.parse(JSON.stringify(props.sample))
  if (p.id === 'builder') {
    builder.setSlot(i, sample)
    close()
    router.push('/builder')
    return
  }
  const t = library.myTeams.find((x) => x.id === p.id)
  const slots = [...t.slots]
  slots[i] = sample
  library.saveTeam({ ...t, slots })
  close()
  emit('done', `${t.name}에 추가했습니다`)
}
</script>

<template>
  <el-dialog :model-value="open" width="640px" :show-close="false" align-center class="atp" @update:model-value="close">
    <template #header>
      <div class="head">
        <div><strong>{{ label }}을(를) 파티에 추가</strong><span>1. 파티 선택 → 2. 가득 찼다면 뺄 포켓몬 선택</span></div>
        <button class="x" @click="close">✕</button>
      </div>
    </template>
    <div class="list">
      <div v-for="p in parties" :key="p.id" class="party" :class="{ sel: target === p.id }" @click="pick(p.id)">
        <div class="ph">
          <strong>{{ p.name }}</strong><span class="sub">{{ p.sub }}</span>
          <span class="cnt mono" :class="{ full: p.slots.filter(Boolean).length >= 6 }">{{ p.slots.filter(Boolean).length }}/6</span>
        </div>
        <div class="slots">
          <button v-for="(s, i) in p.slots" :key="i" class="slot"
                  :class="{ empty: !s, out: target === p.id && out === i, can: target === p.id && full && s }"
                  @click.stop="pick(p.id); pickOut(p, i)">
            <PokemonImg :id="s?.pokemon || ''" :size="36" :dim="!s" />
            <span>{{ nameOf(s) }}</span>
          </button>
        </div>
        <span v-if="target === p.id && full && out === null" class="ask">파티가 가득 찼습니다. 뺄 포켓몬을 눌러주세요.</span>
      </div>
    </div>
    <template #footer>
      <div class="foot">
        <span class="summary">{{ summary }}</span>
        <button class="btn line" @click="close">취소</button>
        <button class="btn fill" :disabled="!canAdd" @click="confirm">추가</button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; }
.head div { display: flex; flex-direction: column; gap: 2px; }
.head strong { font-size: 18px; }
.head span { font-size: 12px; color: var(--c-muted); }
.x { margin-left: auto; width: 32px; height: 32px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; }
.list { display: flex; flex-direction: column; gap: 10px; }
.party { border: 1px solid var(--c-line); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; cursor: pointer; background: #fff; }
.party.sel { border: 2px solid var(--c-primary); background: var(--c-hover); }
.ph { display: flex; align-items: center; gap: 8px; }
.ph strong { font-size: 14px; }
.sub { font-size: 11px; color: var(--c-muted); }
.cnt { margin-left: auto; font-size: 12px; color: var(--c-ok); }
.cnt.full { color: var(--c-danger); }
.slots { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 6px; }
.slot { border: 1px solid var(--c-line-soft); border-radius: 6px; background: #fff; padding: 6px 0; display: flex; flex-direction: column; align-items: center; gap: 4px; color: var(--c-text); cursor: default; }
.slot span { font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.slot.empty { border-style: dashed; }
.slot.empty span { color: var(--c-faint); }
.slot.can { cursor: pointer; }
.slot.out { border: 2px solid var(--c-danger); background: #fbecea; }
.slot.out span { color: var(--c-danger); text-decoration: line-through; }
.ask { font-size: 12px; color: var(--c-danger); }
.foot { display: flex; gap: 8px; align-items: center; }
.summary { margin-right: auto; font-size: 12px; color: var(--c-text-3); }
.btn { height: 38px; padding: 0 14px; border-radius: 6px; font-size: 13px; }
.btn.line { border: 1px solid var(--c-text); background: #fff; }
.btn.fill { border: 0; background: var(--c-primary); color: #fbfbf9; font-weight: 600; padding: 0 16px; }
.btn.fill:disabled { background: #b9c6e6; cursor: default; }
</style>
