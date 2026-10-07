"""학습과 Colab 채팅에서 공통으로 쓰는, 사실을 버리지 않는 짧은 입력 표현.

도구 호출 정답은 실제 API 형식 그대로 둔다. 입력에 반복되는 육성형만 참조로
표시하고 모든 참조의 원문을 함께 제공한다. 도구 목록은 전체를 항상 제공한다.
"""
import copy
import json
import re


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def system_prompt(system, tools):
    # 원래 프롬프트의 동작 규칙을 Colab용으로 요약한다. 서버 프롬프트는 수정하지 않는다.
    def typename(p):
        if p.get('enum'):
            return '|'.join(p['enum'])
        if p.get('type') == 'array':
            return typename(p['items']) + '[]'
        if p.get('type') == 'object' and 'pokemon' in p.get('properties', {}):
            return 'SAMPLE' if 'moves' in p['properties'] else '{pokemon:string,item?:string}'
        return p.get('type', 'object')
    lines = []
    for t in tools:
        schema = t['input_schema']
        params = ','.join(k + ('' if k in schema.get('required', []) else '?') + ':' + typename(v)
                          for k, v in schema.get('properties', {}).items())
        lines.append(f"{t['name']}({params})")
    return '''포켓몬 챔피언스 M-C 파티 코치. 한국어로 결론·근거·장단점을 짧게, 마크다운 없이 답한다.
사실·수치·ID는 조회 결과만 사용. 이름의 ID가 없으면 search_pokemon. 승률·대미지·최선은 단정하지 않는다.
고정 멤버·제외 조건을 지킨다. 포켓몬·도구 중복 금지. Lv50, 무보정 성격 serious.
메가는 기본 폼+메가스톤. 배틀당 한 번, 메가 3마리 이상이면 선출 제한을 알린다.
역할은 SP·기술 기준: 공격/특공/속도는 딜러, 내구 투자 딜러는 내구조정, 랭크업기는 스위퍼,
벽·스텔스록·순풍·배턴은 기점잡이, 더블은 속이기·날따름·트릭룸 등 서포터, 내구 위주는 막이.
shapes의 10% 이상 형태를 우선. 공격 SP만 투자하고 해당 공격기가 없는 샘플은 제외.
컨셉을 모르면 묻거나 균형. 컨셉 파티는 컨셉 유지·대가 설명. 파티 판단은 check_party,
약점 받는 후보가 없으면 한계를 알린다. 실제 샘플 우선, 직접 만들면 validate_set.
추천은 propose_party로 전체 파티를 표시. 채팅은 이름 @ 도구 (SP)·짧은 장단점만.
''' + '\n'.join(lines) + '''
?가 붙은 인자만 선택 사항. format 생략 시 현재 화면의 포맷.
SAMPLE={pokemon:string,item:string,ability:string,nature:string,sp:object,moves:string[]}.
모든 SAMPLE 필드는 필수, 영문 ID, SP 각 0~32·합 66, 기술 4개. 메가는 기본 폼+메가스톤.
search_samples에는 pokemon이 반드시 필요하다. role에는 역할만 넣는다.
전체 파티 요청은 search_teams 또는 컨셉 질문. get_team으로 육성형을 확인한다.
조회 오류는 샘플이 없다는 뜻이 아니다. 조회되지 않은 이름·추천 근거를 만들지 않는다.
[육성형 원문]의 sample_ref는 입력의 반복을 줄인 참조다. 호출할 때는 원문의 전체 필드를 복원한다.
도구 호출은 다음 형식으로 출력한다. 인자 값이 배열/객체면 JSON으로 쓴다.
<tool_call>
<function=도구이름>
<parameter=인자이름>값</parameter>
</function>
</tool_call>
도구를 호출할 때 임의의 도구 이름이나 필드 이름을 만들지 않는다. 최종 답변은 짧은 한국어.
'''


def prepare_messages(messages, system):
    """매 생성 직전에 사용. 질문·후속 대화·도구 결과의 값은 자르지 않는다."""
    samples, keys = {}, {}

    def pack(value):
        if isinstance(value, dict):
            if all(k in value for k in ('pokemon', 'item', 'ability', 'nature', 'sp', 'moves')):
                # 기술 순서까지 같아야 같은 원문으로 압축한다.
                key = dumps(value)
                if key not in keys:
                    ref = 's' + str(len(keys) + 1)
                    keys[key] = ref
                    samples[ref] = value
                return {'sample_ref': keys[key]}
            return {k: pack(v) for k, v in value.items()}
        if isinstance(value, list):
            return [pack(v) for v in value]
        return value

    decoder = json.JSONDecoder()
    def content(text):
        # 화면에 표시된 JSON 육성형도 같은 참조 표를 사용한다.
        lines = []
        for line in (text or '').splitlines():
            match = re.match(r'^(\d+\. )(\{.*)$', line)
            if match:
                try:
                    obj, end = decoder.raw_decode(match[2])
                    line = match[1] + dumps(pack(obj)) + match[2][end:]
                except ValueError:
                    pass
            lines.append(line)
        return '\n'.join(lines)

    out, trace = [{'role': 'system', 'content': system}], []
    for m in messages:
        if m['role'] == 'system':
            continue
        if m.get('tool_calls'):
            trace.append({'calls': [pack(c['function']) for c in m['tool_calls']],
                          **({'text': m['content']} if m.get('content') else {})})
        elif m['role'] == 'tool':
            try:
                result = json.loads(m['content'])
            except (ValueError, TypeError):
                result = m['content']
            trace.append({'result': pack(result)})
        else:
            out.append({'role': m['role'], 'content': content(m.get('content'))})
    evidence = ''
    if samples:
        evidence += '\n\n[육성형 원문]\n' + dumps(samples)
    if trace:
        evidence += '\n\n[실제 도구 호출·조회 기록]\n' + dumps(trace)
    # 학습과 추론 모두 현재 질문 뒤에 같은 기록을 붙인다.
    out[-1]['content'] += evidence
    return out


def action_records(row, system):
    """각 assistant 행동을 별도 정답으로. 긴 전체 턴 하나만 탈락시키지 않는다."""
    last_user = max(i for i, m in enumerate(row['messages']) if m['role'] == 'user')
    for i, m in enumerate(row['messages']):
        if m['role'] == 'assistant' and i > last_user:
            yield {**{k: v for k, v in row.items() if k != 'messages'},
                   'id': row['id'] + f'-a{i}', 'source_turn_id': row['id'],
                   'messages': prepare_messages(row['messages'][:i], system) + [copy.deepcopy(m)]}


def mask_last_response(example, marker):
    """이미 토큰화된 자료에서 마지막 assistant 응답만 loss에 포함한다."""
    ids = example['input_ids']
    starts = [i for i in range(len(ids) - len(marker) + 1) if ids[i:i + len(marker)] == marker]
    if not starts:
        raise ValueError('assistant 시작 토큰을 찾지 못함. 템플릿/토크나이저 확인 필요')
    start = starts[-1] + len(marker)
    if start >= len(ids):
        raise ValueError('학습할 마지막 assistant 응답이 없음')
    return {'labels': [-100] * start + ids[start:]}
