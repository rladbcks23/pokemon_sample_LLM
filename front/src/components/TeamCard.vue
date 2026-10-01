<script setup>
import { computed } from 'vue'
import { useLibrary } from '@/stores/library'
import PokemonImg from '@/components/PokemonImg.vue'

// 파티 카드: 이름, 출처, 6마리, 작성자·날짜, (리플레이) 레이팅·승패. 파티 조회·마이페이지 공용
const props = defineProps({
  team: { type: Object, required: true },   // API team_summary 모양
  heart: { type: Boolean, default: true },
})
const library = useLibrary()
const fav = computed(() => library.isFavTeam(props.team.id))
const date = computed(() => (props.team.date || '').replaceAll('-', '.'))
const RESULT = { win: '승', lose: '패' }
const placeText = (p) => (p === 1 ? '우승' : p === 2 ? '준우승' : `${p}위`)
</script>

<template>
  <div class="tcard">
    <div class="th">
      <strong>{{ team.title }}</strong>
      <span class="src">{{ team.source_label }}</span>
      <button v-if="heart" class="heart" :class="{ on: fav }" title="찜" @click.stop="library.toggleFavTeam(team)">
        {{ fav ? '♥' : '♡' }}
      </button>
    </div>
    <div class="mons">
      <div v-for="(m, i) in team.members" :key="i" class="mon">
        <PokemonImg :id="m.id" :size="56" />
        <span>{{ m.name_ko }}</span>
      </div>
    </div>
    <div class="tf">
      <span>{{ team.player || '—' }}</span><span>{{ date }}</span>
      <span v-if="team.event" class="ev">{{ team.event }}<template v-if="team.placement"> · {{ placeText(team.placement) }}</template></span>
      <span v-if="team.rating" class="rep mono">R {{ team.rating }}<template v-if="team.result"> · {{ RESULT[team.result] }}</template></span>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.tcard { border: 1px solid var(--c-line); border-radius: 12px; padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; cursor: pointer; background: #fff; }
.tcard:hover { border-color: var(--c-primary); }
.th { display: flex; align-items: center; gap: 10px; min-width: 0; }
.th strong { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.src { font-size: 11px; border: 1px solid var(--c-line); border-radius: 3px; padding: 1px 6px; color: var(--c-text-3); white-space: nowrap; }
.heart { margin-left: auto; flex: none; width: 34px; height: 34px; border: 1px solid var(--c-line-strong); border-radius: 17px; background: #fff; color: var(--c-muted); font-size: 16px; }
.heart.on { border-color: var(--c-heart); color: var(--c-heart); }
.mons { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
.mon { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 0; }
.mon span { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.tf { display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--c-muted); }
.ev { color: var(--c-text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.rep { margin-left: auto; color: var(--c-text); }
</style>
