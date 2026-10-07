"""에이전트 루프: 모델 호출 → 도구 실행 → 결과를 넣어 다시 호출, 모델이 도구를 그만 부를 때까지.

화면으로 보낼 이벤트를 차례로 내보낸다.
    ('status', 진행 상태) ('text', 답변 조각) ('party', 추천 파티 샘플 목록) ('error', 오류 문구)
"""
import json
import logging

import httpx

import config
from agent.prompt import SYSTEM, screen_context
from agent.tools import STATUS, TOOLS, ToolError, Tools

log = logging.getLogger(__name__)


def build_messages(history: list[dict], format: str, party: list) -> list[dict]:
    """화면 대화 기록(텍스트만) → 모델 메시지. 마지막 사용자 메시지 앞에 화면 상황을 붙인다."""
    msgs = [{'role': h['role'], 'content': h['text']} for h in history
            if h.get('role') in ('user', 'assistant') and (h.get('text') or '').strip()]
    while msgs and msgs[0]['role'] != 'user':      # 첫 인사말(코치) 같은 앞쪽 assistant는 뺌
        msgs.pop(0)
    if not msgs or msgs[-1]['role'] != 'user':
        raise ValueError('마지막 메시지는 사용자 질문이어야 함')
    msgs[-1] = {'role': 'user', 'content': screen_context(format, party) + '\n\n' + msgs[-1]['content']}
    return msgs


async def run_agent(provider, tools: Tools, messages: list[dict]):
    for _ in range(config.MAX_TOOL_ROUNDS):
        final = None
        async for kind, value in provider.turn(SYSTEM, messages, TOOLS):
            if kind == 'text':
                yield 'text', value
            else:
                final = value

        if final.stop_reason == 'refusal':
            yield 'error', '이 요청에는 답할 수 없습니다.'
            return
        uses = [b for b in final.content if b.type == 'tool_use']
        if not uses:
            return
        if final.stop_reason == 'max_tokens':        # 잘린 도구 입력은 실행하지 않음
            yield 'error', '답변이 너무 길어 중간에 끊겼습니다.'
            return

        results = []
        for b in uses:
            yield 'status', STATUS.get(b.name, b.name)
            try:
                out = await tools.run(b.name, b.input)
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
    yield 'error', '도구 호출이 너무 많아 멈췄습니다. 질문을 나눠서 다시 물어봐 주세요.'
