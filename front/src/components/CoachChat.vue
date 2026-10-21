<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useCoach } from '@/stores/coach'
import PokemonImg from '@/components/PokemonImg.vue'

// 파티 코치 채팅 (오른쪽 패널). llm 서버(SSE)에 대화와 현재 파티를 보내고 답변을 이어 붙임.
// 답변에 추천 파티(party: [샘플…])가 오면 카드로 표시. 포켓몬마다 "넣기"(빈칸·같은 포켓몬 칸, 꽉 차면 바꿀 멤버 고르기),
// 여러 마리면 "이 파티로 전부 바꾸기"
const props = defineProps({
  open: Boolean,
  formatLabel: { type: String, default: '' },
  rulesetLabel: { type: String, default: '' },
  names: { type: Object, default: () => ({}) },
  format: { type: String, default: 'singles' },
  party: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:open', 'apply', 'open-sample', 'add'])

const CHIPS = ['이 파티 약점 알려줘', '메가 누구한테 써?', '이 파티 고칠 점 있어?']
const coach = useCoach()      // 대화는 store에 (페이지를 나갔다 와도 유지, 답변도 계속 받음)
// 첫 인사말은 저장하지 않고 화면에서만 (서버의 build_messages도 앞쪽 assistant는 뺌)
const messages = computed(() => [
  { role: 'bot', text: `${props.formatLabel} 배틀 · ${props.rulesetLabel} 레귤레이션 기준으로 도와드릴게요. 중심으로 쓰고 싶은 포켓몬이나 플레이 스타일을 알려주세요.` },
  ...coach.messages,
])
const draft = ref('')
const box = ref(null)

async function scroll() {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
}

function ask(text) {
  const q = text.trim()
  if (!q || coach.busy) return
  draft.value = ''
  coach.ask(q, props.format, props.party, scroll)
}

// 추천 카드의 포켓몬 하나 넣기: 같은 포켓몬이 있으면 그 칸, 없으면 빈칸, 꽉 찼으면 누구 대신 넣을지 고르게
const same = (a, b) => !!a && !!b && a.pokemon === b.pokemon && (a.item || '') === (b.item || '')
  && JSON.stringify(a.moves || []) === JSON.stringify(b.moves || [])
const inParty = (s) => props.party.some((x) => same(x, s))
const picking = ref(null)     // { i: 메시지 번호, s: 넣을 샘플 }
function add(i, s) {
  const k = props.party.findIndex((x) => x?.pokemon === s.pokemon)
  const slot = k >= 0 ? k : props.party.findIndex((x) => !x)
  if (slot >= 0) {
    picking.value = null
    emit('add', s, slot)
  } else {
    picking.value = { i, s }
  }
}
function replace(k) {
  emit('add', picking.value.s, k)
  picking.value = null
}

onMounted(scroll)
</script>

<template>
  <aside class="chat" :class="{ closed: !open }">
    <button v-if="!open" class="opener" title="파티 코치 열기" @click="emit('update:open', true)">
      <span>◀</span><span class="vt">파티 코치</span>
    </button>
    <div v-else class="inner">
      <div class="ch">
        <div><strong>파티 코치</strong><span>{{ formatLabel }} · {{ rulesetLabel }} 기준으로 답변</span></div>
        <div class="cr"><button class="new" :disabled="coach.busy || !coach.messages.length" @click="coach.reset()">새 대화</button><button class="fold" title="접기" @click="emit('update:open', false)">▶</button></div>
      </div>
      <div ref="box" class="msgs">
        <div v-for="(m, i) in messages" :key="i" class="m" :class="m.role">
          <div v-if="m.role === 'user'" class="bubble user">{{ m.text }}</div>
          <div v-else-if="m.role === 'status'" class="status mono">● {{ m.text }}</div>
          <div v-else class="botwrap">
            <div v-if="m.text" class="bubble bot">{{ m.text }}</div>
            <div v-if="m.party" class="rec">
              <div class="rh"><span class="mono">{{ m.party.length > 1 ? `추천 파티 · ${m.party.length}마리` : '추천 샘플' }}</span><span>그림: 상세보기 · 넣기: 파티에 추가</span></div>
              <div class="rm">
                <div v-for="(s, j) in m.party" :key="j" class="mem">
                  <button class="pk" title="상세보기" @click="emit('open-sample', s)">
                    <PokemonImg :id="s.pokemon" :size="40" /><span>{{ names[s.pokemon] || s.pokemon }}</span>
                  </button>
                  <span v-if="inParty(s)" class="have">파티에 있음</span>
                  <button v-else class="add" @click="add(i, s)">+ 넣기</button>
                </div>
              </div>
              <div v-if="picking && picking.i === i" class="swap">
                <span>파티가 꽉 찼어요. {{ names[picking.s.pokemon] || picking.s.pokemon }}, 누구 대신 넣을까요?</span>
                <div>
                  <button v-for="(x, k) in party" :key="k" @click="replace(k)">{{ x ? names[x.pokemon] || x.pokemon : `${k + 1}번 칸` }}</button>
                  <button class="cancel" @click="picking = null">취소</button>
                </div>
              </div>
              <button v-if="m.party.length > 1" class="apply" @click="emit('apply', m.party)">← 이 파티로 전부 바꾸기</button>
            </div>
          </div>
        </div>
      </div>
      <div class="foot">
        <div class="chips"><button v-for="c in CHIPS" :key="c" @click="ask(c)">{{ c }}</button></div>
        <div class="input">
          <input v-model="draft" placeholder="파티에 대해 물어보세요" @keydown.enter="ask(draft)">
          <button :disabled="coach.busy" @click="ask(draft)">전송</button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* 상단 메뉴(64px) 아래에 화면 높이만큼 고정. 메시지 목록만 안에서 스크롤 */
.chat { position: sticky; top: 64px; height: calc(100vh - 64px); border-left: 1px solid var(--c-line); display: flex; flex-direction: column; min-height: 0; background: var(--c-hover); overflow: hidden; }
.opener { flex: 1; border: 0; background: none; display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 20px 0; font-size: 13px; color: var(--c-text); }
.opener:hover { background: #efeeea; }
.vt { writing-mode: vertical-rl; letter-spacing: 2px; font-weight: 600; }
.inner { display: flex; flex-direction: column; flex: 1; min-height: 0; width: 420px; }
.ch { padding: 18px 20px; border-bottom: 1px solid var(--c-line); display: flex; align-items: center; justify-content: space-between; }
.ch > div:first-child { display: flex; flex-direction: column; gap: 2px; }
.ch strong { font-size: 15px; }
.ch span { font-size: 12px; color: var(--c-muted); }
.cr { display: flex; align-items: center; gap: 10px; }
.new { height: 30px; padding: 0 10px; border: 1px solid var(--c-line-strong); border-radius: 6px; background: #fff; font-size: 12px; }
.new:disabled { opacity: .5; }
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
.mem { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 0; }
.pk { width: 100%; border: 1px solid transparent; background: none; border-radius: 6px; padding: 4px 0; display: flex; flex-direction: column; align-items: center; gap: 4px; color: inherit; }
.pk:hover { border-color: var(--c-text); background: #f4f3ef; }
.pk span { font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.add { height: 22px; padding: 0 6px; border: 1px solid var(--c-primary); border-radius: 11px; background: #fff; color: var(--c-primary); font-size: 10px; white-space: nowrap; }
.add:hover { background: var(--c-primary); color: #fbfbf9; }
.have { height: 22px; line-height: 22px; font-size: 10px; color: var(--c-muted); white-space: nowrap; }
.swap { border-top: 1px solid var(--c-line); padding-top: 10px; display: flex; flex-direction: column; gap: 8px; font-size: 12px; }
.swap div { display: flex; flex-wrap: wrap; gap: 6px; }
.swap button { height: 26px; padding: 0 10px; border: 1px solid var(--c-line-strong); border-radius: 13px; background: #fff; font-size: 12px; }
.swap button:hover { border-color: var(--c-text); }
.swap .cancel { color: var(--c-muted); }
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
