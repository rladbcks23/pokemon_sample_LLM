"""DB 기반 코치 (llm/DESIGN.md): 질문 → 의도 JSON → 서버가 DB 조회·화면 띄우기·답 문장.

의도 JSON (영문 ID):
    {"intent": "sample", "pokemon": "sableye", "stone": null, "item": "rockyhelmet", "without": ["reflect"], "role": "막이"}
    {"intent": "party", "pokemon": "garchomp"}      pokemon 생략 가능
    {"intent": "fill"} {"intent": "weakness"} {"intent": "mega"} {"intent": "threats"}    화면 파티 대상
    {"intent": "item_usage", "pokemon": "sableye"}
    {"intent": "unknown", "reason": "unclear" | "off_topic" | "cant" | "who"}
    공통으로 "format": "singles" | "doubles" (질문에 있으면, 없으면 화면)

parse()는 지금은 규칙(DB 이름 맞추기 + 키워드)으로 만든다. 학습한 모델이 생기면 같은 JSON을 모델이 만든다.
대상: "얘·걔·그거"는 앞 대화, 지금 파티 대상 요청은 화면, 질문에 이름이 있으면 그 포켓몬.
"""
import re

from agent import answers
from agent.tools import ToolError, Tools

FORMAT_KO = {'singles': '싱글', 'doubles': '더블'}
POINTER = re.compile(r'얘|걔|쟤|그거|그놈|그 포켓몬|이 포켓몬')
ROLES = [('물리막이', '물리막이'), ('특수막이', '특수막이'), ('막이', '막이'), ('물리 딜러', '물리 딜러'),
         ('특수 딜러', '특수 딜러'), ('기점잡이', '기점잡이'), ('서포터', '서포터'), ('스위퍼', '랭크업 딜러'),
         ('랭크업', '랭크업 딜러')]
DOMAIN = re.compile(r'포켓몬|파티|샘플|육성|기술|도구|아이템|템|특성|성격|싱글|더블|메가|약점|상성|추천|짜')
UNKNOWN_TEXT = {
    'unclear': "무슨 말인지 잘 이해하지 못했어요. 다시 말해 주세요.\n예: '(포켓몬 이름) 샘플 짜줘', '이 파티 약점 알려줘', '파티 하나 짜줘'",
    'off_topic': '그건 도와드릴 수 없어요. 저는 포켓몬 챔피언스 파티 빌딩(샘플·파티 추천, 약점·메가 확인)만 도와드려요.',
    'cant': '그건 아직 할 수 없어요. 승률·대미지 계산·선출 추천은 데이터가 없어서 지어서 답하지 않을게요. '
            '대신 파티 약점이나 어울리는 포켓몬은 봐 드릴 수 있어요.',
    'who': '누구를 말하는지 모르겠어요. 포켓몬 이름으로 다시 말해 주세요.',
}


# ---------------------------------------------------------------- 질문 → 의도 (규칙)

async def previous_pokemon(tools: Tools, history: list[dict]) -> dict | None:
    """앞 대화에서 이야기한 포켓몬: 최근부터, 코치가 1마리를 띄웠으면 그 포켓몬, 사용자가 이름을 말했으면 그 포켓몬."""
    for h in reversed(history):
        if h.get('role') == 'assistant' and len(h.get('party') or []) == 1:
            s = h['party'][0]
            stone = s.get('item') if s.get('item') and await is_stone(tools, s['pokemon'], s['item']) else None
            return {'id': s['pokemon'], 'stone': stone}
        if h.get('role') == 'user':
            found = await tools.find_pokemon(h.get('text', ''))
            if found:
                return found
    return None


async def is_stone(tools: Tools, pokemon: str, item: str) -> bool:
    items = (await tools._get('pokemon/', {'format': tools.format}, cache=True))['items']
    return any(m['item'] == item for p in items if p['id'] == pokemon for m in p['megas'])


# 지금 파티 고치기: "빼고 넣을 만한", "수정할 만한 거", "바꿀 멤버" 등
IMPROVE = re.compile(r'빼고 ?넣|뺄 ?만한|바꿀 ?만한|바꿔야|바꾸면 좋|교체|수정(할|이 ?필요|하면|해야)|고칠|손볼|손 ?봐|개선|보완|'
                     r'더 좋게|(뭘|누굴|누구를|어떤 ?걸) ?바꿀')
# 지금 육성형 점검: "구애스카프인데 방어 맞아?", "이 기술 배치 괜찮아?"
REVIEW = re.compile(r'맞아|맞나|맞는 ?거|괜찮아|괜찮나|이상해|이상한|말이 ?돼|정상이|문제 ?없')
WEATHER_WORDS = {'rain': re.compile(r'비 ?파티|비를|비가|비 ?오|비바라기|잔비|우천'),
                 'sun': re.compile(r'쾌청|햇살|해 ?파티|가뭄|맑은 ?날')}
WEATHER_SETTERS = {'rain': {'raindance', 'drizzle'}, 'sun': {'sunnyday', 'drought'}}


def weather_in(q: str) -> str | None:
    return next((w for w, r in WEATHER_WORDS.items() if r.search(q)), None)


def party_weather(party: list[dict]) -> str | None:
    """화면 파티에 날씨를 까는 기술·특성이 있으면 그 날씨 (두 가지면 None)."""
    found = {w for m in party for w, ids in WEATHER_SETTERS.items() if ids & {m.get('ability'), *(m.get('moves') or [])}}
    return found.pop() if len(found) == 1 else None


def format_of(q: str) -> dict:
    return {'format': 'doubles'} if '더블' in q else {'format': 'singles'} if '싱글' in q else {}


def sample_intent(out: dict, q: str, target: dict, item, without: list, role) -> dict:
    # 도구를 정하면 메가스톤을 들 수 없으므로 일반 폼으로
    return {**out, 'intent': 'sample', 'pokemon': target['id'], 'stone': None if item else target.get('stone'),
            **({'item': item} if item else {}), **({'without': [w for w in without if w]} if without else {}),
            **({'role': role} if role else {}), **({'other': True} if re.search(r'다른|또|말고', q) else {})}


async def parse(question: str, history: list[dict], tools: Tools, classify=None, party_size: int = 6) -> dict:
    """question: 지금 질문, history: 앞 대화 (지금 질문 제외, [{role, text, party?}]).
    classify: 규칙이 못 알아들은(unclear·off_topic) 질문을 로컬 모델로 다시 분류 (agent.classify.classify). 없으면 규칙만."""
    intent = await parse_rules(question, history, tools)
    if classify and intent.get('reason') in ('unclear', 'off_topic'):
        label = await classify(question, history, party_size)
        if label == 'who' and not POINTER.search(question):
            label = None                        # 욕설 등을 '누구?'로 고르는 경우가 있어서
        if label and label not in ('unclear', 'off_topic'):
            return {**await from_label(label, question.strip(), history, tools), 'by': 'model'}
    return intent


async def from_label(label: str, q: str, history: list[dict], tools: Tools) -> dict:
    """모델이 고른 의도 이름 → 의도 JSON (이름·도구·기술은 규칙과 같게 DB에서 찾음)."""
    out = format_of(q)
    if label in ('cant', 'who'):
        return {'intent': 'unknown', 'reason': label}
    weather = weather_in(q)
    if label in ('weakness', 'threats'):
        return {**out, 'intent': label, **({'weather': weather} if weather else {}),
                **({'teams': True} if label == 'threats' and '파티' in q.replace('이 파티', '') else {})}
    if label in ('mega', 'improve'):
        return {**out, 'intent': label}
    if label == 'fill':
        return {**out, 'intent': 'fill', 'count': 1 if re.search(r'한 ?마리|하나|마지막|한 ?자리', q) else 'all'}
    named = await tools.find_pokemon(q)
    if label == 'party':
        return {**out, 'intent': 'party', **({'pokemon': named['id']} if named else {})}
    target = named or await previous_pokemon(tools, history)
    if not target:          # "걔"라고 했으면 누구냐고 묻고, 그것도 아니면 못 알아들은 것
        return {'intent': 'unknown', 'reason': 'who' if POINTER.search(q) else 'unclear'}
    if label in ('item_usage', 'review'):
        return {**out, 'intent': label, 'pokemon': target['id']}
    item = await tools.item_in(q)
    without = [await tools.move_id(m) for m in await tools.moves_without(q)]
    return sample_intent(out, q, target, item, without, next((v for k, v in ROLES if k in q), None))


async def parse_rules(question: str, history: list[dict], tools: Tools) -> dict:
    """키워드 규칙."""
    q = question.strip()
    out = format_of(q)
    if re.search(r'승률|대미지|데미지|선출|예측|확률', q):
        return {'intent': 'unknown', 'reason': 'cant'}
    weather = weather_in(q)
    if re.search(r'찌르|위협|카운터|천적|조심|무서|까다|약점 ?포켓몬|(어려운|힘든|껄끄러운) ?상대|불리한', q):
        return {**out, 'intent': 'threats', **({'teams': True} if '파티' in q.replace('이 파티', '') else {}),
                **({'weather': weather} if weather else {})}
    if re.search(r'약점|상성|파회|파훼', q) or weather:
        return {**out, 'intent': 'weakness', **({'weather': weather} if weather else {})}
    if re.search(r'메가.*(누구|누굴|누가)|(누구|누굴).*메가', q):
        return {**out, 'intent': 'mega'}
    if IMPROVE.search(q) and not await tools.find_pokemon(q):     # 이름이 있으면 그 포켓몬 샘플 바꾸기
        return {**out, 'intent': 'improve'}
    if re.search(r'채워|나머지|빈 ?자리|한 ?마리 더|마지막 한|부족한|남은 자리', q):
        one = re.search(r'한 ?마리|마지막|하나', q)
        return {**out, 'intent': 'fill', 'count': 1 if one else 'all'}

    named = await tools.find_pokemon(q)
    pointed = POINTER.search(q)
    target = named or ((await previous_pokemon(tools, history)) if pointed or not named else None)
    item = await tools.item_in(q)
    without = [await tools.move_id(m) for m in await tools.moves_without(q)]
    role = next((v for k, v in ROLES if k in q), None)

    if REVIEW.search(q) and (named or pointed) and target:     # "얘 구애스카프인데 방어 맞아?"
        return {**out, 'intent': 'review', 'pokemon': target['id']}
    if re.search(r'파티', q) and re.search(r'짜|만들|추천|하나|구성', q) and not named:
        return {**out, 'intent': 'party'}
    if re.search(r'파티', q) and re.search(r'짜|만들|추천', q) and named:
        return {**out, 'intent': 'party', 'pokemon': named['id']}
    if re.search(r'아이템|도구|템', q) and re.search(r'뭐|무슨|사용률|많이|추천|다른|바꾸|바꿔|주고', q) and not item:
        if not target:
            return {'intent': 'unknown', 'reason': 'who'}
        return {**out, 'intent': 'item_usage', 'pokemon': target['id']}
    sample_words = re.search(r'샘플|육성|형태|짜|추천|다른|바꿔|바꾸|없는|빼고|으로|로$|어때', q)
    if sample_words or item or without or role:
        if not target:
            if pointed or item or without:
                return {'intent': 'unknown', 'reason': 'who'}
        else:
            return sample_intent(out, q, target, item, without, role)
    if named:
        return {**out, 'intent': 'sample', 'pokemon': named['id'], 'stone': named.get('stone')}
    return {'intent': 'unknown', 'reason': 'unclear' if DOMAIN.search(q) or not re.search(r'[가-힣]{2,}', q) else 'off_topic'}


# ---------------------------------------------------------------- 의도 → DB 조회·띄우기·답

async def run(intent: dict, tools: Tools, party: list[dict], history: list[dict] | None = None):
    """('status', 문구) ('party', 샘플들) ('text', 답) 이벤트를 낸다. party: 화면 파티 (None 없이),
    history: 앞 대화 ("다른 거"면 앞에서 띄운 샘플은 빼고 고름)."""
    kind = intent.get('intent')
    trace = []

    async def call(name, args):
        out = await tools.run(name, args)
        trace.append((name, args, out))
        return out

    async def show(members):
        out = await call('propose_party', {'members': members})
        shown = tools.proposed
        tools.proposed = None
        return out, shown

    if kind == 'unknown':
        yield 'text', UNKNOWN_TEXT.get(intent.get('reason'), UNKNOWN_TEXT['unclear'])
        return

    if kind in ('weakness', 'mega', 'threats', 'fill', 'improve') and not party:
        yield 'text', '화면 파티가 비어 있어요. 포켓몬을 넣은 뒤 다시 물어보거나, 파티를 짜 달라고 해 주세요.'
        return

    if kind == 'improve':
        yield 'status', '파티 점검 중'
        check = await call('check_party', {'members': party})
        weather = intent.get('weather') or party_weather(party)
        yield 'status', '바꿀 후보 찾는 중'
        plan = await counter_plan(tools, call, party, check, weather, force=True)
        yield 'text', answers.improve_answer(check, weather, plan)
        return

    if kind == 'weakness':
        yield 'status', '파티 점검 중'
        check = await call('check_party', {'members': party})
        weather = intent.get('weather') or party_weather(party)
        yield 'status', '받아 줄 포켓몬 찾는 중'
        plan = await counter_plan(tools, call, party, check, weather)
        yield 'text', answers.weakness_answer(check, weather, plan)
        return

    if kind == 'threats':
        yield 'status', '위협 포켓몬 찾는 중'
        # 도구(find_threats)는 모델 문맥 때문에 5마리로 자르므로, 날씨로 거른 뒤에도 남게 API 결과(최대 8)를 그대로 씀
        th = await tools._post('threats/', {'members': [{'pokemon': m['pokemon'], 'item': m.get('item', '')} for m in party],
                                            'format': tools.format, 'top': 40})
        weather = intent.get('weather') or party_weather(party)
        th = answers.weather_threats(th, weather)
        text = answers.threats_answer(th, weather)
        if intent.get('teams') and th.get('threats'):
            yield 'status', '위협 포켓몬이 든 파티 찾는 중'
            text += await threat_teams(tools, th['threats'])
        yield 'text', text
        return

    if kind == 'mega':
        yield 'status', '메가스톤 확인 중'
        yield 'text', await mega_answer(tools, party)
        return

    if kind == 'review':
        yield 'status', '육성형 점검 중'
        yield 'text', await review_answer(tools, call, intent['pokemon'], party, history or [])
        return

    if kind == 'item_usage':
        yield 'status', '포켓몬 정보 확인 중'
        info = await call('get_pokemon', {'id': intent['pokemon']})
        yield 'text', answers.item_answer(info, tools.format) or '이 포켓몬의 도구 사용률 데이터가 없어요.'
        return

    if kind == 'party':
        yield 'status', '파티 샘플 찾는 중'
        members = await team_for(tools, call, intent.get('pokemon'))
        if not members:
            yield 'text', '조건에 맞는 상위 파티를 찾지 못했어요.'
            return
        await call('check_party', {'members': members})
        out, shown = await show(members)
        if shown:
            yield 'party', shown
        yield 'text', answers.party_answer(trace, members) if shown else f'파티를 띄우지 못했어요: {out}'
        return

    if kind == 'fill':
        if len(party) >= 6:
            yield 'text', '파티는 6마리가 최대라 더 넣을 수 없어요. 바꿀 멤버나 넣고 싶은 포켓몬을 알려 주세요.'
            return
        yield 'status', '같이 쓰인 포켓몬 찾는 중'
        filled = list(party)
        while len(filled) < 6:                  # "나머지"면 6마리까지, "한 마리 더"면 1마리
            pick = await fill_one(tools, call, filled)
            if not pick:
                break
            filled.append(pick)
            if intent.get('count') == 1:
                break
        if len(filled) == len(party):
            yield 'text', '지금 파티와 같이 쓰인 포켓몬 중에 도구·포켓몬이 겹치지 않는 후보를 찾지 못했어요.'
            return
        await call('check_party', {'members': filled})      # 넣은 뒤 구성·한글 이름
        out, shown = await show(filled)
        if shown:
            yield 'party', shown
        added = len(filled) - len(party)
        yield 'text', answers.party_answer(trace, filled, compare=added == 1,
                                           lead=f'같이 쓰인 포켓몬으로 {added}마리를 채웠어요 (화면에 띄움).')
        return

    if kind == 'sample':
        yield 'status', '샘플 찾는 중'
        seen = [s for h in history or [] for s in h.get('party') or []] if intent.get('other') else []
        async for e in sample(tools, call, show, intent, trace, seen):
            yield e
        return

    yield 'text', UNKNOWN_TEXT['unclear']


def same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ('pokemon', 'item', 'ability', 'nature')) and         sorted(a.get('moves') or []) == sorted(b.get('moves') or [])


async def sample(tools: Tools, call, show, intent: dict, trace: list, seen: list[dict]):
    """공개 샘플 → 없으면 사용률로 조합 (검사 통과만) → 그것도 안 되면 이유. seen: 이미 띄운 샘플 (다른 거 달라면 뺌)."""
    item = intent.get('stone') or intent.get('item')
    args = {'pokemon': intent['pokemon'], **({'item': item} if item else {}),
            **({'without': intent['without']} if intent.get('without') else {}),
            **({'role': intent['role']} if intent.get('role') else {})}
    try:
        res = await call('search_samples', args)
    except ToolError as e:
        yield 'text', str(e)
        return
    fresh = [r['sample'] for r in (res.get('samples') or [])
             if not any(same(r['sample'], x) for x in seen)] if isinstance(res, dict) else []
    fresh = [x for x in fresh if not await tools.set_issues(x)] or fresh     # 구애스카프+방어 같은 건 뒤로 (그것뿐이면 그대로)
    if isinstance(res, dict) and res.get('samples') and not fresh:
        yield 'text', '조건에 맞는 공개 샘플은 앞에서 보여 드린 것뿐이에요. 도구·기술·역할 같은 조건을 바꿔서 말해 주세요.'
        return
    if fresh:
        s = fresh[0]
        out, shown = await show([s])
        if shown:
            yield 'party', shown
            yield 'text', answers.sample_answer(trace, s)
            return
    built = await build_from_usage(tools, intent['pokemon'], item, intent.get('without') or [])
    if built:
        s, why = built
        out, shown = await show([s])
        if shown:
            yield 'party', shown
            yield 'text', why
            return
    yield 'text', answers.render('', trace, tools.format) or '조건에 맞는 샘플을 찾지 못했어요.'


async def build_from_usage(tools: Tools, pokemon: str, item: str | None, without: list[str]):
    """공개 샘플이 없을 때 그 포켓몬의 사용률(특성·성격·SP·기술)로 조합. validate_set 통과만. (샘플, 답 문장)."""
    d = await tools._get(f'pokemon/{pokemon}/', cache=True)
    u = (d.get('usage') or {}).get(tools.format)
    if not u or not u.get('spread') or len(u.get('move') or []) < 4:
        return None
    items = {i['id']: i for i in await tools._items()}
    item_id = item and (await tools.item_id(item) or item)
    if not item_id:
        item_id = next((x['id'] for x in u['item'] if not items.get(x['id'], {}).get('mega_from')), u['item'][0]['id'])
    drop = set(without or [])
    moves = [m for m in u['move'] if m['id'] not in drop][:4]
    ability, nature = u['ability'][0], u['nature'][0]
    for spread in u['spread'][:3]:
        s = {'pokemon': pokemon, 'item': item_id, 'ability': ability['id'], 'nature': nature['id'],
             'sp': spread['sp'], 'moves': [m['id'] for m in moves]}
        v = await tools._validate(s)
        if v.get('valid'):
            names = await tools.party_names([s])
            short = f"{names[0] or pokemon} @ {items.get(item_id, {}).get('name_ko', item_id)}"
            fmt = FORMAT_KO.get(tools.format, tools.format)
            move_text = ', '.join(f"{m['name_ko']} {m['pct']}%" for m in moves)
            text = (f"{short} ({answers.sp_text(spread['sp'])}) 추천 (화면에 띄움).\n"
                    f"조건에 맞는 공개 샘플이 없어서 {fmt} 사용률로 짰어요.\n"
                    f"- 특성 {ability['name_ko']} {ability['pct']}% · 성격 {nature['name_ko']} {nature['pct']}% · "
                    f"SP 분배 {spread['pct']}%\n"
                    f"- 기술: {move_text}\n"
                    '항목마다 많이 쓰인 걸 모은 조합이라, 이 조합 그대로 쓴 공개 샘플이 있는 건 아니에요.')
            return s, text
    return None


async def team_for(tools: Tools, call, pokemon: str | None) -> list[dict] | None:
    """상위 파티 중 6마리가 다 있는 첫 파티 (pokemon을 주면 그 포켓몬이 든 파티)."""
    name = None
    if pokemon:
        name = (await tools.party_names([{'pokemon': pokemon}]))[0] or pokemon
    listing = await tools.run('search_teams', {'pokemon': name} if name else {})
    for t in (listing.get('teams') or [])[:5]:
        team = await call('get_team', {'id': t['id']})
        members = [m['sample'] for m in team.get('members', [])]
        if len(members) == 6:
            return members
    return None


async def fill_one(tools: Tools, call, party: list[dict]) -> dict | None:
    """화면 파티 첫 멤버와 같이 쓰인 포켓몬 중 포켓몬·도구가 겹치지 않는 샘플 3개를 비교해 약점을 가장 잘 받아 주는 것."""
    have = {m['pokemon'] for m in party}
    items = {m.get('item') for m in party if m.get('item')}
    partners = await call('find_partners', {'pokemon': [party[0]['pokemon']]})
    cands = []
    for p in partners.get('partners', [])[:8]:
        found = await tools.find_pokemon(p['name_ko'])
        if not found or found['id'] in have:
            continue
        res = await call('search_samples', {'pokemon': found['id']})
        s = None
        for r in (res.get('samples', []) if isinstance(res, dict) else []):
            if r['sample']['item'] not in items and not await tools.set_issues(r['sample']):
                s = r['sample']
                break
        if s:
            cands.append(s)
        if len(cands) == 3:
            break
    if not cands:
        return None
    cmp = await call('check_party', {'members': party, 'candidates': cands})
    rows = cmp.get('candidates', [])
    best = max(range(len(cands)), key=lambda i: (len(rows[i]['covers']) - len(rows[i]['new_weak']), -i) if i < len(rows) else (-9, -i))
    return cands[best]


async def counter_plan(tools: Tools, call, party: list[dict], check: dict, weather: str | None,
                       force: bool = False) -> str:
    """추천 수정 방안: 겹치는 약점을 받아 주는, 화면 멤버와 같이 쓰인 포켓몬 샘플.
    빈자리가 있으면 넣는 후보, 6마리면 그 약점 멤버와 바꾸는 후보 (바꾼 뒤 약점 변화).
    force (파티 고쳐 달라는 요청): 2마리 겹침도 보고, 가장 많은 약점에 후보가 없으면 다음 약점으로."""
    halved = answers.WEATHER.get(weather, (None, None))[1]
    weak = [(t, ms) for t, ms in answers.weak_sorted(check['summary']) if t != halved]
    if not force:
        weak = weak[:1]
        if weak and len(weak[0][1]) < 3 and check['summary']['weak_cover'].get(weak[0][0]):
            return ''                           # 2마리 겹침이고 받아 줄 멤버가 있으면 굳이 바꾸지 않음
    if not weak:
        return ''
    cands = await partner_samples(tools, call, party)
    if not cands:
        return f"\n\n같이 쓰인 포켓몬 데이터가 부족해서 {weak[0][0]} 약점을 받아 줄 후보는 찾지 못했어요."
    names = {m['pokemon']: m['name_ko'] for m in check['members']}
    for t, weak_ms in weak:
        # 후보 비교(candidates)는 5마리 이하 파티만 되고 한 번에 3마리라, 6마리면 그 약점이 아닌 멤버 하나를 뺀 파티에
        # 넣어 봐서 이 약점을 받아 주는 후보만 고름 (실제 교체 결과는 swap_lines가 6마리로 다시 점검)
        if len(party) < 6:
            base = party
        else:
            out = next(i for i in reversed(range(len(party))) if names.get(party[i]['pokemon']) not in weak_ms)
            base = party[:out] + party[out + 1:]
        rows = []
        for i in range(0, len(cands), 3):
            rows += (await call('check_party', {'members': base, 'candidates': cands[i:i + 3]})).get('candidates', [])
        good = [(c, r) for c, r in zip(cands, rows) if t in r['covers']][:3]
        if not good:
            continue
        head = (f"\n\n추천 수정 방안 — {t} 약점 {len(weak_ms)}마리 "
                f"(같이 쓰인 포켓몬 중 {answers.josa(t, '을', '를')} 받아 주는 샘플):")
        lines = (add_lines(good) if len(party) < 6
                 else await swap_lines(call, party, check, names, t, weak_ms, good))
        if lines:
            return head + '\n' + '\n'.join(lines)
    t = weak[0][0]
    return f"\n\n같이 쓰인 포켓몬 중에는 {t} 공격을 받아 줄 후보가 없어요. 약점 멤버의 기술·도구로 버티는 쪽을 생각해 보세요."


async def partner_samples(tools: Tools, call, party: list[dict]) -> list[dict]:
    """화면 멤버마다 같이 쓰인 포켓몬 (횟수 합) 상위의 샘플 최대 6개. 화면에 있는 포켓몬·도구는 뺌."""
    have = {m['pokemon'] for m in party}
    items = {m.get('item') for m in party if m.get('item')}
    count = {}
    for m in party:
        try:
            res = await call('find_partners', {'pokemon': [m['pokemon']]})
        except ToolError:
            continue
        for p in res.get('partners', []):
            count[p['name_ko']] = count.get(p['name_ko'], 0) + p['count']
    cands = []
    for name in sorted(count, key=lambda n: -count[n])[:10]:
        found = await tools.find_pokemon(name)
        if not found or found['id'] in have:
            continue
        res = await call('search_samples', {'pokemon': found['id']})
        s = None
        for r in (res.get('samples', []) if isinstance(res, dict) else []):
            if r['sample']['item'] not in items and not await tools.set_issues(r['sample']):
                s = r['sample']
                break
        if s:
            cands.append(s)
        if len(cands) == 6:
            break
    return cands


def add_lines(good) -> list[str]:
    lines = []
    for c, r in good:
        cons = f" / 단점: {', '.join(w.split(' ')[0] for w in r['new_weak'])} 약점 늘어남" if r['new_weak'] else ''
        lines.append(f"- {r['name_ko']} 넣기 ({answers.role_text(r['roles'])}): {', '.join(r['covers'])} 받아 줌{cons}")
    return lines


async def swap_lines(call, party, check, names, t, weak_ms, good) -> list[str]:
    """6마리: 후보마다 약점 멤버 중 바꿨을 때 2마리 이상 겹치는 약점이 가장 적어지는 멤버."""
    before = check['summary']['weak_types_2plus']
    lines = []
    for c, r in good:
        best = None
        for i, m in enumerate(party):
            if names.get(m['pokemon']) not in weak_ms:
                continue
            after = (await call('check_party', {'members': party[:i] + party[i + 1:] + [c]}))['summary']['weak_types_2plus']
            score = sum(map(len, after.values()))
            if best is None or score < best[0]:
                best = (score, m, after)
        if not best:
            continue
        _, m, after = best
        n_after = len(after.get(t, []))
        more = [k for k, v in after.items() if len(v) > len(before.get(k, []))]
        lines.append(f"- {names[m['pokemon']]} 대신 {r['name_ko']} ({answers.role_text(r['roles'])}): "
                     + (f"{t} 약점 {len(weak_ms)}→{n_after}마리" if n_after else f"{t} 약점 겹침 없어짐") + (f" / 단점: {', '.join(more)} 약점 늘어남" if more else ''))
    return lines


async def threat_teams(tools: Tools, threats: list[dict]) -> str:
    """조심할 파티: 위협 포켓몬이 든 상위 파티 중 위협 포켓몬이 많이 든 순."""
    names = [x['name_ko'] for x in threats]
    teams = {}
    for name in names[:3]:
        res = await tools.run('search_teams', {'pokemon': name})
        for t in res.get('teams', []):
            teams[t['id']] = t
    rows = sorted(((t, [n for n in names if n in t['members']]) for t in teams.values()), key=lambda x: -len(x[1]))
    rows = [(t, hit) for t, hit in rows if len(hit) >= 2][:3]
    if not rows:
        return (f"\n\n위협 포켓몬이 2마리 이상 같이 든 상위 파티는 찾지 못했어요. "
                f"{answers.josa('·'.join(names[:3]), '이', '가')} 든 파티를 만나면 조심하세요.")
    lines = [f"- {answers.team_ref(t['title'])} ({t['source']}): {'·'.join(hit)}" for t, hit in rows]
    return '\n\n조심할 파티 (위협 포켓몬이 든 상위 파티):\n' + '\n'.join(lines)


async def review_answer(tools: Tools, call, pokemon: str, party: list[dict], history: list[dict]) -> str:
    """화면 또는 앞에서 띄운 그 포켓몬 육성형의 도구·기술·SP 점검."""
    sets = [m for m in party if m.get('pokemon') == pokemon] + \
           [m for h in reversed(history) for m in h.get('party') or [] if m.get('pokemon') == pokemon]
    name = (await tools.party_names([{'pokemon': pokemon}]))[0] or pokemon
    if not sets:
        return f"화면이나 앞에서 띄운 {name} 육성형이 없어요. 샘플을 띄우거나 화면에 넣은 뒤 다시 물어봐 주세요."
    s = sets[0]
    check = await call('check_party', {'members': [s]})
    me = check['members'][0]
    moves = {m['id']: m['name_ko'] for m in (await tools._get('options/', {}, cache=True)).get('moves', [])}
    item = next((i['name_ko'] for i in await tools._items() if i['id'] == s.get('item')), s.get('item') or '-')
    head = f"{me['name_ko']} @ {item} ({me['sp']}) — {', '.join(moves.get(x, x) for x in s.get('moves') or [] if x)}"
    v = await tools._validate(s)
    problems = await tools.set_issues(s) + [c['message'] for c in v.get('checks', []) if c['level'] in ('error', 'warn')] \
        + [w.split(': ', 1)[-1] for w in check.get('warnings', [])]
    if not problems:
        return f"{head}\n도구·기술·SP에 안 맞는 점은 없어요. SP·기술 기준 역할은 {answers.josa(answers.role_text(me['roles']), '이에요', '예요')}."
    return (f"{head}\n걸리는 점:\n" + '\n'.join(f'- {p}' for p in problems)
            + f"\n다른 공개 샘플을 보려면 '{name} 다른 형태'라고 말해 주세요.")


async def mega_answer(tools: Tools, party: list[dict]) -> str:
    items = {i['id']: i for i in await tools._items()}
    stones = [m for m in party if items.get(m.get('item', ''), {}).get('mega_from')]
    if not stones:
        return '지금 파티에는 메가스톤을 든 포켓몬이 없어서 메가진화를 할 수 없어요.'
    names = await tools.party_names(stones)
    if len(stones) == 1:
        return f"메가스톤을 든 건 {names[0]} 한 마리라 {answers.josa(names[0], '이', '가')} 메가진화해요."
    lines = []
    known = []
    for m, n in zip(stones, names):
        d = await tools._get(f"pokemon/{m['pokemon']}/", cache=True)
        u = (d.get('usage') or {}).get(tools.format) or {}
        pct = next((x['pct'] for x in u.get('item', []) if x['id'] == m['item']), None)
        base = d.get('name_ko', m['pokemon'])
        stone = items[m['item']]['name_ko']
        lines.append(f"- {n} — {base}의 도구 중 {stone} {pct}%" if pct is not None else f"- {n} — 사용률 상위에 {stone} 없음")
        if pct is not None:
            known.append((pct, n))
    text = (f"메가스톤을 든 포켓몬이 {len(stones)}마리예요. 메가진화는 배틀마다 한 번이라 같이 선출하면 한 마리만 "
            "메가진화할 수 있어요.\n" + '\n'.join(lines))
    if len(known) >= 2 and len({p for p, _ in known}) > 1:
        text += f"\n상대에 따라 달라서 정답은 없지만, 사용률로는 {answers.josa(max(known)[1], '이', '가')} 메가로 더 많이 쓰여요."
    if len(stones) >= 3:
        text += '\n메가스톤이 3개 이상이면 선출이 제한돼요.'
    return text
