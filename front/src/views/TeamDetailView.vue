<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { useBuilder } from '@/stores/builder'
import { useLibrary } from '@/stores/library'
import MemberCard from '@/components/MemberCard.vue'
import WeaknessTable from '@/components/WeaknessTable.vue'

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
  return [x.source_label, x.format === 'singles' ? '싱글' : '더블', x.player, (x.date || '').replaceAll('-', '.'),
    x.rating ? `R ${x.rating}${x.result ? ' · ' + RESULT[x.result] : ''}` : null].filter(Boolean)
})
const weakRows = computed(() => t.value.members.map((m, i) => ({
  name: m.pokemon.name_ko, cells: t.value.weakness.rows[i].cells,
})))

// 목록 카드와 같은 요약 모양으로 찜 (마이페이지에서 다시 부르지 않고 표시)
function toggleFav() {
  const { members, weakness, ...summary } = t.value
  library.toggleFavTeam({ ...summary, members: members.map((m) => m.pokemon) })
}

// 멤버 → 샘플로 바꿔서 파티 빌딩에 불러오기
function toBuilder() {
  const samples = t.value.members.map((m) => ({
    id: null, pokemon: m.pokemon.id, item: m.item?.id || '', ability: m.ability?.id || '',
    nature: m.nature?.id || '', sp: { ...m.sp }, moves: [...m.moves.map((x) => x.id), '', '', '', ''].slice(0, 4),
  }))
  builder.load6(samples, { title: t.value.title })
  router.push('/builder')
}
</script>

<template>
  <section v-if="error" class="page"><p class="err">{{ error }}</p></section>
  <section v-else-if="!t" class="page"><p class="muted">불러오는 중…</p></section>
  <section v-else class="page">
    <div class="crumb"><RouterLink to="/teams">파티</RouterLink> / {{ t.title }}</div>
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

    <div class="members">
      <MemberCard v-for="m in t.members" :key="m.slot" :member="m" />
    </div>

    <div class="weak">
      <div class="wh"><strong>파티 약점표</strong><span class="mono">18타입 × {{ t.members.length }}마리</span></div>
      <WeaknessTable :rows="weakRows" :show-sum="false" />
    </div>
  </section>
</template>

<style scoped>
.page { padding: 32px 64px 56px; display: flex; flex-direction: column; gap: 28px; }
.muted { color: var(--c-muted); }
.err { color: var(--c-danger); }
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
