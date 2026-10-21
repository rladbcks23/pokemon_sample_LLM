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


async def parse(question: str, history: list[dict], tools: Tools) -> dict:
    """question: 지금 질문, history: 앞 대화 (지금 질문 제외, [{role, text, party?}])."""
    q = question.strip()
    out = {}
    if '더블' in q:
        out['format'] = 'doubles'
    elif '싱글' in q:
        out['format'] = 'singles'
    if re.search(r'승률|대미지|데미지|선출|예측|확률', q):
        return {'intent': 'unknown', 'reason': 'cant'}
    if re.search(r'찌르|위협|카운터|천적', q):
        return {**out, 'intent': 'threats'}
    if re.search(r'약점|상성', q):
        return {**out, 'intent': 'weakness'}
    if re.search(r'메가.*(누구|누굴|누가)|(누구|누굴).*메가', q):
        return {**out, 'intent': 'mega'}
    if re.search(r'채워|나머지|빈 ?자리|한 ?마리 더|마지막 한|부족한|남은 자리', q):
        one = re.search(r'한 ?마리|마지막|하나', q)
        return {**out, 'intent': 'fill', 'count': 1 if one else 'all'}

    named = await tools.find_pokemon(q)
    pointed = POINTER.search(q)
    target = named or ((await previous_pokemon(tools, history)) if pointed or not named else None)
    item = await tools.item_in(q)
    without = [await tools.move_id(m) for m in await tools.moves_without(q)]
    role = next((v for k, v in ROLES if k in q), None)

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
            # 도구를 정하면 메가스톤을 들 수 없으므로 일반 폼으로
            return {**out, 'intent': 'sample', 'pokemon': target['id'], 'stone': None if item else target.get('stone'),
                    **({'item': item} if item else {}), **({'without': [w for w in without if w]} if without else {}),
                    **({'role': role} if role else {}), **({'other': True} if re.search(r'다른|또|말고', q) else {})}
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

    if kind in ('weakness', 'mega', 'threats', 'fill') and not party:
        yield 'text', '화면 파티가 비어 있어요. 포켓몬을 넣은 뒤 다시 물어보거나, 파티를 짜 달라고 해 주세요.'
        return

    if kind == 'weakness':
        yield 'status', '파티 점검 중'
        yield 'text', answers.weakness_answer(await call('check_party', {'members': party}))
        return

    if kind == 'threats':
        yield 'status', '위협 포켓몬 찾는 중'
        th = await call('find_threats', {'members': [{'pokemon': m['pokemon'], 'item': m.get('item', '')} for m in party]})
        yield 'text', answers.threats_answer(th)
        return

    if kind == 'mega':
        yield 'status', '메가스톤 확인 중'
        yield 'text', await mega_answer(tools, party)
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
        s = next((r['sample'] for r in (res.get('samples', []) if isinstance(res, dict) else [])
                  if r['sample']['item'] not in items), None)
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
