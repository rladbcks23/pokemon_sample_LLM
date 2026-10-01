<script setup>
import { TYPE_COLOR, TYPE_KO, spText } from '@/utils/pokemon'
import PokemonImg from '@/components/PokemonImg.vue'
import TypeBadge from '@/components/TypeBadge.vue'
import ItemIcon from '@/components/ItemIcon.vue'

// 멤버(육성형) 카드: 파티 상세·파티 빌딩·마이페이지 공용
// member: { pokemon: {id, name_ko, types}, item: {id, name_ko}, ability: {name_ko}, nature: {name_ko},
//           sp: {...}, moves: [{name_ko, type}], is_mega, lead, brought }
defineProps({
  member: { type: Object, required: true },
  size: { type: String, default: 'md' },   // md(파티 상세) / sm(파티 빌딩 슬롯)
})
</script>

<template>
  <div class="mcard" :class="size">
    <div class="top">
      <PokemonImg :id="member.pokemon.id" :size="size === 'sm' ? 56 : 64" />
      <div class="who">
        <div class="nm"><strong :title="member.pokemon.name_ko">{{ member.pokemon.name_ko }}</strong><span v-if="member.is_mega" class="mega mono">MEGA</span></div>
        <div class="types"><TypeBadge v-for="t in member.pokemon.types" :key="t" :type="t" :width="52" /></div>
      </div>
      <!-- md: 특성·성격·SP를 이름 오른쪽에 -->
      <div v-if="size !== 'sm'" class="right">
        <span><small>특성</small>{{ member.ability?.name_ko || '—' }}</span>
        <span><small>성격</small>{{ member.nature?.name_ko || '—' }}</span>
        <span class="mono">{{ spText(member.sp) }}</span>
      </div>
      <div class="side">
        <slot name="actions">
          <span v-if="member.lead" class="tag lead">선봉</span>
          <span v-else-if="member.brought" class="tag">출전</span>
        </slot>
      </div>
    </div>
    <div class="info">
      <div class="item"><ItemIcon :id="member.item?.id" :size="size === 'sm' ? 18 : 24" />{{ member.item?.name_ko || '도구 없음' }}</div>
      <template v-if="size === 'sm'">
        <div class="an">{{ member.ability?.name_ko || '특성 —' }} · {{ member.nature?.name_ko || '성격 —' }}</div>
        <div class="sp mono">SP {{ spText(member.sp) }}</div>
      </template>
    </div>
    <div class="moves">
      <div v-for="(mv, i) in member.moves" :key="i" class="mv">
        <span class="dot" :style="{ background: TYPE_COLOR[mv?.type] || '#8a8882' }" />
        <span class="mn">{{ mv?.name_ko || '—' }}</span>
        <span v-if="size !== 'sm' && mv?.type" class="mt">{{ TYPE_KO[mv.type] }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mcard { border: 1px solid var(--c-line-card); border-radius: 10px; padding: 18px; display: flex; flex-direction: column; gap: 12px; background: #fff; }
.mcard.clickable { cursor: pointer; transition: border-color .15s; }
.mcard.clickable:hover { border-color: var(--c-primary); }
.mcard.sm { padding: 16px; min-height: 236px; }
.top { display: flex; gap: 12px; align-items: center; }
.who { display: flex; flex-direction: column; gap: 6px; min-width: 0; flex: 1; }
.nm { display: flex; align-items: center; gap: 6px; min-width: 0; }
.nm strong { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mega { flex: none; }
.sm .nm strong { font-size: 15px; }
.mega { font-size: 10px; border: 1px solid var(--c-text); border-radius: 3px; padding: 1px 5px; }
.types { display: flex; gap: 4px; }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; font-size: 12px; color: var(--c-text-2, var(--c-text)); text-align: right; flex: none; max-width: 48%; }
.right span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.right small { font-size: 10px; color: var(--c-muted); margin-right: 6px; }
.right .mono { font-size: 11px; color: var(--c-text-3); }
.side:empty { display: none; }
.side { margin-left: auto; align-self: flex-start; display: flex; gap: 4px; flex: none; }
.tag { font-size: 10px; border: 1px solid var(--c-line-strong); border-radius: 3px; padding: 1px 6px; color: var(--c-text-3); }
.tag.lead { border-color: var(--c-primary); color: var(--c-primary); }
.info { display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
.sm .info { gap: 5px; }
.item { display: flex; align-items: center; gap: 8px; }
.an { color: var(--c-text-3); }
.sp { font-size: 11px; color: var(--c-text-3); }
.moves { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px; }
.mv { display: flex; align-items: center; gap: 6px; border: 1px solid var(--c-line-soft); border-radius: 4px; padding: 5px 8px; font-size: 12px; min-width: 0; }
.sm .mv { padding: 4px 6px; font-size: 11px; gap: 5px; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.mn { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mt { margin-left: auto; font-size: 10px; color: var(--c-muted); white-space: nowrap; }
</style>
