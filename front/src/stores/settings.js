import { defineStore } from 'pinia'
import { ref } from 'vue'

// 싱글/더블 전환(페이지마다 FormatToggle), 레귤레이션 (현재는 M-C 하나)
// 싱글/더블은 저장하지 않음 → 새로 열면 항상 싱글
export const useSettings = defineStore('settings', () => {
  const format = ref('singles')
  const ruleset = ref('champions_mc')
  const rulesetLabel = 'M-C'

  const formatLabel = (f = format.value) => (f === 'singles' ? '싱글' : '더블')
  return { format, ruleset, rulesetLabel, formatLabel }
})
