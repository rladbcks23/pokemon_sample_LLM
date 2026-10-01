<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useBuilder } from '@/stores/builder'
import { useLibrary } from '@/stores/library'
import { useSettings } from '@/stores/settings'
import { describe, dex, loadDetail, loadDex, megaForm } from '@/utils/dex'
import { TYPES } from '@/utils/pokemon'
import MemberCard from '@/components/MemberCard.vue'
import WeaknessTable from '@/components/WeaknessTable.vue'
import PokemonPicker from '@/components/PokemonPicker.vue'
import CoachChat from '@/components/CoachChat.vue'
import FormatToggle from '@/components/FormatToggle.vue'
import SampleDetailDialog from '@/components/SampleDetailDialog.vue'

const router = useRouter()
const builder = useBuilder()
const library = useLibrary()
const settings = useSettings()

const chatOpen = ref(false)   // 파티 코치는 접힌 상태로 시작
const pickerOpen = ref(false)
const pickerSlot = ref(0)
const ready = ref(false)

onMounted(async () => {
  await loadDex()
  ready.value = true
})
// 포켓몬 고르기 목록은 고른 싱글/더블의 사용률 순위
const pickList = ref([])
watch(() => settings.format, async (fmt) => { pickList.value = (await api.pokemonList(fmt)).items }, { immediate: true })
// 슬롯 포켓몬의 상세(기술·특성 이름) 불러오기
watch(() => builder.slots.map((s) => s?.pokemon), (ids) => ids.filter(Boolean).forEach(loadDetail), { immediate: true })

const members = computed(() => (ready.value ? builder.slots.map((s) => (s ? describe(s) : null)) : []))
const names = computed(() => Object.fromEntries(Object.values(dex.pokemon).map((p) => [p.id, p.name_ko])))

// 약점표: 메가스톤을 든 멤버는 메가 폼 타입 기준
const weakRows = computed(() => {
  const chart = dex.options?.typechart
  if (!chart) return []
  return builder.slots.filter(Boolean).map((s) => {
    const types = megaForm(s)?.types || dex.pokemon[s.pokemon]?.types || []
    const cells = Object.fromEntries(TYPES.map((t) => [t, types.reduce((m, d) => m * (chart[t]?.[d] ?? 1), 1)]))
    return { name: megaForm(s)?.name_ko || names.value[s.pokemon] || s.pokemon, cells }
  })
})

function openPicker(i) { pickerSlot.value = i; pickerOpen.value = true }
// { pokemon, item? } (메가 폼을 고르면 기본 폼 + 메가스톤)
function onPick({ pokemon, item }) { router.push({ path: '/sample', query: { slot: pickerSlot.value, pokemon, item } }) }
// 내 샘플(만든 것 + 찜한 것)을 바로 슬롯에
const mySamples = computed(() => {
  if (!ready.value) return []
  const list = [...library.mySamples, ...library.favSamples]
  return list.map((sample) => ({ sample, member: describe(sample) })).filter((x) => x.member)
})
watch(() => [...library.mySamples, ...library.favSamples].map((s) => s.pokemon), (ids) => ids.forEach(loadDetail),
  { immediate: true })
function onPickSample(sample) {
  builder.setSlot(pickerSlot.value, JSON.parse(JSON.stringify({ ...sample, id: sample.id ?? null })))
  ElMessage.success('샘플을 불러왔습니다')
}
const detailOpen = ref(false)
const detailSample = ref(null)
const edit = (i) => router.push({ path: '/sample', query: { slot: i } })

async function clearAll() {
  if (!builder.count) return
  await ElMessageBox.confirm('파티 6칸을 모두 비울까요?', '비우기', { confirmButtonText: '비우기', cancelButtonText: '취소' })
  builder.reset()
}
function save() {
  if (!builder.count) { ElMessage.warning('포켓몬을 먼저 추가하세요'); return }
  const t = library.saveTeam({ id: builder.teamId, name: builder.name || '새 파티', format: settings.format,
    slots: JSON.parse(JSON.stringify(builder.slots)) })
  // 저장하면 파티 빌딩을 비우고 마이페이지(내가 만든 파티)로
  builder.reset()
  ElMessage.success(`"${t.name}"을(를) 내 파티에 저장했습니다`)
  router.push({ path: '/mypage', query: { tab: 'myTeams' } })
}
function loadTeam(t) {
  if (t.format) settings.format = t.format
  builder.load6(JSON.parse(JSON.stringify(t.slots)), { id: t.id, title: t.name })
}
function applyParty(samples) { builder.load6(samples, { title: builder.name }) }
function openSample(s) {
  const i = builder.slots.findIndex((x) => x?.pokemon === s.pokemon)
  const slot = i >= 0 ? i : Math.max(0, builder.firstEmpty())
  builder.setSlot(slot, JSON.parse(JSON.stringify(s)))
  router.push({ path: '/sample', query: { slot } })
}
</script>

<template>
  <div class="builder" :style="{ gridTemplateColumns: `minmax(0, 1fr) ${chatOpen ? '420px' : '56px'}` }">
    <div class="left">
      <div class="bar">
        <FormatToggle />
        <label class="name"><input v-model="builder.name" placeholder="파티 이름"><span>✎ 이름 편집</span></label>
        <el-dropdown trigger="click" @command="loadTeam">
          <button class="btn">불러오기 ▾</button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-if="!library.myTeams.length" disabled>저장된 내 파티가 없습니다</el-dropdown-item>
              <el-dropdown-item v-for="t in library.myTeams" :key="t.id" :command="t">
                {{ t.name }} <span class="dd-sub">{{ t.slots.filter(Boolean).length }}/6</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <button class="btn" @click="clearAll">비우기</button>
        <button class="btn fill" @click="save">저장</button>
      </div>

      <div class="slots">
        <template v-for="(s, i) in builder.slots" :key="i">
          <MemberCard v-if="s && members[i]" :member="members[i]" size="sm">
            <template #actions>
              <button class="sbtn" title="샘플 상세보기" @click="detailSample = s; detailOpen = true">상세</button>
              <button class="sbtn" title="샘플 제작에서 수정" @click="edit(i)">수정</button>
              <button class="sbtn del" title="슬롯에서 삭제" @click="builder.clearSlot(i)">삭제</button>
            </template>
          </MemberCard>
          <div v-else class="empty" @click="openPicker(i)">
            <span class="plus">+</span><span>포켓몬 추가</span><span class="mono">슬롯 {{ i + 1 }}</span>
          </div>
        </template>
      </div>

      <div class="summary">
        <div class="sh"><strong>파티 요약 · 약점표</strong></div>
        <WeaknessTable v-if="weakRows.length" :rows="weakRows" compact :show-sum="false" />
        <p v-else class="muted">포켓몬을 추가하면 약점표가 나옵니다</p>
      </div>
    </div>

    <CoachChat v-model:open="chatOpen" :format-label="settings.formatLabel()" :ruleset-label="settings.rulesetLabel"
               :names="names" @apply="applyParty" @open-sample="openSample" />

    <SampleDetailDialog v-model:open="detailOpen" :sample="detailSample" title="파티 빌딩" />
    <PokemonPicker v-model:open="pickerOpen" :slot="pickerSlot" :list="pickList" :format-label="settings.formatLabel()" :format="settings.format"
                   :in-party="builder.slots.filter(Boolean).map((s) => s.pokemon)" :samples="mySamples"
                   @pick="onPick" @pick-sample="onPickSample" />
  </div>
</template>

<style scoped>
/* 스크롤은 창 하나만: 왼쪽은 창과 같이 스크롤, 채팅 패널은 화면에 고정(CoachChat의 sticky) */
.builder { display: grid; align-items: start; min-height: calc(100vh - 64px); transition: grid-template-columns .2s; }
.left { padding: 32px; display: flex; flex-direction: column; gap: 24px; min-width: 0; }
.bar { display: flex; align-items: center; gap: 10px; }
.name { flex: 1; height: 40px; border: 1px solid var(--c-line-strong); border-radius: 6px; display: flex; align-items: center; padding: 0 14px; }
.name input { flex: 1; border: 0; outline: 0; font-size: 15px; font-weight: 600; min-width: 0; }
.name span { font-size: 13px; color: var(--c-faint); margin-left: 8px; white-space: nowrap; }
.btn { height: 40px; padding: 0 16px; border: 1px solid var(--c-line-strong); background: #fff; border-radius: 6px; font-size: 13px; white-space: nowrap; }
.btn.fill { border: 0; background: var(--c-primary); color: #fbfbf9; font-weight: 600; padding: 0 20px; }
.dd-sub { margin-left: 8px; font-size: 11px; color: var(--c-muted); }
.slots { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.sbtn { height: 26px; padding: 0 8px; border: 1px solid var(--c-line-strong); border-radius: 4px; background: #fff; font-size: 11px; white-space: nowrap; }
.sbtn:hover { border-color: var(--c-primary); color: var(--c-primary); }
.sbtn.del { color: var(--c-danger); }
.sbtn.del:hover { border-color: var(--c-danger); }
.empty { border: 1.5px dashed var(--c-line-strong); border-radius: 10px; min-height: 236px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: #8a8882; cursor: pointer; font-size: 13px; }
.empty:hover { background: var(--c-hover); border-color: var(--c-primary); color: var(--c-primary); }
.plus { font-size: 28px; line-height: 1; }
.empty .mono { font-size: 11px; }
.summary { border-top: 1px solid var(--c-line); padding-top: 20px; display: flex; flex-direction: column; gap: 14px; }
.sh { display: flex; align-items: center; justify-content: space-between; }
.sh strong { font-size: 15px; }
.muted { color: var(--c-muted); font-size: 13px; margin: 0; }
</style>
