import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const KEY = 'pb-settings'

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {}
  } catch {
    return {}
  }
}

// 상단의 싱글/더블 전환, 레귤레이션 (현재는 M-C 하나)
export const useSettings = defineStore('settings', () => {
  const saved = load()
  const format = ref(saved.format || 'doubles')
  const ruleset = ref('champions_mc')
  const rulesetLabel = 'M-C'

  watch(format, (v) => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ format: v }))
    } catch { /* 저장 불가 환경에서는 무시 */ }
  })

  const formatLabel = (f = format.value) => (f === 'singles' ? '싱글' : '더블')
  return { format, ruleset, rulesetLabel, formatLabel }
})
