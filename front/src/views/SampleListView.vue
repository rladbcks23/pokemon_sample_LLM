<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api'
import { useLibrary } from '@/stores/library'
import { dex, loadDex } from '@/utils/dex'
import SampleTabs from '@/components/SampleTabs.vue'
import MemberCard from '@/components/MemberCard.vue'
import PagerNav from '@/components/PagerNav.vue'
import AddToPartyDialog from '@/components/AddToPartyDialog.vue'
import SampleDetailDialog from '@/components/SampleDetailDialog.vue'

// 포켓몬 샘플: 공개 샘플(OP.GG 샘플 등) 목록. 찜하거나 파티에 바로 추가
const route = useRoute()
const router = useRouter()
const library = useLibrary()
loadDex()

const fmt = computed(() => route.query.format || '')
const page = computed(() => Number(route.query.page) || 1)
const q = ref(route.query.q || '')
const data = ref(null)
const error = ref('')
const PAGE_SIZE = 12
const FORMATS = [['', '전체'], ['singles', '싱글'], ['doubles', '더블']]
const SOURCES = [['', '전체'], ['opgg_sample', 'OP.GG 샘플'], ['vgcpastes_team', '대회 팀'], ['opgg_team', 'OP.GG 팀']]
const src = computed(() => route.query.source || '')

function setQuery(patch) {
  const next = { ...route.query, ...patch }
  if (!('page' in patch)) delete next.page
  Object.keys(next).forEach((k) => (next[k] === '' || next[k] == null) && delete next[k])
  router.replace({ query: next })
}
let timer
watch(q, (v) => {
  clearTimeout(timer)
  timer = setTimeout(() => setQuery({ q: v.trim() }), 300)
})
watch(() => route.query, async () => {
  if (route.name !== 'samples') return
  error.value = ''
  try {
    data.value = await api.samples({ format: fmt.value, source: src.value, q: route.query.q, page: page.value, size: PAGE_SIZE })
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true, deep: true })
const pages = computed(() => Math.max(1, Math.ceil((data.value?.count || 0) / PAGE_SIZE)))

// 찜·파티 추가용 샘플 (공개 샘플 id 앞에 pub-)
const asSample = (x) => ({ ...JSON.parse(JSON.stringify(x.sample)), id: `pub-${x.id}` })
const isFav = (x) => library.isFavSample(`pub-${x.id}`)
function toggleFav(x) {
  library.toggleFavSample(asSample(x))
  ElMessage.success(isFav(x) ? '찜한 샘플에 담았습니다' : '찜을 해제했습니다')
}
const addOpen = ref(false)
const addSample = ref(null)
const names = computed(() => Object.fromEntries(Object.values(dex.pokemon).map((p) => [p.id, p.name_ko])))
// 샘플 상세보기 창
const detailOpen = ref(false)
const detailX = ref(null)
function openDetail(x) { detailX.value = x; detailOpen.value = true }
function addToParty(x) {
  addSample.value = { ...asSample(x), id: null }
  addOpen.value = true
}
</script>

<template>
  <section class="page">
    <div class="title"><h2>샘플</h2></div>
    <SampleTabs />

    <div class="controls">
      <div class="seg">
        <button v-for="[k, label] in FORMATS" :key="k" :class="{ on: fmt === k }" @click="setQuery({ format: k })">{{ label }}</button>
      </div>
      <div class="srcs">
        <span>출처</span>
        <button v-for="[k, label] in SOURCES" :key="k" :class="{ on: src === k }" @click="setQuery({ source: k })">{{ label }}</button>
      </div>
      <span v-if="data" class="count">{{ data.count.toLocaleString() }}개</span>
      <input v-model="q" class="search" placeholder="⌕ 포켓몬 (예: 한카리아스)">
    </div>

    <p v-if="error" class="empty err">{{ error }}</p>
    <p v-else-if="!data" class="muted">불러오는 중…</p>
    <template v-else>
      <div v-if="data.results.length" class="grid">
        <div v-for="x in data.results" :key="x.id" class="scard">
          <MemberCard :member="x.member" class="clickable" title="눌러서 상세보기" @click="openDetail(x)" />
          <div class="acts">
            <span class="from" :title="x.name">{{ x.source_label }}<template v-if="x.name"> · {{ x.name }}</template></span>
            <button class="fill sm" @click="addToParty(x)">파티에 추가</button>
            <button class="line sm" :class="{ on: isFav(x) }" @click="toggleFav(x)">{{ isFav(x) ? '♥ 찜함' : '♡ 찜하기' }}</button>
          </div>
        </div>
      </div>
      <div v-else class="empty">{{ route.query.q ? '조건에 맞는 샘플이 없습니다' : '아직 공개된 샘플이 없습니다' }}</div>
      <PagerNav :page="page" :pages="pages" @go="(p) => setQuery({ page: p })" />
    </template>

    <SampleDetailDialog v-model:open="detailOpen" :sample="detailX?.sample" :title="detailX?.name ? `포켓몬 샘플 · ${detailX.name}` : '포켓몬 샘플'">
      <template #actions>
        <div v-if="detailX" class="dacts">
          <button class="fill sm" @click="detailOpen = false; addToParty(detailX)">파티에 추가</button>
          <button class="line sm" :class="{ on: isFav(detailX) }" @click="toggleFav(detailX)">{{ isFav(detailX) ? '♥ 찜함' : '♡ 찜하기' }}</button>
        </div>
      </template>
    </SampleDetailDialog>
    <AddToPartyDialog v-model:open="addOpen" :sample="addSample" :label="names[addSample?.pokemon] || ''" :names="names"
                      @done="(m) => ElMessage.success(m)" />
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 24px; }
.title h2 { margin: 0; font-size: 28px; font-weight: 700; }
.muted { color: var(--c-muted); }
.controls { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.seg { display: flex; border: 1px solid var(--c-primary); border-radius: 6px; overflow: hidden; }
.seg button { border: 0; height: 38px; padding: 0 16px; font-size: 13px; background: #fff; color: var(--c-primary); }
.seg button.on { background: var(--c-primary); color: #fbfbf9; }
.srcs { display: flex; gap: 6px; align-items: center; }
.srcs span { font-size: 12px; color: var(--c-muted); margin-right: 4px; }
.srcs button { height: 32px; padding: 0 12px; border-radius: 16px; border: 1px solid var(--c-line-strong); background: #fff; font-size: 12px; }
.srcs button.on { border-color: var(--c-primary); background: var(--c-primary-soft); color: var(--c-primary); }
.from { margin-right: auto; align-self: center; font-size: 11px; color: var(--c-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.count { font-size: 13px; color: var(--c-muted); }
.search { margin-left: auto; width: 280px; height: 38px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 12px; font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.scard { display: flex; flex-direction: column; border: 1px solid var(--c-line); border-radius: 12px; overflow: hidden; background: #fff; }
.scard :deep(.mcard) { border: 0; border-radius: 0; }
.acts { display: flex; gap: 6px; border-top: 1px solid var(--c-line-faint); padding: 12px 18px 18px; }
.fill { border: 0; background: var(--c-primary); color: #fbfbf9; border-radius: 6px; font-weight: 600; }
.line { border: 1px solid var(--c-line-strong); background: #fff; color: var(--c-text); border-radius: 6px; }
.line.on { border-color: var(--c-heart); color: var(--c-heart); }
.dacts { display: flex; gap: 6px; }
.sm { height: 34px; font-size: 12px; padding: 0 14px; }
.empty { padding: 48px; text-align: center; color: var(--c-muted); font-size: 14px; border: 1.5px dashed var(--c-line-strong); border-radius: 12px; margin: 0; }
.err { color: var(--c-danger); }
</style>
