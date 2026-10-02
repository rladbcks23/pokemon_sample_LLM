<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { useBuilder } from '@/stores/builder'
import { useLibrary } from '@/stores/library'
import MemberCard from '@/components/MemberCard.vue'
import WeaknessTable from '@/components/WeaknessTable.vue'
import BackLink from '@/components/BackLink.vue'
import SampleDetailDialog from '@/components/SampleDetailDialog.vue'

const route = useRoute()
const router = useRouter()
const builder = useBuilder()
const library = useLibrary()

const t = ref(null)
const error = ref('')

watch(() => route.params.id, async (id) => {
  t.value = null
  error.value = ''
  try {
    t.value = await api.team(id)
  } catch (e) {
    error.value = e.message
  }
}, { immediate: true })

const fav = computed(() => t.value && library.isFavTeam(t.value.id))
const RESULT = { win: '승', lose: '패' }
const tags = computed(() => {
  const x = t.value
  const place = x.placement === 1 ? '우승' : x.placement === 2 ? '준우승' : x.placement ? `${x.placement}위` : ''
  return [x.source_label, x.format === 'singles' ? '싱글' : '더블', x.event, place, x.player, (x.date || '').replaceAll('-', '.'),
    x.rating ? `R ${x.rating}${x.result ? ' · ' + RESULT[x.result] : ''}` : null].filter(Boolean)
})
// 리플레이 멤버 SP를 같은 VGCPastes 팀에서 가져왔으면 그 팀 ID
const spFrom = computed(() => t.value.members.find((m) => m.sp_from)?.sp_from.replace('vgcpastes:', '') || '')
const weakRows = computed(() => t.value.members.map((m, i) => ({
  name: m.pokemon.name_ko, cells: t.value.weakness.rows[i].cells,
})))

// 목록 카드와 같은 요약 모양으로 찜 (마이페이지에서 다시 부르지 않고 표시)
function toggleFav() {
  const { members, weakness, ...summary } = t.value
  library.toggleFavTeam({ ...summary, members: members.map((m) => m.pokemon) })
}

// 멤버 → 샘플 모양 (메가 멤버는 메가 전 폼 + 메가스톤, 원래 특성)
const toSample = (m) => ({
  id: null, pokemon: m.base || m.pokemon.id, item: m.item?.id || '', ability: m.base_ability || m.ability?.id || '',
  nature: m.nature?.id || '', sp: { ...m.sp }, moves: [...m.moves.map((x) => x.id), '', '', '', ''].slice(0, 4),
})
const detailOpen = ref(false)
const detailSample = ref(null)

// 멤버 → 샘플로 바꿔서 파티 빌딩에 불러오기
function toBuilder() {
  const samples = t.value.members.map(toSample)
  builder.load6(samples, { title: t.value.title })
  router.push('/builder')
}
</script>

<template>
  <section v-if="error" class="page"><p class="err">{{ error }}</p></section>
  <section v-else-if="!t" class="page"><p class="muted">불러오는 중…</p></section>
  <section v-else class="page">
    <div class="crumbbar">
      <BackLink to="/teams" />
      <div class="crumb"><RouterLink to="/teams">파티 샘플</RouterLink> / {{ t.title }}</div>
    </div>
    <div class="head">
      <div class="hl">
        <h2>{{ t.title }}</h2>
        <div class="tags"><span v-for="tg in tags" :key="tg">{{ tg }}</span></div>
      </div>
      <div class="acts">
        <button class="heart" :class="{ on: fav }" @click="toggleFav">{{ fav ? '♥' : '♡' }} 찜</button>
        <button class="fill" @click="toBuilder">파티 빌딩에서 열기</button>
      </div>
    </div>

    <p v-if="spFrom" class="spnote">
      리플레이에는 SP가 공개되지 않아, 6마리 육성이 모두 같은 VGCPastes 대회 팀({{ spFrom }})의 SP를 넣었습니다.
    </p>
    <p v-else-if="t.source === 'showdown_replay'" class="spnote">리플레이에는 SP가 공개되지 않아 SP가 비어 있습니다.</p>
    <div class="members">
      <MemberCard v-for="m in t.members" :key="m.slot" :member="m" class="clickable" title="눌러서 상세보기"
                  @click="detailSample = toSample(m); detailOpen = true" />
    </div>

    <div class="weak">
      <div class="wh"><strong>파티 약점표</strong><span class="mono">18타입 × {{ t.members.length }}마리</span></div>
      <WeaknessTable :rows="weakRows" :show-sum="false" />
      <SampleDetailDialog v-model:open="detailOpen" :sample="detailSample" :title="t.title" />
    </div>
  </section>
</template>

<style scoped>
.page { padding: 32px 64px 56px; display: flex; flex-direction: column; gap: 28px; }
.muted { color: var(--c-muted); }
.err { color: var(--c-danger); }
.spnote { margin: -8px 0 0; font-size: 13px; color: var(--c-text-3); background: var(--c-primary-soft); border-radius: 6px; padding: 8px 12px; }
.crumbbar { display: flex; align-items: center; gap: 16px; }
.crumb { font-size: 13px; color: var(--c-muted); }
.crumb a { color: var(--c-primary); }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; }
.hl { display: flex; flex-direction: column; gap: 12px; }
.hl h2 { margin: 0; font-size: 28px; font-weight: 700; }
.tags { display: flex; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.tags span { border: 1px solid var(--c-line); border-radius: 12px; padding: 4px 10px; color: var(--c-text-2); }
.acts { display: flex; gap: 8px; flex: none; }
.heart { height: 40px; padding: 0 14px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; color: var(--c-muted); font-size: 13px; }
.heart.on { border-color: var(--c-heart); color: var(--c-heart); }
.fill { border: 0; background: var(--c-primary); color: #fbfbf9; border-radius: 6px; font-weight: 600; height: 40px; padding: 0 16px; font-size: 13px; }
.members { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.weak { display: flex; flex-direction: column; gap: 12px; }
.wh { display: flex; justify-content: space-between; align-items: center; }
.wh strong { font-size: 17px; }
.wh span { font-size: 12px; color: var(--c-muted); }
</style>
