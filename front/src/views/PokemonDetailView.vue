<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { useSettings } from '@/stores/settings'
import { emptySample } from '@/stores/library'
import { CATEGORY_KO, STATS, STAT_KO, compareMoves, mulText, spText, toId } from '@/utils/pokemon'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'
import AddToPartyDialog from '@/components/AddToPartyDialog.vue'

const route = useRoute()
const router = useRouter()
const settings = useSettings()

const d = ref(null)
const error = ref('')
const formIdx = ref(0)
const uFmt = ref(settings.format)
const expanded = ref({})
const mq = ref('')
const mSort = ref({ k: 'type', dir: 1 })   // 기본: 타입 → 분류(물리·특수·변화) → 위력
const addOpen = ref(false)
const addMsg = ref('')
const names = ref({})

watch(() => route.params.id, async (id) => {
  d.value = null
  error.value = ''
  addMsg.value = ''
  try {
    d.value = await api.pokemon(id)
    // 메가 폼 ID로 들어왔으면 그 폼 탭을 선택
    formIdx.value = Math.max(0, d.value.forms.findIndex((f) => f.id === id))
    names.value = Object.fromEntries((await api.pokemonList(settings.format)).items.map((p) => [p.id, p.name_ko]))
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true })

const form = computed(() => d.value?.forms[formIdx.value])
const usage = computed(() => d.value?.usage[uFmt.value])

const statBars = computed(() => STATS.map((s) => ({
  s, label: STAT_KO[s], v: form.value.stats[s], pct: Math.min(100, (form.value.stats[s] / 180) * 100) + '%',
})))
const MATCH = [['weak', '약점', 'var(--c-heart)'], ['resist', '반감', 'var(--c-ok)'], ['immune', '무효', 'var(--c-primary)']]

// 사용률 5칸: 기술 / 도구 / 특성 / 성격 / SP 배분
const natureText = (n) => (n.plus ? `${n.name_ko} (${STAT_KO[n.plus]}▲ ${STAT_KO[n.minus]}▼)` : n.name_ko)
const usageCols = computed(() => {
  const u = usage.value
  if (!u) return []
  return [
    ['move', '기술', u.move.map((x) => ({ name: x.name_ko, pct: x.pct }))],
    ['item', '도구', u.item.map((x) => ({ name: x.name_ko, pct: x.pct }))],
    ['ability', '특성', u.ability.map((x) => ({ name: x.name_ko, pct: x.pct }))],
    ['nature', '성격', u.nature.map((x) => ({ name: natureText(x), pct: x.pct }))],
    ['spread', 'SP 배분', u.spread.map((x) => ({ name: spText(x.sp), pct: x.pct }))],
  ].map(([k, title, rows]) => ({ k, title, rows: expanded.value[k] ? rows : rows.slice(0, 4), more: rows.length - 4 }))
})
const allOpen = computed(() => usageCols.value.every((c) => expanded.value[c.k] || c.more <= 0))
function toggleAll() {
  const open = !allOpen.value
  expanded.value = Object.fromEntries(usageCols.value.map((c) => [c.k, open]))
}

// 배우는 기술 표 (열 제목 눌러 정렬)
const MOVE_COLS = [['name_ko', '기술'], ['type', '타입'], ['category', '분류'], ['power', '위력'], ['accuracy', '명중'], ['pp', 'PP']]
const learn = computed(() => {
  const k = mq.value.trim().toLowerCase()
  const { k: key, dir } = mSort.value
  return (d.value?.learnset || [])
    .filter((m) => !k || m.name_ko.toLowerCase().includes(k) || m.name.toLowerCase().includes(k))
    .sort((a, b) => {
      // 타입은 타입 순서(노말 → 페어리)로, 같으면 분류·위력 순
      if (key === 'type') return compareMoves(a, b) * dir
      const x = a[key] ?? -1
      const y = b[key] ?? -1
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'ko')) * dir || compareMoves(a, b)
    })
})
function sortBy(k) {
  mSort.value = { k, dir: mSort.value.k === k ? -mSort.value.dir : (k === 'name_ko' || k === 'type' ? 1 : -1) }
}
const arrow = (k) => (mSort.value.k === k ? (mSort.value.dir > 0 ? '▲' : '▼') : '↕')

// 샘플: 기본 폼 + (메가 탭이면 메가스톤)
const sample = computed(() => {
  const s = emptySample(d.value?.id)
  if (form.value?.is_mega) s.item = toId(form.value.required_item)
  return s
})
function toSample() {
  const q = { pokemon: d.value.id }
  if (form.value.is_mega) q.item = toId(form.value.required_item)
  router.push({ path: '/sample', query: q })
}
</script>

<template>
  <section v-if="error" class="page"><p class="err">{{ error }}</p></section>
  <section v-else-if="!d" class="page"><p class="muted">불러오는 중…</p></section>
  <section v-else class="page">
    <div class="topbar">
      <div class="crumb"><RouterLink to="/pokemon">포켓몬</RouterLink> / {{ d.name_ko }}</div>
      <div class="forms">
        <button v-for="(f, i) in d.forms" :key="f.id" :class="{ on: formIdx === i }" @click="formIdx = i">
          {{ f.name_ko }}
        </button>
      </div>
    </div>

    <div class="main">
      <div class="side">
        <PokemonImg :id="form.id" :size="200" />
        <span class="no mono">#{{ String(d.num).padStart(4, '0') }}</span>
        <strong class="fname">{{ form.name_ko }}</strong>
        <div class="types"><TypeBadge v-for="t in form.types" :key="t" :type="t" :width="120" /></div>
        <div class="acts">
          <button class="btn fill" @click="toSample">이 포켓몬으로 샘플 만들기</button>
          <span v-if="addMsg" class="ok">{{ addMsg }}</span>
          <button class="btn line" @click="addOpen = true">파티 빌딩에 추가</button>
        </div>
      </div>

      <div class="info">
        <div class="block">
          <div class="bh"><strong>종족값</strong><span class="mono">합계 <strong>{{ form.bst }}</strong></span></div>
          <div v-for="b in statBars" :key="b.s" class="stat">
            <span>{{ b.label }}</span><strong class="mono">{{ b.v }}</strong>
            <div class="bar"><div :style="{ width: b.pct }" /></div>
          </div>
        </div>
        <div class="two">
          <div class="block">
            <strong class="h">특성</strong>
            <div v-for="a in form.abilities" :key="a.id" class="ability">
              <div><strong>{{ a.name_ko }}</strong><span v-if="a.hidden" class="tag">숨겨진 특성</span></div>
              <span class="desc">{{ a.desc || '설명 준비 중' }}</span>
            </div>
          </div>
          <div class="block">
            <strong class="h">타입 상성</strong>
            <div v-for="[k, label, col] in MATCH" :key="k" class="mrow">
              <span class="ml" :style="{ color: col }">{{ label }}</span>
              <div class="mlist">
                <span v-for="x in form.matchups[k]" :key="x.type" class="mt">
                  <TypeBadge :type="x.type" :width="72" /><span class="mono">{{ mulText(x.multiplier) }}</span>
                </span>
                <span v-if="!form.matchups[k].length" class="none">없음</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="sh">
        <div class="st"><strong>사용률</strong><span>{{ settings.rulesetLabel }} 인게임 랭크배틀 기준</span></div>
        <div class="sr">
          <button class="link" @click="toggleAll">{{ allOpen ? '모두 접기' : '모두 펼치기' }}</button>
          <div class="tabs">
            <button :class="{ on: uFmt === 'singles' }" @click="uFmt = 'singles'">싱글</button>
            <button :class="{ on: uFmt === 'doubles' }" @click="uFmt = 'doubles'">더블</button>
          </div>
        </div>
      </div>
      <p v-if="!usage" class="muted">{{ settings.formatLabel(uFmt) }} 사용률 데이터가 없습니다</p>
      <div v-else class="ucols">
        <div v-for="c in usageCols" :key="c.k" class="ucol">
          <strong>{{ c.title }}</strong>
          <div v-for="(r, i) in c.rows" :key="i" class="urow">
            <div class="ut"><span>{{ r.name }}</span><span class="mono">{{ r.pct }}%</span></div>
            <div class="ub"><div :style="{ width: Math.min(100, r.pct) + '%' }" /></div>
          </div>
          <button v-if="c.more > 0" class="umore" @click="expanded = { ...expanded, [c.k]: !expanded[c.k] }">
            {{ expanded[c.k] ? '접기 ▴' : `+${c.more}개 더 보기 ▾` }}
          </button>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="sh">
        <div class="st"><strong>배우는 기술</strong><span>{{ learn.length }}개 · 열 제목을 눌러 정렬</span></div>
        <input v-model="mq" class="msearch" placeholder="⌕ 기술 검색">
      </div>
      <div class="mtable">
        <div class="mhead">
          <button v-for="[k, label] in MOVE_COLS" :key="k" class="mono" :class="{ on: mSort.k === k }" @click="sortBy(k)">
            {{ label }} <span>{{ arrow(k) }}</span>
          </button>
        </div>
        <div v-for="m in learn" :key="m.id" class="mrow2">
          <strong>{{ m.name_ko }}</strong>
          <TypeBadge :type="m.type" :width="60" />
          <span class="cat">{{ CATEGORY_KO[m.category] }}</span>
          <span class="mono">{{ m.power || '—' }}</span>
          <span class="mono">{{ m.accuracy || '—' }}</span>
          <span class="mono">{{ m.pp }}</span>
        </div>
      </div>
    </div>

    <AddToPartyDialog v-model:open="addOpen" :sample="sample" :label="form.name_ko" :names="names"
                      @done="(m) => (addMsg = m)" />
  </section>
</template>

<style scoped>
.page { padding: 32px 64px 56px; display: flex; flex-direction: column; gap: 36px; }
.muted { color: var(--c-muted); }
.err { color: var(--c-danger); }
.topbar { display: flex; align-items: center; justify-content: space-between; }
.crumb { font-size: 13px; color: var(--c-muted); }
.crumb a { color: var(--c-primary); }
.forms { display: flex; gap: 4px; border-bottom: 1px solid var(--c-line); }
.forms button { border: 0; background: none; padding: 8px 14px; font-size: 14px; color: var(--c-text-3); border-bottom: 2px solid transparent; margin-bottom: -1px; }
.forms button.on { font-weight: 600; color: var(--c-primary); border-bottom-color: var(--c-primary); }

.main { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 40px; }
.side { border: 1px solid var(--c-line); border-radius: 12px; padding: 28px; display: flex; flex-direction: column; align-items: center; gap: 12px; align-self: start; }
.no { font-size: 12px; color: var(--c-muted); }
.fname { font-size: 24px; }
.types { display: flex; gap: 6px; }
.acts { display: flex; flex-direction: column; gap: 8px; align-self: stretch; margin-top: 12px; }
.btn { height: 44px; border-radius: 6px; font-size: 14px; }
.btn.fill { border: 0; background: var(--c-primary); color: #fbfbf9; font-weight: 600; }
.btn.line { border: 1px solid var(--c-text); background: #fff; color: var(--c-text); }
.ok { font-size: 12px; color: var(--c-ok); text-align: center; }

.info { display: flex; flex-direction: column; gap: 32px; }
.block { display: flex; flex-direction: column; gap: 10px; }
.bh { display: flex; justify-content: space-between; align-items: baseline; }
.bh > strong, .h { font-size: 17px; }
.bh span { font-size: 13px; }
.stat { display: grid; grid-template-columns: 56px 44px minmax(0, 1fr); gap: 12px; align-items: center; font-size: 13px; }
.bar { height: 12px; background: var(--c-bar); border-radius: 3px; overflow: hidden; }
.bar div { height: 100%; background: var(--c-primary); }
.two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px; }
.ability { border: 1px solid var(--c-line-soft); border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
.ability > div { display: flex; align-items: center; gap: 8px; }
.ability strong { font-size: 14px; }
.tag { font-size: 10px; border: 1px solid var(--c-line-strong); border-radius: 3px; padding: 1px 5px; color: var(--c-text-3); }
.desc { font-size: 12px; color: var(--c-text-3); line-height: 1.5; }
.mrow { display: flex; gap: 12px; align-items: flex-start; }
.ml { width: 40px; flex: none; font-size: 13px; font-weight: 600; padding-top: 5px; }
.mlist { display: flex; flex-wrap: wrap; gap: 6px; }
.mt { display: inline-flex; align-items: center; gap: 4px; }
.mt .mono { font-size: 11px; color: var(--c-text-3); }
.none { font-size: 12px; color: var(--c-faint); padding-top: 5px; }

.section { display: flex; flex-direction: column; gap: 16px; }
.sh { display: flex; align-items: center; justify-content: space-between; }
.st { display: flex; align-items: baseline; gap: 12px; }
.st strong { font-size: 20px; }
.st span { font-size: 12px; color: var(--c-muted); }
.sr { display: flex; align-items: center; gap: 12px; }
.link { border: 0; background: none; font-size: 13px; color: var(--c-primary); text-decoration: underline; }
.tabs { display: flex; gap: 8px; background: var(--c-primary-soft); padding: 4px; border-radius: 8px; }
.tabs button { border: 0; height: 32px; padding: 0 16px; border-radius: 6px; font-size: 13px; font-weight: 600; background: transparent; }
.tabs button.on { background: #fff; }
.ucols { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 16px; align-items: start; }
.ucol { border: 1px solid var(--c-line); border-radius: 10px; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.ucol > strong { font-size: 14px; }
.urow { display: flex; flex-direction: column; gap: 3px; }
.ut { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; }
.ut span:first-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ub { height: 5px; background: var(--c-line-row); border-radius: 3px; overflow: hidden; }
.ub div { height: 100%; background: var(--c-primary); }
.umore { margin-top: 2px; height: 28px; border: 1px solid var(--c-line); border-radius: 6px; background: #fff; font-size: 12px; color: var(--c-primary); }
.umore:hover { border-color: var(--c-primary); }

.msearch { width: 260px; height: 38px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 12px; font-size: 13px; }
.mtable { border: 1px solid var(--c-line); border-radius: 8px; overflow: hidden; }
.mhead, .mrow2 { display: grid; grid-template-columns: minmax(0, 1fr) 100px 80px 80px 80px 60px; gap: 12px; padding: 10px 24px; align-items: center; }
.mhead { background: var(--c-head); }
.mhead button { border: 0; background: none; padding: 0; text-align: left; font-size: 12px; color: var(--c-muted); }
.mhead button.on { color: var(--c-primary); }
.mhead button span { opacity: .7; }
.mrow2 { padding: 9px 24px; border-top: 1px solid var(--c-line-row); font-size: 13px; }
.mrow2 strong { font-weight: 600; }
.cat { color: var(--c-text-3); }
</style>
