<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { useBuilder } from '@/stores/builder'
import { useLibrary } from '@/stores/library'
import { describe, dex, loadDetail, loadDex, megaForm } from '@/utils/dex'
import TeamCard from '@/components/TeamCard.vue'
import MemberCard from '@/components/MemberCard.vue'
import AddToPartyDialog from '@/components/AddToPartyDialog.vue'
import SampleDetailDialog from '@/components/SampleDetailDialog.vue'

const route = useRoute()
const router = useRouter()
const library = useLibrary()
const builder = useBuilder()
const ready = ref(false)

const TABS = [
  ['all', '전체'], ['favTeams', '찜한 파티'], ['favSamples', '찜한 샘플'], ['myTeams', '내가 만든 파티'], ['mySamples', '내가 만든 샘플'],
]
const tab = computed(() => (TABS.some(([k]) => k === route.query.tab) ? route.query.tab : 'all'))
const setTab = (k) => router.replace({ query: { tab: k } })
const isTeamTab = computed(() => tab.value === 'favTeams' || tab.value === 'myTeams')
const isAll = computed(() => tab.value === 'all')

onMounted(async () => { await loadDex(); ready.value = true })
// 샘플 목록: { s, fav } (전체 탭은 내가 만든 것 → 찜한 것 순)
const sampleRows = computed(() => [
  ...(tab.value === 'all' || tab.value === 'mySamples' ? library.mySamples.map((s) => ({ s, fav: false })) : []),
  ...(tab.value === 'all' || tab.value === 'favSamples' ? library.favSamples.map((s) => ({ s, fav: true })) : []),
])
watch(sampleRows, (list) => list.forEach(({ s }) => loadDetail(s.pokemon)), { immediate: true })

// 내가 만든 파티 → 카드용 요약 (메가스톤을 든 멤버는 메가 폼으로)
const myTeamCards = computed(() => library.myTeams.map((t) => ({
  id: t.id, title: t.name, source_label: t.format === 'singles' ? '내 파티 · 싱글' : '내 파티 · 더블',
  player: '나', date: new Date(t.updatedAt).toISOString().slice(0, 10),
  members: t.slots.filter(Boolean).map((s) => megaForm(s) || { id: s.pokemon, name_ko: dex.pokemon[s.pokemon]?.name_ko || s.pokemon }),
  raw: t,
})))
// 파티 목록: { c, fav }
const teamRows = computed(() => [
  ...(tab.value === 'all' || tab.value === 'myTeams' ? myTeamCards.value.map((c) => ({ c, fav: false })) : []),
  ...(tab.value === 'all' || tab.value === 'favTeams' ? library.favTeams.map((c) => ({ c, fav: true })) : []),
])

// 전체 탭: 처음엔 2줄씩(파티 2개×2줄, 샘플 3개×2줄), 더보기마다 2줄씩 추가
const TEAM_STEP = 4
const SAMPLE_STEP = 6
const teamLimit = ref(TEAM_STEP)
const sampleLimit = ref(SAMPLE_STEP)
watch(tab, () => { teamLimit.value = TEAM_STEP; sampleLimit.value = SAMPLE_STEP })
const teamsShown = computed(() => (isAll.value ? teamRows.value.slice(0, teamLimit.value) : teamRows.value))
const samplesShown = computed(() => (isAll.value ? sampleRows.value.slice(0, sampleLimit.value) : sampleRows.value))

// ---------------------------------------------------------------- 파티
async function editTeam(card) {
  if (card.raw) {
    builder.load6(JSON.parse(JSON.stringify(card.raw.slots)), { id: card.raw.id, title: card.raw.name })
  } else {
    // 찜한 파티는 서버에서 멤버 육성 정보를 받아 샘플로 변환
    const t = await api.team(card.id)
    builder.load6(t.members.map((m) => ({
      id: null, pokemon: m.base || m.pokemon.id, item: m.item?.id || '', ability: m.base_ability || m.ability?.id || '', nature: m.nature?.id || '',
      sp: { ...m.sp }, moves: [...m.moves.map((x) => x.id), '', '', '', ''].slice(0, 4),
    })), { title: t.title })
  }
  router.push('/builder')
}
async function removeTeam(card, fav) {
  await ElMessageBox.confirm(fav ? '찜을 해제할까요?' : `"${card.title}"을(를) 삭제할까요?`, fav ? '찜 해제' : '파티 삭제',
    { confirmButtonText: fav ? '해제' : '삭제', cancelButtonText: '취소' })
  if (fav) library.toggleFavTeam(card)
  else library.removeTeam(card.id)
}
const openCard = (card) => (card.raw ? editTeam(card) : router.push(`/teams/${card.id}`))

function newParty() { builder.reset(); router.push('/builder') }

// ---------------------------------------------------------------- 샘플
const addOpen = ref(false)
const addSample = ref(null)
const names = computed(() => Object.fromEntries(Object.values(dex.pokemon).map((p) => [p.id, p.name_ko])))
function addToBuilder(s) {
  const copy = JSON.parse(JSON.stringify(s))
  const i = builder.firstEmpty()
  if (i >= 0) {
    builder.setSlot(i, copy)
    router.push('/builder')
    return
  }
  addSample.value = copy            // 가득 찼으면 뺄 포켓몬 고르기
  addOpen.value = true
}
async function removeSample(s, fav) {
  await ElMessageBox.confirm(fav ? '찜을 해제할까요?' : '이 샘플을 삭제할까요?', fav ? '찜 해제' : '샘플 삭제',
    { confirmButtonText: fav ? '해제' : '삭제', cancelButtonText: '취소' })
  if (fav) library.removeFavSample(s.id)
  else library.removeSample(s.id)
}

// 샘플 상세보기 창
const detailOpen = ref(false)
const detailSample = ref(null)
const detailTitle = ref('')
function openDetail(s, title) { detailSample.value = s; detailTitle.value = title; detailOpen.value = true }

const EMPTY_HINT = {
  favTeams: '샘플 › 파티 샘플에서 ♡를 누르면 여기에 모입니다.',
  favSamples: '샘플 › 포켓몬 샘플에서 찜하면 여기에 모입니다.',
  myTeams: '파티 빌딩에서 저장하면 여기에 모입니다.',
  mySamples: '샘플 제작에서 저장하면 여기에 모입니다.',
}
const count = (k) => (k === 'all' ? library.myTeams.length + library.favTeams.length + library.mySamples.length
  + library.favSamples.length : library[k].length)
</script>

<template>
  <section class="page">
    <div class="head">
      <h2>마이페이지</h2>
      <span>찜한 파티·샘플과 내가 만든 파티·샘플은 이 브라우저에만 저장됩니다.</span>
    </div>

    <div class="tabs">
      <button v-for="[k, label] in TABS" :key="k" :class="{ on: tab === k }" @click="setTab(k)">
        {{ label }}<span class="mono">{{ count(k) }}</span>
      </button>
    </div>

    <div v-if="tab === 'myTeams' || tab === 'mySamples'" class="create">
      <span>{{ tab === 'myTeams' ? '빈 파티로 파티 빌딩을 엽니다' : '빈 샘플로 샘플 제작을 엽니다' }}</span>
      <button class="fill" @click="tab === 'myTeams' ? newParty() : router.push('/sample')">
        {{ tab === 'myTeams' ? '+ 파티 만들기' : '+ 샘플 만들기' }}
      </button>
    </div>

    <template v-if="isAll || isTeamTab">
      <div v-if="isAll" class="sec"><strong>파티</strong><span class="mono">{{ teamRows.length }}</span></div>
      <div v-if="teamRows.length" class="teams">
        <TeamCard v-for="{ c, fav } in teamsShown" :key="c.id" :team="c" :heart="false" @click="openCard(c)">
          <div class="acts">
            <span v-if="isAll" class="kind">{{ fav ? '찜한 파티' : '내가 만든 파티' }}</span>
            <button class="fill sm" @click.stop="editTeam(c)">파티 수정하기</button>
            <button class="danger sm" @click.stop="removeTeam(c, fav)">{{ fav ? '찜 해제' : '파티 삭제하기' }}</button>
          </div>
        </TeamCard>
      </div>
      <button v-if="isAll && teamRows.length > teamLimit" class="more" @click="teamLimit += TEAM_STEP">
        더보기 ({{ teamRows.length - teamLimit }}개 남음) ▾
      </button>
      <p v-if="isAll && !teamRows.length" class="none">저장하거나 찜한 파티가 없습니다</p>
    </template>

    <hr v-if="isAll" class="divider">

    <template v-if="isAll || !isTeamTab">
      <div v-if="isAll" class="sec"><strong>포켓몬 샘플</strong><span class="mono">{{ sampleRows.length }}</span></div>
      <div v-if="sampleRows.length" class="samples">
        <div v-for="{ s, fav } in samplesShown" :key="s.id" class="scard">
          <MemberCard v-if="ready && describe(s)" :member="describe(s)" class="clickable" title="눌러서 상세보기"
                      @click="openDetail(s, fav ? '찜한 샘플' : '내가 만든 샘플')" />
          <div class="acts">
            <button class="fill sm" @click="router.push({ path: '/sample', query: { sample: s.id } })">샘플 제작에서 열기</button>
            <button class="line sm" @click="addToBuilder(s)">파티 빌딩에 추가</button>
            <button class="danger sm push" @click="removeSample(s, fav)">{{ fav ? '찜 해제' : '삭제' }}</button>
          </div>
        </div>
      </div>
      <button v-if="isAll && sampleRows.length > sampleLimit" class="more" @click="sampleLimit += SAMPLE_STEP">
        더보기 ({{ sampleRows.length - sampleLimit }}개 남음) ▾
      </button>
      <p v-if="isAll && !sampleRows.length" class="none">저장하거나 찜한 샘플이 없습니다</p>
    </template>

    <div v-if="!isAll && (isTeamTab ? teamRows : sampleRows).length === 0" class="empty">
      <strong>아직 비어 있습니다</strong><span>{{ EMPTY_HINT[tab] }}</span>
    </div>

    <SampleDetailDialog v-model:open="detailOpen" :sample="detailSample" :title="detailTitle" />
    <AddToPartyDialog v-model:open="addOpen" :sample="addSample" :label="names[addSample?.pokemon] || ''" :names="names"
                      @done="(m) => ElMessage.success(m)" />
  </section>
</template>

<style scoped>
.page { padding: 40px 64px 56px; display: flex; flex-direction: column; gap: 24px; }
.head { display: flex; flex-direction: column; gap: 6px; }
.head h2 { margin: 0; font-size: 28px; font-weight: 700; }
.head span { font-size: 14px; color: var(--c-text-3); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--c-line); }
.tabs button { border: 0; background: none; padding: 10px 14px; font-size: 14px; color: var(--c-text-3); border-bottom: 2px solid transparent; margin-bottom: -1px; display: flex; gap: 6px; align-items: baseline; }
.tabs button.on { font-weight: 600; color: var(--c-primary); border-bottom-color: var(--c-primary); }
.tabs .mono { font-size: 12px; color: var(--c-faint); }
.create { display: flex; align-items: center; justify-content: space-between; }
.create span { font-size: 13px; color: var(--c-text-3); }
.fill { border: 0; background: var(--c-primary); color: #fbfbf9; border-radius: 6px; font-weight: 600; height: 38px; padding: 0 16px; font-size: 13px; }
.line { border: 1px solid var(--c-text); background: #fff; color: var(--c-text); border-radius: 6px; height: 34px; padding: 0 14px; font-size: 12px; }
.danger { border: 0; background: var(--c-danger); color: #fbfbf9; border-radius: 6px; font-weight: 600; }
.danger:hover { background: #8c3832; }
.push { margin-left: auto; }
.sm { height: 34px; font-size: 12px; padding: 0 14px; }
.teams { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.acts { display: flex; gap: 8px; border-top: 1px solid var(--c-line-faint); padding-top: 12px; }
.samples { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.scard { display: flex; flex-direction: column; gap: 0; border: 1px solid var(--c-line); border-radius: 12px; overflow: hidden; background: #fff; }
.scard :deep(.mcard) { border: 0; border-radius: 0; }
.scard .acts { padding: 12px 18px 18px; gap: 6px; }
.scard .sm { padding: 0 10px; }
.sec { display: flex; align-items: baseline; gap: 8px; margin-bottom: -8px; }
.sec strong { font-size: 18px; }
.sec .mono { font-size: 13px; color: var(--c-faint); }
.divider { border: 0; border-top: 1px solid var(--c-line-strong); margin: 8px 0; width: 100%; }
.more { align-self: center; height: 38px; padding: 0 28px; border: 1px solid var(--c-primary); border-radius: 19px; background: var(--c-primary-soft); font-size: 13px; font-weight: 600; color: var(--c-primary); }
.more:hover { background: var(--c-primary); color: #fbfbf9; }
.none { margin: 0; font-size: 13px; color: var(--c-muted); }
.kind { align-self: center; font-size: 11px; color: var(--c-muted); margin-right: auto; }
.empty { padding: 56px; text-align: center; border: 1.5px dashed var(--c-line-strong); border-radius: 12px; display: flex; flex-direction: column; gap: 8px; align-items: center; }
.empty strong { font-size: 15px; }
.empty span { font-size: 13px; color: var(--c-muted); }
</style>
