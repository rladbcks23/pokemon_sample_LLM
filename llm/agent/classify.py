"""질문 → 의도 이름 하나 (로컬 모델, llama-server). 규칙(intents.parse)이 못 알아들은 질문만 여기로 온다.

학습 없이 예시만 보여 주고, 문법으로 의도 목록 밖의 답은 못 내게 한다.
포켓몬·도구·기술 이름은 여기서 뽑지 않는다 (서버가 DB 이름과 맞춰 찾음).
시험: training/build/intent_model_eval.py (규칙 59% / 모델 68% / 섞기 76%, 64문항)
"""
import json
import logging

import httpx

import config

log = logging.getLogger('coach')

LABELS = ['sample', 'party', 'fill', 'weakness', 'threats', 'mega', 'improve', 'item_usage',
          'review', 'cant', 'off_topic', 'unclear', 'who']

SYSTEM = """너는 포켓몬 챔피언스 파티 빌더의 질문 분류기다. 사용자의 마지막 질문을 아래 의도 중 하나로 분류해 JSON만 낸다.
- sample: 특정 포켓몬의 샘플·육성·기술·SP·성격·형태를 보여 달라 (도구·기술 조건 포함, "걔/얘"가 앞 대화 포켓몬이면 여기)
- party: 새 파티(팀)를 통째로 짜 달라 / 추천해 달라
- fill: 화면 파티의 빈자리를 채우거나 한 마리 더 넣을 포켓몬
- weakness: 화면 파티의 약점 타입·상성·타입 밸런스 (날씨로 약점이 줄어든다는 말도 여기)
- threats: 화면 파티가 만나면 힘든 상대 포켓몬·파티, 조심할 포켓몬, 카운터
- mega: 메가진화를 누구에게 쓸지, 메가스톤 개수
- improve: 화면 파티에서 뺄 멤버·바꿀 멤버·고칠 점·개선
- item_usage: 특정 포켓몬에게 어떤 도구(아이템)를 들릴지, 도구 사용률
- review: 특정 포켓몬의 지금 육성형(도구·기술·SP)이 맞는지, 이상하지 않은지 점검
- cant: 포켓몬 이야기지만 할 수 없는 것 (승률, 대미지 계산, 선출, 배틀 중 행동 예측)
- off_topic: 포켓몬 파티 빌딩과 상관없는 말
- unclear: 무슨 말인지 알 수 없음 (의미 없는 글자, 너무 짧음)
- who: "걔/얘/그거"라고 했는데 앞 대화에 가리킬 포켓몬이 없음"""

# (앞 대화, 질문, 의도). 시험 질문(intent_model_eval.TESTS)과 겹치지 않게
FEW_SHOT = [
    ('', '메가한카리아스Z 샘플 짜줘', 'sample'),
    ('사용자: 포푸니크 샘플 짜줘\n코치: 포푸니크 @ 기합의띠 추천 (화면에 띄움).', '울퉁불퉁멧 든 형태는?', 'sample'),
    ('', '더블 파티 하나 짜줘', 'party'),
    ('', '나머지 채워줘', 'fill'),
    ('', '이 파티 약점 알려줘', 'weakness'),
    ('', '이거 약점 찌르는 포켓몬 누가 있어?', 'threats'),
    ('', '메가 누구한테 써?', 'mega'),
    ('', '이 파티 고칠 점 있어?', 'improve'),
    ('', '깜까미 아이템 다른 거 주고 싶은데', 'item_usage'),
    ('사용자: 깜까미 샘플\n코치: 깜까미 @ 축축한바위 추천 (화면에 띄움).', '얘 기술 이렇게 쓰는 게 정상이야?', 'review'),
    ('', '이 파티 승률 몇 퍼야?', 'cant'),
    ('', '오늘 점심 뭐 먹지', 'off_topic'),
    ('', 'ㅁㄴㅇㄹ', 'unclear'),
    ('', '얘 샘플 보여줘', 'who'),
]

GRAMMAR = 'root ::= "{\\"intent\\":\\"" label "\\"}"\nlabel ::= ' + ' | '.join(f'"{x}"' for x in LABELS)


def history_text(history: list[dict], turns: int = 4) -> str:
    """앞 대화 최근 몇 줄 (답은 첫 줄만 짧게)."""
    lines = []
    for h in history[-turns:]:
        text = (h.get('text') or '').strip().split('\n')[0][:80]
        lines.append(f"{'사용자' if h.get('role') == 'user' else '코치'}: {text}")
    return '\n'.join(lines)


def user_text(hist: str, q: str, party_size: int = 6) -> str:
    return ((f'앞 대화:\n{hist}\n' if hist else '앞 대화: 없음\n') + f'화면 파티: {party_size}마리\n' + f'질문: {q}')


def prompt(hist: str, q: str, party_size: int = 6) -> str:
    turns = [f'<|im_start|>system\n{SYSTEM}<|im_end|>\n']
    for h, x, y in FEW_SHOT:
        turns.append(f'<|im_start|>user\n{user_text(h, x)}<|im_end|>\n<|im_start|>assistant\n{{"intent":"{y}"}}<|im_end|>\n')
    turns.append(f'<|im_start|>user\n{user_text(hist, q, party_size)}<|im_end|>\n<|im_start|>assistant\n')
    return ''.join(turns)


async def classify(question: str, history: list[dict], party_size: int = 6) -> str | None:
    """의도 이름. llama-server가 꺼져 있거나 실패하면 None (규칙 결과를 그대로 씀)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f'{config.QWEN_SERVER}/completion', json={
                'prompt': prompt(history_text(history), question, party_size), 'grammar': GRAMMAR,
                'n_predict': 20, 'temperature': 0, 'cache_prompt': True})
            r.raise_for_status()
            label = json.loads(r.json()['content'])['intent']
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.info('의도 모델 사용 안 함 (%s)', type(e).__name__)
        return None
    return label if label in LABELS else None
