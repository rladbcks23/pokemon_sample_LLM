import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { chatStream } from '@/api'

// 파티 코치 대화. 페이지를 나갔다 와도 남고 답변도 계속 받도록 화면이 아니라 store에 두고 localStorage에 저장
const KEY = 'pb-coach-v1'

function load() {
  try {
    // 답변 도중 새로고침했으면 빈 답변은 버림
    return (JSON.parse(localStorage.getItem(KEY)) || []).filter((m) => m.role !== 'status' && (m.text || m.party))
  } catch {
    return []
  }
}

export const useCoach = defineStore('coach', () => {
  const messages = ref(load())        // {role: 'user'|'bot'|'status', text, party?}
  const busy = ref(false)

  watch(messages, () => {
    try {
      localStorage.setItem(KEY, JSON.stringify(messages.value.filter((m) => m.role !== 'status')))
    } catch { /* 저장 불가 환경 */ }
  }, { deep: true })

  async function ask(q, format, party, onUpdate = () => {}) {
    if (!q || busy.value) return
    busy.value = true
    messages.value.push({ role: 'user', text: q })
    const history = messages.value.filter((m) => m.role !== 'status' && m.text)
      .map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', text: m.text }))
    messages.value.push({ role: 'status', text: '답변 준비 중…' }, { role: 'bot', text: '' })
    const status = messages.value[messages.value.length - 2]
    const bot = messages.value[messages.value.length - 1]
    onUpdate()
    try {
      await chatStream({ history, format, party: JSON.parse(JSON.stringify(party)) }, (event, data) => {
        if (event === 'status') status.text = `${data.text}…`
        else if (event === 'text') bot.text += data.delta
        else if (event === 'party') bot.party = data.members
        else if (event === 'error') bot.text += `${bot.text ? '\n\n' : ''}⚠ ${data.message}`
        onUpdate()
      })
    } catch {
      bot.text = '파티 코치 서버(llm)에 연결하지 못했습니다. llm 서버가 켜져 있는지 확인해 주세요.'
    }
    messages.value.splice(messages.value.indexOf(status), 1)
    if (!bot.text && !bot.party) bot.text = '답변을 받지 못했습니다.'
    busy.value = false
    onUpdate()
  }

  function reset() {
    if (!busy.value) messages.value = []
  }

  return { messages, busy, ask, reset }
})
