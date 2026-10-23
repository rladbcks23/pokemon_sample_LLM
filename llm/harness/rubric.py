"""설명문 평가 기준 (DESCRIPTION_RUBRIC.md v3): 1차 자동 검사, 2차 감점표·100점 계산.

DB 없이 돈다 (테스트용). 이름 목록은 호출하는 쪽이 넘긴다.
"""
import re
from difflib import SequenceMatcher

RUBRIC_VERSION = 'v3'
PASS_TOTAL = 80
REWRITE_BELOW = 70          # 이보다 낮으면 고쳐 쓰기 대신 새로 쓰기
MAX_NA = 2                  # N/A가 이보다 많으면 사람 검수

# 항목: (이름, 만점, 최소점수)
ITEMS = {
    'sample': {'J1': ('게임 정확성', 20, 18), 'J2': ('역할 일치', 15, 13), 'J3': ('"왜"가 있음', 15, 9),
               'S1': ('차별점', 12, 6), 'J4': ('한계·약점', 10, 5), 'J5': ('쓸모', 10, 5), 'J6': ('문체', 10, 6),
               'S2': ('형태 빈도', 8, 6)},
    'party': {'J1': ('게임 정확성', 20, 18), 'P1': ('컨셉', 12, 8), 'P2': ('멤버 연결', 12, 7), 'P3': ('위협·선출', 12, 6),
              'J2': ('역할 일치', 10, 8), 'J3': ('"왜"가 있음', 10, 6), 'J4': ('한계·약점', 8, 4), 'J5': ('쓸모', 8, 4),
              'J6': ('문체', 8, 5)},
}
NO_NA = {'J1', 'J2', 'J3'}

# 감점 규칙: ID → (사유, 샘플 기준 감점(None = 그 항목 전부), 건당인지). 파티 감점은 만점 비율로 줄인다
RULES = {
    'J1-a': ('기술·특성·도구 효과를 잘못 앎', 10, True),
    'J1-b': ('타입 상성을 틀림 (근거 묶음 약점과 다름)', 10, True),
    'J1-c': ('포맷 규칙 오해 (싱글에서 범위기 이득, 메가를 여러 번 등)', 5, True),
    'J1-d': ('틀리지는 않지만 효과를 과하게·애매하게 씀', 2, True),
    'J2-a': ('역할이 틀림 (파티면 멤버 1마리당)', None, True),
    'J2-b': ('역할 근거를 종족값만으로 씀', 4, False),
    'J2-c': ('세부 역할 빠짐 (내구조정·랭크업 딜러·물리/특수막이)', 2, False),
    'J3-a': ('구성 나열만 하고 이유가 하나도 없음', None, False),
    'J3-b': ('도구·SP·기술(파티면 멤버) 중 이유가 빠진 것', 4, True),
    'J3-c': ('이유가 근거 묶음과 연결되지 않는 일반론', 2, True),
    'J3-d': ('근거 묶음에 이유가 있는데 "이유를 모르겠다"고 씀', 4, True),
    'J4-a': ('한계·약점이 없음', None, False),
    'J4-b': ('근거 묶음에 없는 약점을 지어냄', None, False),
    'J4-c': ('막연함 ("상성 주의")', 5, False),
    'J4-d': ('대응 없이 약점만', 2, False),
    'J5-a': ('언제 꺼내는지 없음', 4, False),
    'J5-b': ('무엇을 먼저 하는지 없음', 3, False),
    'J5-c': ('어떤 샘플·파티에도 맞는 일반론만', 3, False),
    'J6-a': ('반말·명령조, 불평·비꼬기', 5, False),
    'J6-b': ('"~요" 체가 아님', 3, False),
    'J6-c': ('같은 말 반복, 군더더기 문장', 2, False),
    'J6-d': ('길이 상한의 80% 초과', 2, False),
    'J6-e': ('번역투·겹말·어색한 조사', 1, True),
    'S1-a': ('다른 샘플과의 차이를 말하지 않음', None, False),
    'S1-b': ('차이를 암시만 함', 6, False),
    'S1-c': ('차이를 틀리게 씀', None, False),
    'S2-a': ('드문 형태를 표준인 것처럼 씀', None, False),
    'S2-b': ('흔한 형태인데 빈도를 밝히지 않음', 2, False),
    'P1-a': ('컨셉이 없음', 8, False),
    'P1-b': ('컨셉이 check_party 밸런스와 어긋남', 6, False),
    'P1-c': ('축(메가·에이스)이 없음', 4, False),
    'P1-d': ('컨셉이 첫 문장에 없음', 2, False),
    'P2-a': ('연결이 하나도 없음 (멤버 나열만)', None, False),
    'P2-b': ('연결이 1개뿐', 5, False),
    'P2-c': ('잘못된 연결 (받아 준다는 멤버가 그 타입에 약점)', 6, True),
    'P3-a': ('위협·겹치는 약점을 말하지 않음', 6, False),
    'P3-b': ('위협에 대한 대응이 없음', 6, False),
    'P3-c': ('find_threats·겹치는 약점에 없는 위협', 6, True),
    'P3-d': ('위협을 3개 이상 나열', 2, False),
}


def rule_points(rule: str, kind: str) -> int:
    item = rule.split('-')[0]
    _, pts, _ = RULES[rule]
    full = ITEMS[kind][item][1]
    if rule == 'J2-a' and kind == 'party':
        return 5
    if pts is None:
        return full
    if kind == 'party' and item in ITEMS['sample']:
        return round(pts * full / ITEMS['sample'][item][1])
    return pts


def rules_for(kind: str) -> list[str]:
    return [r for r in RULES if r.split('-')[0] in ITEMS[kind]]


def rubric_text(kind: str) -> str:
    """심사 프롬프트에 넣을 감점표 (이 파일이 기준의 원본)."""
    lines = []
    for item, (name, full, low) in ITEMS[kind].items():
        lines.append(f'{item} {name} (만점 {full}, 최소 {low})')
        for r in rules_for(kind):
            if r.startswith(item + '-'):
                desc, _, each = RULES[r]
                lines.append(f'  {r}: {desc} → -{rule_points(r, kind)}{" (건당)" if each else ""}')
    return '\n'.join(lines)


def score(kind: str, deductions: list[dict], na: dict) -> dict:
    """감점 목록 → 항목 점수·합계(100점 환산)·통과."""
    items = ITEMS[kind]
    na = {k: v for k, v in (na or {}).items() if k in items and k not in NO_NA}
    used = {}
    pts = {k: full for k, (_, full, _) in items.items() if k not in na}
    for d in deductions:
        r = d.get('rule')
        if r not in RULES or r.split('-')[0] not in pts:
            continue
        if not RULES[r][2] and r in used:        # 건당이 아니면 한 번만
            continue
        used[r] = True
        item = r.split('-')[0]
        pts[item] = max(0, pts[item] - rule_points(r, kind))
    full_sum = sum(items[k][1] for k in pts)
    total = round(sum(pts.values()) * 100 / full_sum, 1) if full_sum else 0
    below = [k for k, v in pts.items() if v < items[k][2]]
    return {'items': pts, 'na': na, 'total': total, 'below_min': below,
            'pass': not below and total >= PASS_TOTAL and len(na) <= MAX_NA, 'too_many_na': len(na) > MAX_NA}


# ---------------------------------------------------------------- 1차 자동 검사

FOREIGN = re.compile(r'[^\x00-\x7F가-힣ㄱ-ㆎ·…—–→←×%\s]')
MARKDOWN = re.compile(r'\*\*|^\s*#|^\s*[-*•]\s|\|', re.M)
BANNED = ['최강', '무조건', '필수', '완벽', '절대', '카운터 없', '승률이 높', '승률']
TOOL_NAMES = ['check_party', 'find_partners', 'find_threats', 'search_samples', 'member_profile', 'party_check']
ROLE_WORDS = ['물리막이', '특수막이', '막이', '딜러', '기점잡이', '서포터']
LENGTH = {'sample': (60, 220, 2, 4), 'party': (120, 400, 3, 6)}
COUNT_UNIT = re.compile(r'^(마리|개|턴|번|가지)')


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


def _numbers(text: str):
    for m in re.finditer(r'\d+(?:\.\d+)?', text):
        yield m.group(), text[m.end():m.end() + 2]


def auto_check(kind: str, text: str, packet: dict, grounding: str, vocab: dict, derived=(), others=()) -> list[dict]:
    """실패 목록 [{'id': 'A1', 'msg': ...}]. 비어 있으면 통과.

    vocab: {'pokemon': [한글 이름…], 'move': […], 'item': […], 'ability': […]} (게임 전체 이름)
    others: 비교할 다른 설명 글 (같은 포켓몬 샘플 / 다른 파티)
    """
    fails = []

    def fail(i, msg):
        fails.append({'id': i, 'msg': msg})

    # A1 숫자: 근거 묶음에 없는 숫자 (1~6마리·개처럼 셈하는 말은 허용)
    have = set(re.findall(r'\d+(?:\.\d+)?', grounding)) | {str(x) for x in derived}
    bad = [n for n, after in _numbers(text) if n not in have and not (int(float(n)) <= 6 and COUNT_UNIT.match(after))]
    if bad:
        fail('A1', f'근거 없는 숫자: {", ".join(dict.fromkeys(bad))}')
    # A2·A3 이름: 게임에 있는 이름인데 근거 묶음에 없는 것
    for kind_, aid in (('pokemon', 'A2'), ('move', 'A3'), ('item', 'A3'), ('ability', 'A3')):
        words = sorted((w for w in vocab.get(kind_, []) if len(w) >= 2), key=len, reverse=True)
        if not words:
            continue
        found = set(re.findall('|'.join(map(re.escape, words)), text))
        miss = [w for w in found if w not in grounding]
        if miss:
            fail(aid, f'근거 묶음에 없는 {"포켓몬" if kind_ == "pokemon" else "기술·도구·특성"}: {", ".join(sorted(miss))}')
    # A4 역할: 샘플 첫 문장의 역할 말이 판정과 다름
    if kind == 'sample':
        first = sentences(text)[0] if sentences(text) else ''
        said = next((w for w in ROLE_WORDS if w in first), None)
        roles = ' '.join(packet.get('roles', []))
        if said and said not in roles and not (said == '막이' and '막이' in roles):
            fail('A4', f'첫 문장 역할 "{said}"가 판정 역할({roles})과 다름')
    # A5 포맷 용어
    if packet.get('format') == '더블' and '기점잡이' in text:
        fail('A5', '더블 설명에 "기점잡이" (더블은 서포터)')
    # A6 출처
    src = packet.get('source', '')
    if '리플레이' in text:
        fail('A6', '리플레이를 근거로 씀')
    if '대회' in text and '대회' not in src and 'VGC' not in src:
        fail('A6', f'출처는 {src}인데 "대회"라고 씀')
    if 'OP.GG' in text and 'OP.GG' not in src:
        fail('A6', f'출처는 {src}인데 "OP.GG"라고 씀')
    # A7 글자
    if f := FOREIGN.findall(text):
        fail('A7', f'외국 글자·이모지: {"".join(dict.fromkeys(f))}')
    if MARKDOWN.search(text):
        fail('A7', '마크다운(굵게·제목·글머리표·표)')
    if t := [n for n in TOOL_NAMES if n in text]:
        fail('A7', f'도구 이름: {", ".join(t)}')
    # A8 길이
    lo, hi, slo, shi = LENGTH[kind]
    n_sent = len(sentences(text))
    if not lo <= len(text) <= hi:
        fail('A8', f'길이 {len(text)}자 ({lo}~{hi}자)')
    if not slo <= n_sent <= shi:
        fail('A8', f'문장 {n_sent}개 ({slo}~{shi}개)')
    # A9 단정·과장
    if b := [w for w in BANNED if w in text]:
        fail('A9', f'단정·과장: {", ".join(dict.fromkeys(b))}')
    # A10 중복: 다른 설명과 거의 같은 문장
    for s in sentences(text):
        if len(s) < 15:
            continue
        for o in others:
            if any(SequenceMatcher(None, s, x).ratio() >= 0.8 for x in sentences(o)):
                fail('A10', f'다른 설명과 거의 같은 문장: "{s}"')
                break
    # A11 메가
    if kind == 'sample':
        base = (packet.get('pokemon') or {}).get('mega_from')
        if base and re.search(rf'(?<!메가){re.escape(base)}', text):
            fail('A11', f'메가 폼을 메가 전 이름 "{base}"로 부름')
    else:
        if packet.get('mega_stones', 0) >= 3 and '선출' not in text:
            fail('A11', f'메가스톤 {packet["mega_stones"]}개인데 선출 제한 언급 없음')
        if re.search(r'메가.{0,6}(2마리|두 마리|둘).{0,8}(같이|동시)', text):
            fail('A11', '메가 2마리 동시 선출을 권함')
    return fails
