import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { migrateSample } from '@/utils/pokemon'

// 파티 빌딩에서 편집 중인 파티. 샘플 제작 페이지를 다녀와도 유지되도록 localStorage에 둠
const KEY = 'pb-builder-v1'
const EMPTY = () => [null, null, null, null, null, null]

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {}
  } catch {
    return {}
  }
}

export const useBuilder = defineStore('builder', () => {
  const s = load()
  const teamId = ref(s.teamId || null)      // 내 파티를 불러와 편집 중이면 그 id
  const name = ref(s.name || '새 파티')
  const slots = ref((s.slots || EMPTY()).map(migrateSample))     // sample | null

  watch([teamId, name, slots], () => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ teamId: teamId.value, name: name.value, slots: slots.value }))
    } catch { /* 저장 불가 환경 */ }
  }, { deep: true })

  const count = computed(() => slots.value.filter(Boolean).length)
  const firstEmpty = () => slots.value.findIndex((x) => !x)

  function setSlot(i, sample) { slots.value.splice(i, 1, sample) }
  function clearSlot(i) { slots.value.splice(i, 1, null) }
  function reset() { teamId.value = null; name.value = '새 파티'; slots.value = EMPTY() }
  function load6(samples, { id = null, title = '새 파티' } = {}) {
    teamId.value = id
    name.value = title
    slots.value = [...samples, ...EMPTY()].slice(0, 6)
  }

  return { teamId, name, slots, count, firstEmpty, setSlot, clearSlot, reset, load6 }
})
