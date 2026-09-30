<script setup>
import { nextTick, ref } from 'vue'
import PokemonImg from '@/components/PokemonImg.vue'

// 파티 코치 채팅 (오른쪽 패널). LLM 서버 연결 전이라 안내 메시지만 답함.
// 나중에 LLM 답변에 추천 파티(party: [샘플…])가 오면 카드와 "모두 추가하기"로 표시
const props = defineProps({
  open: Boolean,
  formatLabel: { type: String, default: '' },
  rulesetLabel: { type: String, default: '' },
  names: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:open', 'apply', 'open-sample'])

const CHIPS = ['이 파티 약점 알려줘', '메가 누구한테 써?', '선출 추천해줘']
const messages = ref([
  { role: 'bot', text: `${props.formatLabel} 배틀 · ${props.rulesetLabel} 레귤레이션 기준으로 도와드릴게요. 중심으로 쓰고 싶은 포켓몬이나 플레이 스타일을 알려주세요.` },
])
const draft = ref('')
const busy = ref(false)
const box = ref(null)

async function scroll() {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
}

async function ask(text) {
  const q = text.trim()
  if (!q || busy.value) return
  draft.value = ''
  busy.value = true
  messages.value.push({ role: 'user', text: q }, { role: 'status', text: '답변 준비 중…' })
  scroll()
  // TODO(LLM 단계): llm 서버 SSE 스트리밍 연결
  await new Promise((r) => setTimeout(r, 600))
  messages.value.splice(-1, 1, {
    role: 'bot',
    text: '파티 코치(LLM)는 아직 연결되지 않았습니다. LLM 서버를 붙이는 단계에서 이 창으로 파티 추천·진단·선출 가이드를 답하게 됩니다.',
  })
  busy.value = false
  scroll()
}
</script>

<template>
  <aside class="chat" :class="{ closed: !open }">
    <button v-if="!open" class="opener" title="파티 코치 열기" @click="emit('update:open', true)">
      <span>◀</span><span class="vt">파티 코치</span>
    </button>
    <div v-else class="inner">
      <div class="ch">
        <div><strong>파티 코치</strong><span>{{ formatLabel }} · {{ rulesetLabel }} 기준으로 답변</span></div>
        <div class="cr"><span class="muted">대화 목록 ▾</span><button class="fold" title="접기" @click="emit('update:open', false)">▶</button></div>
      </div>
      <div ref="box" class="msgs">
        <div v-for="(m, i) in messages" :key="i" class="m" :class="m.role">
          <div v-if="m.role === 'user'" class="bubble user">{{ m.text }}</div>
          <div v-else-if="m.role === 'status'" class="status mono">● {{ m.text }}</div>
          <div v-else class="botwrap">
            <div class="bubble bot">{{ m.text }}</div>
            <div v-if="m.party" class="rec">
              <div class="rh"><span class="mono">추천 파티 · {{ m.party.length }}마리</span><span>하나 누르면 샘플 제작으로 →</span></div>
              <div class="rm">
                <button v-for="(s, j) in m.party" :key="j" title="샘플 제작에서 열기" @click="emit('open-sample', s)">
                  <PokemonImg :id="s.pokemon" :size="40" /><span>{{ names[s.pokemon] || s.pokemon }}</span>
                </button>
              </div>
              <button class="apply" @click="emit('apply', m.party)">← 모두 추가하기</button>
            </div>
          </div>
        </div>
      </div>
      <div class="foot">
        <div class="chips"><button v-for="c in CHIPS" :key="c" @click="ask(c)">{{ c }}</button></div>
        <div class="input">
          <input v-model="draft" placeholder="파티에 대해 물어보세요" @keydown.enter="ask(draft)">
          <button :disabled="busy" @click="ask(draft)">전송</button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.chat { border-left: 1px solid var(--c-line); display: flex; flex-direction: column; min-height: 0; background: var(--c-hover); overflow: hidden; }
.opener { flex: 1; border: 0; background: none; display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 20px 0; font-size: 13px; color: var(--c-text); }
.opener:hover { background: #efeeea; }
.vt { writing-mode: vertical-rl; letter-spacing: 2px; font-weight: 600; }
.inner { display: flex; flex-direction: column; flex: 1; min-height: 0; width: 420px; }
.ch { padding: 18px 20px; border-bottom: 1px solid var(--c-line); display: flex; align-items: center; justify-content: space-between; }
.ch > div:first-child { display: flex; flex-direction: column; gap: 2px; }
.ch strong { font-size: 15px; }
.ch span { font-size: 12px; color: var(--c-muted); }
.cr { display: flex; align-items: center; gap: 10px; }
.fold { width: 30px; height: 30px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; font-size: 12px; }
.msgs { flex: 1; overflow: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.m { display: flex; }
.m.user { justify-content: flex-end; }
.bubble { font-size: 13px; line-height: 1.6; padding: 10px 14px; white-space: pre-wrap; }
.bubble.user { max-width: 80%; background: var(--c-primary); color: #fbfbf9; border-radius: 12px 12px 2px 12px; }
.botwrap { max-width: 92%; display: flex; flex-direction: column; gap: 10px; }
.bubble.bot { border: 1px solid var(--c-line); background: #fff; padding: 12px 14px; border-radius: 12px 12px 12px 2px; line-height: 1.65; }
.status { font-size: 12px; color: var(--c-muted); padding: 4px 0; }
.rec { border: 1px dashed var(--c-primary); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 10px; background: #fff; }
.rh { display: flex; justify-content: space-between; font-size: 11px; color: var(--c-muted); }
.rm { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.rm button { border: 1px solid transparent; background: none; border-radius: 6px; padding: 4px 0; display: flex; flex-direction: column; align-items: center; gap: 4px; color: inherit; }
.rm button:hover { border-color: var(--c-text); background: #f4f3ef; }
.rm span { font-size: 10px; white-space: nowrap; }
.apply { height: 34px; border: 0; border-radius: 6px; background: var(--c-primary); color: #fbfbf9; font-size: 13px; font-weight: 600; }
.foot { padding: 14px 20px 20px; border-top: 1px solid var(--c-line); display: flex; flex-direction: column; gap: 10px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chips button { height: 28px; padding: 0 10px; border: 1px solid var(--c-line-strong); border-radius: 14px; background: #fff; font-size: 12px; }
.chips button:hover { border-color: var(--c-text); }
.input { display: flex; gap: 8px; }
.input input { flex: 1; height: 42px; border: 1px solid var(--c-line-strong); border-radius: 6px; padding: 0 12px; font-size: 13px; background: #fff; }
.input button { height: 42px; padding: 0 16px; border: 0; border-radius: 6px; background: var(--c-primary); color: #fbfbf9; font-size: 13px; }
.input button:disabled { background: #b9c6e6; }
.muted { color: var(--c-muted); font-size: 12px; }
</style>
