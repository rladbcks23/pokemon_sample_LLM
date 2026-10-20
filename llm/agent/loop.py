"""에이전트 루프: 모델 호출 → 도구 실행 → 결과를 넣어 다시 호출, 모델이 도구를 그만 부를 때까지.

화면으로 보낼 이벤트를 차례로 내보낸다.
    ('status', 진행 상태) ('text', 답변 조각) ('party', 추천 파티 샘플 목록) ('error', 오류 문구)
"""
import json
import re
import logging

import httpx

import config
from agent import answers
from agent.prompt import SYSTEM, card_line, screen_context
from agent.tools import STATUS, TOOLS, ToolError, Tools

log = logging.getLogger(__name__)


def build_messages(history: list[dict], format: str, party: list, names: list[str] | None = None) -> list[dict]:
    """화면 대화 기록(텍스트만) → 모델 메시지. 마지막 사용자 메시지 앞에 화면 상황(멤버 한글 이름 포함)을 붙인다."""
    msgs = [{'role': h['role'], 'content': h['text'] + (card_line(h.get('party')) if h['role'] == 'assistant' else '')}
            for h in history if h.get('role') in ('user', 'assistant') and (h.get('text') or '').strip()]
    while msgs and msgs[0]['role'] != 'user':      # 첫 인사말(코치) 같은 앞쪽 assistant는 뺌
        msgs.pop(0)
    if not msgs or msgs[-1]['role'] != 'user':
        raise ValueError('마지막 메시지는 사용자 질문이어야 함')
    msgs[-1] = {'role': 'user', 'content': screen_context(format, party, names) + '\n\n' + msgs[-1]['content']}
    return msgs


def subject_of(history: list[dict], party: list, names: list[str] | None) -> str | None:
    """지금 이야기 중인 포켓몬 ID: 최근부터 보며, 코치가 1마리를 띄웠으면 그 포켓몬, 사용자가 화면 멤버 이름을 말했으면 그 멤버."""
    members = [m for m in party if m]
    for h in reversed(history):
        if h.get('role') == 'assistant' and len(h.get('party') or []) == 1:
            return h['party'][0].get('pokemon')
        if h.get('role') == 'user' and names:
            hit = [m['pokemon'] for m, n in zip(members, names) if n and n in (h.get('text') or '')]
            if len(hit) == 1:
                return hit[0]
    return None


SAMPLE_ASK = re.compile(r'샘플|형태|짜줘|추천|띄워|바꿔|바꾸|쓰고|주고|으로|로 해')


async def ensure_shown(tools: Tools, question: str, trace: list):
    """샘플을 찾아 달라는 흐름에서 검색 결과가 있는데 모델이 띄우지 않았으면 서버가 첫 샘플을 띄운다
    ("화면에 띄움"이 늘 사실이 되게)."""
    if any(n == 'propose_party' and isinstance(r, dict) and r.get('shown') for n, _, r in trace):
        return
    hit = next(((a, r) for n, a, r in reversed(trace) if n == 'search_samples'), None)
    if not hit:
        return
    args, found = hit
    # 도구·기술 조건을 붙여 찾은 샘플이면 그 조건의 샘플을 달라는 뜻
    asked = SAMPLE_ASK.search(question) or args.get('item') or args.get('without')
    if not (isinstance(found, dict) and found.get('samples') and asked):
        return
    args = {'members': [found['samples'][0]['sample']]}
    out = await tools.run('propose_party', args)
    trace.append(('propose_party', args, out))
    log.info('모델이 띄우지 않아 서버가 첫 샘플을 띄움: %s', args['members'][0].get('pokemon'))
    if tools.proposed:
        yield 'party', tools.proposed
        tools.proposed = None


async def run_agent(provider, tools: Tools, messages: list[dict]):
    # 로컬 모델(render_answers)은 도구 흐름으로 답을 알 수 있으면 서버가 도구 결과로 답을 쓴다 (agent/answers.py)
    render = getattr(provider, 'render_answers', False)
    question = messages[-1]['content'].split('\n\n')[-1] if isinstance(messages[-1]['content'], str) else ''
    trace = []                                      # [(도구, 인자, 결과)] 이번 턴에 성공한 호출
    for _ in range(config.MAX_TOOL_ROUNDS):
        final, said = None, []
        async for kind, value in provider.turn(SYSTEM, messages, TOOLS):
            if kind == 'text':
                if render:
                    said.append(value)
                else:
                    yield 'text', value
            else:
                final = value

        if final.stop_reason == 'refusal':
            yield 'error', '이 요청에는 답할 수 없습니다.'
            return
        uses = [b for b in final.content if b.type == 'tool_use']
        if not uses:
            if render:
                async for event in ensure_shown(tools, question, trace):
                    yield event
                text = answers.render(question, trace, tools.format)
                if text:
                    log.info('답변은 도구 결과로 작성 (모델 글 %d자 대신)', len(''.join(said)))
                yield 'text', text or ''.join(said)
            return
        if final.stop_reason == 'max_tokens':        # 잘린 도구 입력은 실행하지 않음
            yield 'error', '답변이 너무 길어 중간에 끊겼습니다.'
            return

        results = []
        for b in uses:
            yield 'status', STATUS.get(b.name, b.name)
            if render and b.name == 'search_samples' and getattr(tools, 'subject', None) \
                    and not await tools.pokemon_in(question):
                # "울퉁불퉁멧 형태"처럼 질문에 포켓몬 이름이 없으면 지금 이야기 중인 포켓몬 (모델이 도구 이름을 넣거나
                # 없는 이름을 지어내도). 포켓몬 자리에 도구 이름을 넣었으면 그건 도구 조건으로
                wrong = b.input.get('pokemon', '')
                item = b.input.get('item') or (wrong if await tools.item_id(wrong) else None)
                b.input = {**b.input, 'pokemon': tools.subject, **({'item': item} if item else {})}
            if render and b.name == 'search_samples' and not b.input.get('without'):
                without = await tools.moves_without(question)    # "빛의장막 리플렉터 없는 건"
                if without:
                    b.input = {**b.input, 'without': without}
            if render and b.name == 'search_samples' and not b.input.get('item'):
                item = await tools.item_in(question)    # 질문의 "울퉁불퉁멧 형태" 같은 도구 조건을 모델이 빠뜨리면 채움
                if item:
                    b.input = {**b.input, 'item': item}
            log.info('도구 %s %s', b.name, json.dumps(b.input, ensure_ascii=False)[:200])
            try:
                out = await tools.run(b.name, b.input)
                trace.append((b.name, b.input, out))
                results.append({'type': 'tool_result', 'tool_use_id': b.id,
                                'content': json.dumps(out, ensure_ascii=False, separators=(',', ':'))})
            except (ToolError, TypeError, ValueError) as e:        # 없는 ID, 잘못된 입력
                results.append({'type': 'tool_result', 'tool_use_id': b.id, 'is_error': True, 'content': str(e)})
            except httpx.HTTPError as e:
                log.warning('back API 오류: %s', e)
                results.append({'type': 'tool_result', 'tool_use_id': b.id, 'is_error': True,
                                'content': 'back API에 접속할 수 없음 (데이터 조회 실패)'})
            if b.name == 'propose_party' and tools.proposed:
                yield 'party', tools.proposed
                tools.proposed = None
        # 도구 결과는 한 사용자 메시지에 모아서 (병렬 호출 유지)
        messages.append({'role': 'assistant', 'content': final.content})
        messages.append({'role': 'user', 'content': results})
    text = render and answers.render(question, trace, tools.format)
    if text:                                        # 도구를 너무 많이 불러도 이미 띄운 파티 등이 있으면 그걸로 답
        yield 'text', text
        return
    yield 'error', '도구 호출이 너무 많아 멈췄습니다. 질문을 나눠서 다시 물어봐 주세요.'
