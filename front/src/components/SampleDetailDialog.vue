<script setup>
import { computed, ref, watch } from 'vue'
import { dex, loadDetail, loadDex, megaForm } from '@/utils/dex'
import { CATEGORY_KO, STATS, STAT_KO, calcStats } from '@/utils/pokemon'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'
import ItemIcon from '@/components/ItemIcon.vue'

// 샘플 상세보기 (띄우는 창): 실수치, 도구·특성·성격, 기술 + 각 설명
// sample: { pokemon, item, ability, nature, sp, moves } (ID만 있는 샘플 모양)
const props = defineProps({
  open: Boolean,
  sample: { type: Object, default: null },
  title: { type: String, default: '' },    // 창 위의 작은 글 (예: 내가 만든 샘플)
})
const emit = defineEmits(['update:open'])

const detail = ref(null)
watch(() => [props.open, props.sample?.pokemon], async ([open, id]) => {
  if (!open || !id) return
  detail.value = null
  await loadDex()
  detail.value = await loadDetail(id)
}, { immediate: true })

const s = computed(() => props.sample)
const base = computed(() => dex.pokemon[s.value?.pokemon])
const mega = computed(() => (s.value ? megaForm(s.value) : null))
const shown = computed(() => mega.value || base.value)     // 메가스톤을 들면 메가진화 후 기준
const nature = computed(() => dex.natures[s.value?.nature])
const item = computed(() => dex.items[s.value?.item])
// 특성: 이 포켓몬 특성 중에서 찾고, 없으면 메가 폼 특성 (OP.GG 샘플은 메가 특성으로 적혀 있기도 함)
const ability = computed(() => detail.value?.forms[0].abilities.find((a) => a.id === s.value?.ability)
  || (mega.value?.ability?.id === s.value?.ability ? mega.value.ability : null))
const isMegaAbility = computed(() => !!mega.value?.ability && ability.value?.id === mega.value.ability.id)
const moves = computed(() => {
  const map = Object.fromEntries((detail.value?.learnset || []).map((m) => [m.id, m]))
  return (s.value?.moves || []).filter(Boolean).map((id) => map[id] || { id, name_ko: id })
})

const rows = computed(() => {
  if (!shown.value) return []
  const n = nature.value
  const real = calcStats(shown.value.stats, s.value.sp, n?.plus, n?.minus)
  return STATS.map((k) => ({
    k, label: STAT_KO[k], base: shown.value.stats[k], sp: s.value.sp?.[k] || 0, real: real[k],
    mark: n?.plus === k ? 'up' : n?.minus === k ? 'down' : '',
  }))
})
const maxReal = computed(() => Math.max(1, ...rows.value.map((r) => r.real)))
const spSum = computed(() => rows.value.reduce((a, r) => a + r.sp, 0))
const natureText = computed(() => {
  const n = nature.value
  if (!n) return ''
  return n.plus ? `${STAT_KO[n.plus]}▲ ${STAT_KO[n.minus]}▼` : '보정 없음'
})
</script>

<template>
  <el-dialog :model-value="open" width="820px" :show-close="false" align-center class="sdd"
             @update:model-value="(v) => emit('update:open', v)">
    <template #header>
      <div class="head">
        <PokemonImg :id="shown?.id || s?.pokemon || ''" :size="72" />
        <div class="who">
          <span v-if="title" class="sub">{{ title }}</span>
          <div class="nm"><strong>{{ shown?.name_ko || s?.pokemon }}</strong><span v-if="mega" class="mega mono">MEGA</span></div>
          <div class="types"><TypeBadge v-for="t in shown?.types || []" :key="t" :type="t" :width="60" /></div>
        </div>
        <slot name="actions" />
        <button class="x" @click="emit('update:open', false)">✕</button>
      </div>
    </template>

    <div v-if="s" class="body">
      <div class="left">
        <div class="bh"><strong>실수치</strong><span class="mono">Lv50 · SP {{ spSum }}/66{{ mega ? ' · 메가진화 후' : '' }}</span></div>
        <div class="st head mono"><span>스탯</span><span>종족</span><span>SP</span><span /><span class="r">실수치</span></div>
        <div v-for="r in rows" :key="r.k" class="st">
          <span class="lbl">{{ r.label }}<small v-if="r.mark" :class="r.mark">{{ r.mark === 'up' ? '▲' : '▼' }}</small></span>
          <span class="mono muted">{{ r.base }}</span>
          <span class="mono" :class="{ muted: !r.sp }">{{ r.sp }}</span>
          <div class="bar"><div :class="r.mark" :style="{ width: (r.real / maxReal * 100) + '%' }" /></div>
          <strong class="mono r" :class="r.mark">{{ r.real }}</strong>
        </div>
      </div>

      <div class="right">
        <div class="info">
          <span class="k">도구</span>
          <div class="v">
            <div class="t"><ItemIcon :id="s.item" :size="22" /><strong>{{ item?.name_ko || '도구 없음' }}</strong></div>
            <p v-if="item?.desc">{{ item.desc }}</p>
          </div>
        </div>
        <div class="info">
          <span class="k">특성</span>
          <div class="v">
            <div class="t"><strong>{{ ability?.name_ko || s.ability || '—' }}</strong><span v-if="ability?.hidden" class="tag">숨겨진 특성</span></div>
            <p v-if="ability?.desc">{{ ability.desc }}</p>
            <p v-if="mega?.ability && !isMegaAbility" class="megaab">메가진화 후 특성: <strong>{{ mega.ability.name_ko }}</strong>
              <span v-if="mega.ability.desc"> · {{ mega.ability.desc }}</span></p>
            <p v-else-if="isMegaAbility" class="megaab">메가진화 후 특성</p>
          </div>
        </div>
        <div class="info">
          <span class="k">성격</span>
          <div class="v"><div class="t"><strong>{{ nature?.name_ko || '—' }}</strong><span v-if="natureText" class="eff">{{ natureText }}</span></div></div>
        </div>
      </div>
    </div>

    <div v-if="s" class="moves">
      <div class="bh"><strong>기술</strong></div>
      <div v-for="m in moves" :key="m.id" class="mv">
        <div class="mt">
          <strong>{{ m.name_ko }}</strong>
          <TypeBadge v-if="m.type" :type="m.type" :width="56" />
          <span class="cat">{{ CATEGORY_KO[m.category] || '' }}</span>
          <span class="mono nums">위력 {{ m.power || '—' }} · 명중 {{ m.accuracy || '—' }} · PP {{ m.pp ?? '—' }}</span>
        </div>
        <p v-if="m.desc">{{ m.desc }}</p>
      </div>
      <p v-if="!moves.length" class="muted">기술이 없습니다</p>
      <p v-else-if="!detail" class="muted">기술 정보를 불러오는 중…</p>
    </div>
  </el-dialog>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 14px; }
.who { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.sub { font-size: 12px; color: var(--c-muted); }
.nm { display: flex; align-items: center; gap: 8px; }
.nm strong { font-size: 20px; }
.mega { font-size: 10px; border: 1px solid var(--c-text); border-radius: 3px; padding: 1px 5px; }
.types { display: flex; gap: 4px; }
.x { margin-left: auto; width: 32px; height: 32px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; flex: none; }
.head :slotted(*) { margin-left: auto; }
.head :slotted(*) + .x { margin-left: 8px; }

.body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; }
.bh { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8px; }
.bh strong { font-size: 15px; }
.bh span { font-size: 12px; color: var(--c-muted); }
.st { display: grid; grid-template-columns: 52px 40px 32px minmax(0, 1fr) 44px; gap: 10px; align-items: center; font-size: 13px; padding: 5px 0; }
.st.head { font-size: 11px; color: var(--c-muted); padding-bottom: 2px; }
.lbl small { margin-left: 3px; font-size: 10px; }
.bar { height: 8px; background: var(--c-line-faint, #eee); border-radius: 4px; overflow: hidden; }
.bar div { height: 100%; background: var(--c-primary); border-radius: 4px; }
.bar div.up { background: var(--c-heart); }
.bar div.down { background: #6f8fd6; }
.r { text-align: right; }
.up { color: var(--c-heart); }
.down { color: #3d6fe0; }
.st strong.up, .st strong.down { font-weight: 700; }
.muted { color: var(--c-muted); }

.right { display: flex; flex-direction: column; gap: 14px; }
.info { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 10px; }
.k { font-size: 12px; color: var(--c-muted); padding-top: 3px; }
.v { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.t { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.v p { margin: 0; font-size: 12px; line-height: 1.55; color: var(--c-text-3); }
.tag { font-size: 10px; border: 1px solid var(--c-line-strong); border-radius: 3px; padding: 1px 6px; color: var(--c-text-3); }
.eff { font-size: 12px; color: var(--c-text-3); }
.megaab strong { color: var(--c-primary); }

.moves { margin-top: 22px; border-top: 1px solid var(--c-line); padding-top: 16px; display: flex; flex-direction: column; gap: 8px; }
.mv { border: 1px solid var(--c-line-soft); border-radius: 8px; padding: 10px 14px; display: flex; flex-direction: column; gap: 5px; }
.mt { display: flex; align-items: center; gap: 10px; font-size: 14px; }
.cat { font-size: 12px; color: var(--c-text-3); }
.nums { margin-left: auto; font-size: 11px; color: var(--c-muted); }
.mv p { margin: 0; font-size: 12px; line-height: 1.5; color: var(--c-text-3); }
</style>
