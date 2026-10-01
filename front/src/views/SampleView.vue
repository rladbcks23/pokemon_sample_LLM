<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { useBuilder } from '@/stores/builder'
import { emptySample, useLibrary } from '@/stores/library'
import { useSettings } from '@/stores/settings'
import { dex, loadDetail, loadDex } from '@/utils/dex'
import {
  CATEGORY_KO, SP_MAX_PER_STAT, SP_MAX_TOTAL, STATS, STAT_KO, calcStats, spText, spTotal, toId,
} from '@/utils/pokemon'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'
import ItemIcon from '@/components/ItemIcon.vue'

const route = useRoute()
const router = useRouter()
const builder = useBuilder()
const library = useLibrary()
const settings = useSettings()

const sample = ref(emptySample())
const detail = ref(null)
const moveSel = ref(null)
const checks = ref([])
const usageOpen = ref(false)
const usageTab = ref('move')
const msg = ref('')

// 파티 빌딩 N번 슬롯 편집 중인지
const slot = computed(() => (route.query.slot != null ? Number(route.query.slot) : null))
const fromBuilder = computed(() => slot.value !== null)

onMounted(async () => {
  await loadDex()
  const q = route.query
  let s = null
  if (fromBuilder.value) s = builder.slots[slot.value]
  if (!s && q.sample) s = library.mySamples.find((x) => x.id === q.sample)
  s = s ? JSON.parse(JSON.stringify(s)) : emptySample(q.pokemon || null)
  if (!s.id && q.item) s.item = q.item
  sample.value = s
})

// 포켓몬이 바뀌면 상세(특성·기술·사용률) 불러오고, 특성이 비었거나 안 맞으면 첫 특성으로
watch(() => sample.value.pokemon, async (id) => {
  detail.value = id ? await loadDetail(id) : null
  const abilities = detail.value?.forms[0].abilities || []
  if (detail.value && !abilities.some((a) => a.id === sample.value.ability)) {
    sample.value.ability = abilities[0]?.id || ''
  }
})

const pokemonOptions = computed(() => (dex.list || []).slice().sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999)))
const mon = computed(() => dex.pokemon[sample.value.pokemon])
const abilities = computed(() => detail.value?.forms[0].abilities || [])
const nature = computed(() => dex.natures[sample.value.nature])
const natureText = (n) => (n?.plus ? `${STAT_KO[n.plus]}▲ ${STAT_KO[n.minus]}▼` : '무보정')

// 성격: 무보정 5개는 효과가 같아 "노력"만 남기고, 나머지는 올라가는 스탯별로 묶음
const NEUTRAL = 'hardy'
const natureGroups = computed(() => {
  const all = dex.options?.natures || []
  const groups = [{ label: '무보정', natures: all.filter((n) => n.id === NEUTRAL) }]
  for (const st of STATS.slice(1)) {
    const natures = all.filter((n) => n.plus === st)
      .sort((a, b) => STATS.indexOf(a.minus) - STATS.indexOf(b.minus))
    groups.push({ label: `${STAT_KO[st]}▲`, natures })
  }
  return groups
})
const normNature = (id) => (id && !dex.natures[id]?.plus ? NEUTRAL : id)

function pickPokemon(id) {
  sample.value = { ...emptySample(id), id: sample.value.id }
  moveSel.value = null
}

// ---------------------------------------------------------------- SP
const used = computed(() => spTotal(sample.value.sp))
const left = computed(() => SP_MAX_TOTAL - used.value)
function setSp(stat, v) {
  const others = used.value - sample.value.sp[stat]
  sample.value.sp[stat] = Math.max(0, Math.min(SP_MAX_PER_STAT, Math.round(v) || 0, SP_MAX_TOTAL - others))
}
const actual = computed(() => (mon.value
  ? calcStats(mon.value.stats, sample.value.sp, nature.value?.plus, nature.value?.minus)
  : null))

// ---------------------------------------------------------------- 기술
const learn = computed(() => (detail.value?.learnset || []).slice().sort((a, b) => (b.power || 0) - (a.power || 0)))
const moveMap = computed(() => Object.fromEntries((detail.value?.learnset || []).map((m) => [m.id, m])))
const moveHint = computed(() => (moveSel.value !== null
  ? `${moveSel.value + 1}번 칸 선택됨 · 아래에서 바꿀 기술을 누르세요`
  : '기술 4개 · 칸을 누르고 아래에서 바꿀 기술 선택'))
const learnHint = computed(() => (moveSel.value !== null
  ? `${moveSel.value + 1}번 칸을 이 기술로 교체`
  : `${learn.value.length}개 · 누르면 빈 칸에 추가`))
function pickMove(id) {
  const moves = sample.value.moves
  if (moves.includes(id)) return
  const i = moveSel.value !== null ? moveSel.value : moves.findIndex((m) => !m)
  if (i < 0) return
  moves.splice(i, 1, id)
  moveSel.value = null
}
function clearMove(i) { sample.value.moves.splice(i, 1, ''); moveSel.value = null }

// ---------------------------------------------------------------- 참고: 인기 육성 (현재 싱글/더블 기준)
const usage = computed(() => detail.value?.usage[settings.format])
const natureName = (id) => dex.natures[id]?.name_ko || id
const refBars = computed(() => {
  const u = usage.value
  if (!u) return []
  return [
    ['spread', 'SP', u.spread[0] && spText(u.spread[0].sp), u.spread[0]?.pct],
    ['item', '도구', u.item[0]?.name_ko, u.item[0]?.pct],
    ['ability', '특성', u.ability[0]?.name_ko, u.ability[0]?.pct],
    ['nature', '성격', u.nature[0]?.name_ko, u.nature[0]?.pct],
    ['move', '기술', u.move[0]?.name_ko, u.move[0]?.pct],
  ].filter((r) => r[2]).map(([tab, k, n, p]) => ({ tab, k, n, p }))
})
function loadRef() {
  const u = usage.value
  if (!u) return
  const s = sample.value
  if (u.spread[0]) s.sp = { ...s.sp, ...Object.fromEntries(STATS.map((x) => [x, u.spread[0].sp[x] || 0])) }
  if (u.item[0]) s.item = u.item[0].id
  if (u.ability[0] && abilities.value.some((a) => a.id === u.ability[0].id)) s.ability = u.ability[0].id
  if (u.nature[0]) s.nature = normNature(u.nature[0].id)
  const learnable = new Set(learn.value.map((m) => m.id))
  s.moves = [...u.move.map((m) => m.id).filter((id) => learnable.has(id)).slice(0, 4), '', '', '', ''].slice(0, 4)
  moveSel.value = null
}
const USAGE_TABS = [['move', '기술'], ['item', '도구'], ['ability', '특성'], ['nature', '성격'], ['spread', 'SP 배분']]
const usageRows = computed(() => {
  const u = usage.value
  if (!u) return []
  return u[usageTab.value].map((x, i) => ({
    rank: i + 1, p: x.pct,
    name: usageTab.value === 'spread' ? spText(x.sp) : usageTab.value === 'nature' ? natureName(x.id) : x.name_ko,
  }))
})
function openUsage(tab) { usageTab.value = tab; usageOpen.value = true }

// ---------------------------------------------------------------- 적합성 검사 (서버)
let timer
watch(sample, (s) => {
  clearTimeout(timer)
  msg.value = ''
  if (!s.pokemon) { checks.value = []; return }
  timer = setTimeout(async () => {
    try {
      checks.value = (await api.validate({ ...s, moves: s.moves.filter(Boolean) })).checks
    } catch (e) {
      checks.value = [{ level: 'error', message: e.message }]
    }
  }, 250)
}, { deep: true })
const MARK = { ok: '✓', warn: '!', error: '✕' }

// ---------------------------------------------------------------- 저장
function save() {
  if (!sample.value.pokemon) { msg.value = '포켓몬을 먼저 선택하세요'; return null }
  const saved = library.saveSample(sample.value)
  sample.value.id = saved.id
  return saved
}
function saveOnly() {
  if (save()) router.push({ path: '/mypage', query: { tab: 'mySamples' } })
}
function saveAdd() {
  const saved = save()
  if (!saved) return
  builder.setSlot(slot.value, JSON.parse(JSON.stringify(saved)))
  router.push('/builder')
}
const itemIdOf = (form) => toId(form.required_item)
</script>

<template>
  <section class="page">
    <div v-if="fromBuilder" class="ctx mono">← 파티 빌딩 · 슬롯 {{ slot + 1 }} 편집 중</div>
    <div class="grid">
      <!-- 왼쪽: 포켓몬·도구·특성·성격·기술 -->
      <div class="col">
        <el-select :model-value="sample.pokemon" filterable placeholder="⌕ 포켓몬 검색 (한글/영문)" class="sel"
                   @change="pickPokemon">
          <el-option v-for="p in pokemonOptions" :key="p.id" :value="p.id" :label="`${p.name_ko} ${p.name}`">
            <span class="opt"><PokemonImg :id="p.id" :size="24" />{{ p.name_ko }}<span class="opt-sub">{{ p.name }}</span></span>
          </el-option>
        </el-select>
        <div class="card">
          <PokemonImg :id="sample.pokemon || ''" :size="128" />
          <strong>{{ mon?.name_ko || '포켓몬 선택' }}</strong>
          <div class="types"><TypeBadge v-for="t in mon?.types || []" :key="t" :type="t" :width="60" /></div>
        </div>

        <label class="fld"><span>도구</span>
          <el-select v-model="sample.item" filterable clearable placeholder="도구 선택" class="sel">
            <template #prefix><ItemIcon :id="sample.item" :size="24" /></template>
            <el-option v-for="it in dex.options?.items || []" :key="it.id" :value="it.id" :label="it.name_ko">
              <span class="opt"><ItemIcon :id="it.id" :size="20" />{{ it.name_ko }}</span>
            </el-option>
          </el-select>
        </label>
        <label class="fld"><span>특성 · 이 포켓몬이 가진 것만</span>
          <el-select v-model="sample.ability" placeholder="특성 선택" class="sel" :disabled="!abilities.length">
            <el-option v-for="a in abilities" :key="a.id" :value="a.id" :label="a.name_ko + (a.hidden ? ' (숨겨진 특성)' : '')" />
          </el-select>
        </label>
        <label class="fld"><span>성격</span>
          <el-select v-model="sample.nature" filterable placeholder="성격 선택" class="sel">
            <el-option-group v-for="g in natureGroups" :key="g.label" :label="g.label">
              <el-option v-for="n in g.natures" :key="n.id" :value="n.id" :label="n.name_ko">
                <span class="opt">{{ n.name_ko }}<span class="opt-sub">{{ natureText(n) }}</span></span>
              </el-option>
            </el-option-group>
          </el-select>
        </label>

        <div class="fld"><span>{{ moveHint }}</span>
          <div v-for="(m, i) in sample.moves" :key="i" class="mslot" :class="{ sel: moveSel === i, empty: !m }"
               @click="moveSel = moveSel === i ? null : i">
            <span class="mono idx">{{ i + 1 }}</span>
            <span>{{ m ? (moveMap[m]?.name_ko || m) : '⌕ 기술 검색' }}</span>
            <span v-if="m" class="mtype">{{ moveMap[m] ? CATEGORY_KO[moveMap[m].category] : '' }}</span>
            <button v-if="m" class="mx" title="비우기" @click.stop="clearMove(i)">✕</button>
          </div>
        </div>
      </div>

      <!-- 가운데: SP 배분, 배울 수 있는 기술 -->
      <div class="col wide">
        <div class="block">
          <div class="bh"><strong>SP 배분</strong>
            <span><span class="muted">{{ SP_MAX_TOTAL }} 중 </span><strong class="mono big">{{ left }}</strong><span class="muted"> 남음</span></span>
          </div>
          <div class="usedbar"><div :style="{ width: (used / SP_MAX_TOTAL * 100) + '%' }" /></div>
          <div class="sprow head mono"><span>스탯</span><span>종족</span><span /><span /><span>SP · 최대 32</span><span /><span /><span class="c">SP</span><span class="r">실수치</span></div>
          <div v-for="s in STATS" :key="s" class="sprow">
            <span class="lbl">{{ STAT_KO[s] }} <small>{{ nature?.plus === s ? '▲' : nature?.minus === s ? '▼' : '' }}</small></span>
            <span class="mono base">{{ mon?.stats[s] ?? '—' }}</span>
            <button class="pill mono" title="0으로" @click="setSp(s, 0)">0</button>
            <button class="pm" @click="setSp(s, sample.sp[s] - 1)">−</button>
            <input type="range" min="0" :max="SP_MAX_PER_STAT" :value="sample.sp[s]" @input="setSp(s, +$event.target.value)">
            <button class="pm" @click="setSp(s, sample.sp[s] + 1)">+</button>
            <button class="pill mono" title="남은 포인트 안에서 최대(32)" @click="setSp(s, SP_MAX_PER_STAT)">max</button>
            <input class="num mono" type="number" min="0" :max="SP_MAX_PER_STAT" :value="sample.sp[s]"
                   @change="setSp(s, +$event.target.value); $event.target.value = sample.sp[s]">
            <strong class="mono act r" :class="{ plus: nature?.plus === s, minus: nature?.minus === s }">{{ actual?.[s] ?? '—' }}</strong>
          </div>
          <span class="note">실수치: Lv50 · 성격 보정 반영</span>
        </div>

        <div class="block">
          <div class="bh"><strong>배울 수 있는 기술</strong><span class="hint" :class="{ on: moveSel !== null }">{{ learnHint }}</span></div>
          <div class="ltable">
            <div class="lrow head mono"><span>기술</span><span>타입</span><span>분류</span><span>위력</span><span>명중</span><span>PP</span></div>
            <div v-for="m in learn" :key="m.id" class="lrow" :class="{ picked: sample.moves.includes(m.id) }" @click="pickMove(m.id)">
              <span class="ln">{{ m.name_ko }}</span>
              <TypeBadge :type="m.type" :width="56" />
              <span class="cat">{{ CATEGORY_KO[m.category] }}</span>
              <span class="mono">{{ m.power || '—' }}</span>
              <span class="mono">{{ m.accuracy || '—' }}</span>
              <span class="mono">{{ m.pp }}</span>
            </div>
            <p v-if="!learn.length" class="lempty">포켓몬을 선택하면 배울 수 있는 기술이 나옵니다</p>
          </div>
        </div>
      </div>

      <!-- 오른쪽: 참고, 적합성 검사, 저장 -->
      <div class="col">
        <div class="ref">
          <div class="rh"><strong>참고 · 인기 육성</strong><span>{{ mon ? `${mon.name_ko} 사용률 1위 조합 · ${settings.formatLabel()}` : '포켓몬을 선택하세요' }}</span></div>
          <p v-if="mon && !refBars.length" class="muted small">{{ settings.formatLabel() }} 사용률 데이터가 없습니다</p>
          <div v-for="rb in refBars" :key="rb.k" class="rb" title="항목별 사용률 보기" @click="openUsage(rb.tab)">
            <div class="rbt"><span><span class="k">{{ rb.k }}</span> {{ rb.n }}</span><span class="mono">{{ rb.p }}%</span></div>
            <div class="bar"><div :style="{ width: rb.p + '%' }" /></div>
          </div>
          <template v-if="refBars.length">
            <button class="link" @click="openUsage('move')">항목별 사용률 전체 보기 →</button>
            <button class="btn line" @click="loadRef">한 번에 불러오기</button>
          </template>
          <div v-if="detail?.forms.length > 1" class="megas">
            <span>메가스톤</span>
            <button v-for="f in detail.forms.filter((x) => x.is_mega)" :key="f.id" class="chip"
                    :class="{ on: sample.item === itemIdOf(f) }" @click="sample.item = itemIdOf(f)">{{ f.name_ko }}</button>
          </div>
        </div>

        <div class="checks">
          <strong>적합성 검사</strong>
          <div v-for="(c, i) in checks" :key="i" class="chk" :class="c.level">
            <span class="mono">{{ MARK[c.level] }}</span><span>{{ c.message }}</span>
          </div>
          <span v-if="!checks.length" class="muted small">포켓몬을 선택하면 검사합니다</span>
        </div>

        <div class="save">
          <span v-if="msg" class="msg">{{ msg }}</span>
          <template v-if="fromBuilder">
            <button class="btn fill" @click="saveAdd">샘플 저장 + 파티에 추가</button>
            <button class="btn line" @click="router.push('/builder')">취소하고 파티 빌딩으로</button>
          </template>
          <button v-else class="btn fill" @click="saveOnly">샘플 저장</button>
        </div>
      </div>
    </div>

    <el-dialog v-model="usageOpen" width="640px" :show-close="false" align-center>
      <template #header>
        <div class="uh">
          <div><strong>{{ mon?.name_ko }} 항목별 사용률</strong><span>{{ settings.formatLabel() }} · {{ settings.rulesetLabel }} 인게임 랭크배틀</span></div>
          <button class="x" @click="usageOpen = false">✕</button>
        </div>
      </template>
      <div class="utabs">
        <button v-for="[k, label] in USAGE_TABS" :key="k" :class="{ on: usageTab === k }" @click="usageTab = k">{{ label }}</button>
      </div>
      <div class="urows">
        <div v-for="u in usageRows" :key="u.rank" class="urow">
          <span class="mono rk">{{ u.rank }}</span><span>{{ u.name }}</span>
          <div class="bar"><div :style="{ width: u.p + '%' }" /></div>
          <span class="mono r">{{ u.p }}%</span>
        </div>
      </div>
    </el-dialog>
  </section>
</template>

<style scoped>
.page { padding: 40px 32px 48px; display: flex; flex-direction: column; gap: 16px; }
.ctx { font-size: 12px; color: var(--c-primary); }
.grid { display: grid; grid-template-columns: 320px minmax(0, 1fr) 300px; gap: 32px; }
.col { display: flex; flex-direction: column; gap: 18px; }
.col.wide { gap: 28px; }
.muted { color: var(--c-muted); }
.small { font-size: 12px; margin: 0; }
.sel { width: 100%; }
.sel :deep(.el-select__wrapper) { min-height: 40px; border-radius: 6px; }
.opt { display: flex; align-items: center; gap: 8px; }
.opt-sub { margin-left: auto; font-size: 11px; color: var(--c-muted); }
.card { border: 1px solid var(--c-line-card); border-radius: 10px; padding: 20px; display: flex; flex-direction: column; align-items: center; gap: 10px; background: #fff; }
.card strong { font-size: 18px; }
.types { display: flex; gap: 6px; }
.fld { display: flex; flex-direction: column; gap: 6px; }
.fld > span { font-size: 12px; color: var(--c-muted); }
.mslot { height: 38px; border: 1px solid var(--c-line-strong); border-radius: 6px; display: flex; align-items: center; gap: 8px; padding: 0 12px; font-size: 13px; background: #fff; cursor: pointer; }
.mslot.empty { border: 1px dashed var(--c-danger); color: var(--c-muted); }
.mslot.sel { border: 2px solid var(--c-primary); background: var(--c-primary-soft); }
.idx { font-size: 11px; color: var(--c-faint); }
.mtype { margin-left: auto; font-size: 11px; color: var(--c-muted); }
.mx { border: 0; background: none; color: var(--c-faint); font-size: 11px; padding: 0 2px; }
.mx:hover { color: var(--c-danger); }

.block { display: flex; flex-direction: column; gap: 14px; }
.bh { display: flex; align-items: baseline; justify-content: space-between; }
.bh > strong { font-size: 17px; }
.bh > span { font-size: 14px; }
.big { font-size: 18px; }
.usedbar { height: 6px; background: var(--c-bar); border-radius: 3px; overflow: hidden; }
.usedbar div { height: 100%; background: var(--c-primary); }
/* 스탯 이름과 종족값은 붙여서 (이름 칸을 줄이고 종족값 왼쪽 정렬) */
.sprow { display: grid; grid-template-columns: 50px 32px 36px 32px minmax(0, 1fr) 32px 44px 52px 64px; gap: 10px; align-items: center; }
.sprow.head { font-size: 11px; color: var(--c-faint); }
.r { text-align: right; }
.c { text-align: center; }
.lbl { font-size: 13px; }
.lbl small { font-size: 11px; }
.base { font-size: 14px; color: var(--c-text-3); }
.pill { height: 32px; border: 1px solid var(--c-line-strong); border-radius: 16px; background: #fff; font-size: 11px; padding: 0; }
.pm { width: 32px; height: 32px; border: 1px solid var(--c-line-strong); border-radius: 4px; background: #fff; font-size: 16px; line-height: 1; padding: 0; }
.pill:hover, .pm:hover { border-color: var(--c-text); }
.sprow input[type=range] { width: 100%; accent-color: var(--c-primary); }
.num { height: 32px; width: 100%; border: 1px solid var(--c-line-strong); border-radius: 4px; text-align: center; font-size: 13px; -moz-appearance: textfield; }
.num::-webkit-inner-spin-button { -webkit-appearance: none; }
.act { font-size: 16px; }
.act.plus { color: var(--c-heart); }
.act.minus { color: var(--c-primary); }
.note { font-size: 11px; color: var(--c-faint); text-align: right; }
.hint { font-size: 12px; color: var(--c-muted); }
.hint.on { color: var(--c-primary); }
.ltable { border: 1px solid var(--c-line); border-radius: 8px; overflow: auto; max-height: 300px; }
.lrow { display: grid; grid-template-columns: minmax(0, 1fr) 72px 56px 48px 48px 36px; gap: 10px; padding: 7px 14px; border-top: 1px solid var(--c-line-row); align-items: center; font-size: 12px; cursor: pointer; }
.lrow:hover { background: var(--c-hover); }
.lrow.picked { background: var(--c-primary-soft); }
.lrow.head { position: sticky; top: 0; z-index: 1; padding: 8px 14px; background: var(--c-head); font-size: 11px; color: var(--c-muted); border-top: 0; cursor: default; }
.ln { font-weight: 600; }
.cat { color: var(--c-text-3); }
.lempty { padding: 24px; text-align: center; color: var(--c-muted); font-size: 12px; margin: 0; }

.ref { border: 1px solid var(--c-line-card); border-radius: 10px; padding: 18px; display: flex; flex-direction: column; gap: 14px; background: var(--c-hover); }
.rh { display: flex; flex-direction: column; gap: 2px; }
.rh strong { font-size: 14px; }
.rh span { font-size: 12px; color: var(--c-muted); }
.rb { display: flex; flex-direction: column; gap: 3px; cursor: pointer; padding: 4px; margin: -4px; border-radius: 4px; }
.rb:hover { background: var(--c-bar); }
.rbt { display: flex; justify-content: space-between; font-size: 12px; gap: 8px; }
.k { color: var(--c-faint); }
.bar { height: 5px; background: var(--c-line-row); border-radius: 3px; overflow: hidden; }
.bar div { height: 100%; background: var(--c-primary); }
.link { border: 0; background: none; font-size: 12px; text-decoration: underline; color: var(--c-text-2); text-align: left; padding: 0; }
.megas { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; }
.megas > span { color: var(--c-muted); }
.chip { height: 26px; padding: 0 10px; border: 1px solid var(--c-line-strong); border-radius: 13px; background: #fff; font-size: 11px; }
.chip.on { border-color: var(--c-primary); color: var(--c-primary); background: var(--c-primary-soft); }
.checks { display: flex; flex-direction: column; gap: 8px; }
.checks > strong { font-size: 14px; }
.chk { display: flex; gap: 8px; font-size: 12px; line-height: 1.5; }
.chk .mono { font-weight: 600; }
.chk.ok { color: var(--c-ok); }
.chk.warn { color: var(--c-warn); }
.chk.error { color: var(--c-danger); }
.save { display: flex; flex-direction: column; gap: 8px; margin-top: auto; }
.msg { font-size: 12px; color: var(--c-danger); text-align: center; }
.btn { height: 42px; border-radius: 6px; font-size: 14px; }
.btn.fill { border: 0; background: var(--c-primary); color: #fbfbf9; font-weight: 600; }
.btn.line { height: 38px; border: 1px solid var(--c-text); background: #fff; font-size: 13px; font-weight: 600; }

.uh { display: flex; align-items: center; justify-content: space-between; }
.uh div { display: flex; flex-direction: column; gap: 2px; }
.uh strong { font-size: 18px; }
.uh span { font-size: 12px; color: var(--c-muted); }
.x { width: 32px; height: 32px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; }
.utabs { display: flex; gap: 4px; border-bottom: 1px solid var(--c-line); margin-bottom: 16px; }
.utabs button { border: 0; background: none; padding: 10px 12px; font-size: 14px; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.utabs button.on { font-weight: 600; border-bottom-color: var(--c-primary); }
.urows { display: flex; flex-direction: column; gap: 10px; }
.urow { display: grid; grid-template-columns: 24px 160px minmax(0, 1fr) 52px; gap: 12px; align-items: center; font-size: 13px; }
.urow .rk { color: var(--c-faint); }
.urow .bar { height: 8px; border-radius: 4px; }
</style>
