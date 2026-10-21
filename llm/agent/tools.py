"""에이전트 도구: back API를 불러 사실(종족값·기술·사용률·파티)을 조회한다.

도구 설명·결과는 짧게 유지한다 (로컬 4B 모델의 문맥 길이·학습 길이 때문). 배우는 기술 전체 같은 긴 목록은 요청할 때만.
"""
import json
import re

import httpx

STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
STR = {'type': 'string'}
INT = {'type': 'integer'}
FORMAT = {'type': 'string', 'enum': ['singles', 'doubles']}      # 생략하면 화면의 포맷 (시스템 프롬프트에 적음)
MEMBER = {'type': 'object', 'properties': {'pokemon': STR, 'item': STR}, 'required': ['pokemon']}
SAMPLE = {
    'type': 'object',
    'description': '육성형(영문 ID). 메가는 메가 전 폼+메가스톤. sp는 hp~spe 각 0~32·합 66, moves 4개',
    'properties': {'pokemon': STR, 'item': STR, 'ability': STR, 'nature': STR, 'sp': {'type': 'object'},
                   'moves': {'type': 'array', 'items': STR}},
    'required': ['pokemon', 'item', 'ability', 'nature', 'sp', 'moves'],
}


def _tool(name: str, description: str, properties: dict, required: tuple = ()) -> dict:
    return {'name': name, 'description': description,
            'input_schema': {'type': 'object', 'properties': properties, **({'required': list(required)} if required else {})}}


TOOLS = [
    _tool('search_pokemon', '이름(한글/영문) 일부로 포켓몬 찾기: ID·타입·종족값·픽률 순위·메가 폼.',
          {'query': STR, 'format': FORMAT}, ('query',)),
    _tool('get_pokemon', '포켓몬 상세: 폼별 타입·종족값·특성, 사용률 상위(기술·도구·특성·성격·SP 배분). '
                         'include_learnset=true면 배울 수 있는 기술 전체 (새로 짤 때만).',
          {'id': STR, 'format': FORMAT, 'include_learnset': {'type': 'boolean'}}, ('id',)),
    _tool('get_ranking', '인게임 픽률 순위 (기본 30위까지).', {'format': FORMAT, 'limit': INT}),
    _tool('search_samples', '공개 샘플 3개: 샘플별 역할(SP·기술로 판정)과 그 포켓몬 샘플의 형태 분포(shapes). '
                            'role로 원하는 형태(막이, 특수 딜러, 서포터 등)만, item으로 그 도구를 든 샘플만, '
                            'without(기술 이름들)으로 그 기술이 없는 샘플만. sample은 propose_party에 그대로.',
          {'pokemon': STR, 'format': FORMAT, 'role': STR, 'item': STR,
           'without': {'type': 'array', 'items': STR}}, ('pokemon',)),
    _tool('search_teams', '실제 파티 목록(OP.GG 상위·대회 팀). pokemon을 주면 그 포켓몬이 든 파티만.',
          {'pokemon': STR, 'format': FORMAT}),
    _tool('get_team', '파티 상세: 멤버 육성형(sample은 propose_party에 그대로).', {'id': INT}, ('id',)),
    _tool('check_party', '파티 점검: 멤버별 역할·SP·스피드, 역할 수·물리/특수 딜러 수·메가진화 포켓몬 수, '
                         '2마리 이상 겹치는 약점(타입별 약점 멤버)과 받아 줄 멤버, 경고. candidates(최대 3)를 주면 한 마리씩 넣어 본 비교.',
          {'members': {'type': 'array', 'items': SAMPLE}, 'candidates': {'type': 'array', 'items': SAMPLE},
           'format': FORMAT}, ('members',)),
    _tool('find_partners', '실제 상위 파티에서 주어진 포켓몬(ID 1~3)이 모두 든 파티 수와 같이 쓰인 포켓몬(횟수·%).',
          {'pokemon': {'type': 'array', 'items': STR}, 'format': FORMAT}, ('pokemon',)),
    _tool('find_threats', '픽률 상위 포켓몬 중 자주 쓰는 공격기(사용률 10% 이상)로 파티 여러 마리의 약점을 찌르는 포켓몬. '
                          '드문 기술은 sometimes.',
          {'members': {'type': 'array', 'items': MEMBER}, 'format': FORMAT}, ('members',)),
    _tool('get_speed_tiers', '픽률 상위 포켓몬의 스피드 실수치표 (보정 포함). min_speed/max_speed로 구간만.',
          {'format': FORMAT, 'min_speed': INT, 'max_speed': INT}),
    _tool('validate_set', '육성형 규칙 검사(특성·도구·기술·SP)와 Lv50 실수치.', SAMPLE['properties'], SAMPLE['required']),
    _tool('propose_party', '화면에 추천 파티 카드를 띄운다. 합법이고 같은 포켓몬·도구가 없어야 표시, 아니면 문제를 돌려줌.',
          {'members': {'type': 'array', 'items': SAMPLE}}, ('members',)),
]

# 화면에 보여 줄 진행 상태
STATUS = {
    'search_pokemon': '포켓몬 찾는 중', 'get_pokemon': '포켓몬 정보 확인 중', 'get_ranking': '픽률 순위 확인 중',
    'search_samples': '샘플 찾는 중', 'search_teams': '파티 샘플 찾는 중', 'get_team': '파티 확인 중',
    'get_speed_tiers': '스피드표 확인 중', 'validate_set': '육성형 검사 중',
    'propose_party': '추천 파티 검사 중', 'check_party': '파티 점검 중', 'find_partners': '같이 쓰인 포켓몬 찾는 중',
    'find_threats': '위협 포켓몬 찾는 중',
}


def readable(m: dict) -> str:
    """API 멤버(샘플·파티 상세 같은 모양) → DB 한글 이름으로 쓴 육성형 한 줄. 모델은 이걸 그대로 옮겨 쓴다."""
    return (f"{m['pokemon']['name_ko']} @ {(m['item'] or {}).get('name_ko', '-')} / "
            f"{(m['ability'] or {}).get('name_ko', '-')} / {(m['nature'] or {}).get('name_ko', '-')} / "
            f"SP {_sp_text(m['sp'])} / " + ', '.join(x['name_ko'] for x in m['moves'] if x))


class ToolError(Exception):
    """모델에게 is_error로 돌려줄 오류 (잘못된 ID 등)."""


def _top(rows: list[dict], n: int, keys=('id', 'name_ko', 'pct')) -> list[dict]:
    return [{k: r.get(k) for k in keys} for r in rows[:n]]


def _sp_text(sp: dict) -> str:
    return ' '.join(f'{k}{v}' for k, v in sp.items() if v) or '없음'


def compact_sample(s: dict) -> dict:
    """모델에게 보여 줄 샘플: SP는 0이 아닌 것만 (도구 결과·화면 상황을 짧게. 빠진 SP는 0으로 읽힘)."""
    return {**s, 'sp': {k: v for k, v in (s.get('sp') or {}).items() if v}}


class Tools:
    """도구 실행기. format: 지금 화면의 싱글/더블 (도구에서 format을 생략하면 이 값)."""

    def __init__(self, client: httpx.AsyncClient, format: str = 'singles'):
        self.client = client
        self.format = format if format in ('singles', 'doubles') else 'singles'
        self.proposed: list[dict] | None = None      # propose_party가 통과시킨 파티 (화면에 보낼 것)
        self.subject: str | None = None              # 지금 이야기 중인 포켓몬 ID (서버가 대화 기록으로 정함)
        self._cache: dict[str, dict] = {}

    async def _get(self, path: str, params: dict | None = None, cache: bool = False) -> dict:
        key = path + json.dumps(params or {}, sort_keys=True)
        if cache and key in self._cache:
            return self._cache[key]
        r = await self.client.get(path, params={k: v for k, v in (params or {}).items() if v not in (None, '')})
        _raise_input_error(r)
        if cache:
            self._cache[key] = r.json()
        return r.json()

    async def run(self, name: str, args: dict) -> dict | list:
        fn = getattr(self, f'tool_{name}', None)
        if not fn or name not in STATUS:
            raise ToolError(f'없는 도구: {name}')
        if not isinstance(args, dict):
            raise ToolError('입력은 객체여야 함')
        return await fn(**args)

    def _fmt(self, format: str | None) -> str:
        return format if format in ('singles', 'doubles') else self.format

    async def tool_search_pokemon(self, query: str, format: str | None = None) -> list[dict]:
        q = (query or '').strip().lower()
        if not q:
            raise ToolError('query가 비어 있음')
        items = (await self._get('pokemon/', {'format': self._fmt(format)}, cache=True))['items']
        hits = []
        for p in items:
            names = [p['id'], p['name'].lower(), p['name_ko']] + [m['name_ko'] for m in p['megas']]
            if any(q in n for n in names):
                hits.append({'id': p['id'], 'name_ko': p['name_ko'], 'types': p['types'], 'stats': p['stats'],
                             'rank': p['rank'],
                             'megas': [{'id': m['id'], 'name_ko': m['name_ko'], 'types': m['types'],
                                        'stats': m['stats'], 'stone': m['item']} for m in p['megas']]})
        return hits[:10] or [{'result': f'"{query}"는 이번 레귤레이션 포켓몬 목록에 없음'}]

    async def tool_get_pokemon(self, id: str, format: str | None = None, include_learnset: bool = False) -> dict:
        d = await self._get(f'pokemon/{id}/', cache=True)
        fmt = self._fmt(format)
        u = d['usage'].get(fmt)
        out = {
            'id': d['id'], 'name_ko': d['name_ko'],
            'forms': [{'id': f['id'], 'name_ko': f['name_ko'], 'types': f['types'], 'stats': f['stats'],
                       'mega_stone': f['required_item'] or None,
                       'abilities': [{'id': a['id'], 'name_ko': a['name_ko']} for a in f['abilities']]}
                      for f in d['forms']],
            'format': fmt,
            'usage': u and {
                'rank': u['rank'],
                **{k: _top(u[k], 5) for k in ('move', 'item', 'ability', 'nature')},
                'spread': [{'sp': _sp_text(s['sp']), 'pct': s['pct']} for s in u['spread'][:4]],
            },
        }
        if include_learnset:
            out['learnset'] = [{k: m[k] for k in ('id', 'name_ko', 'type', 'category', 'power', 'accuracy')}
                               for m in d['learnset']]
        return out

    async def tool_get_ranking(self, format: str | None = None, limit: int = 30) -> dict:
        d = await self._get('ranking/', {'format': self._fmt(format), 'limit': min(max(int(limit or 30), 1), 100)})
        # 한 줄씩 짧게: "1. 한카리아스 (garchomp)"
        return {'format': d['format'],
                'items': [f"{r['rank']}. {r['pokemon']['name_ko']} ({r['pokemon']['id']})" for r in d['items']]}

    async def _known_name(self, name: str) -> bool:
        """이번 레귤레이션 포켓몬 이름(한글/영문/ID) 중 하나에 들어맞는지 (지어낸 이름을 걸러 내려고)."""
        q = (name or '').strip().lower()
        items = (await self._get('pokemon/', {'format': self.format}, cache=True))['items']
        # 메가X/Y/Z처럼 한글 이름에도 영문이 있어 모두 소문자로 비교
        return bool(q) and any(q in n.lower() for p in items for n in [p['id'], p['name'], p['name_ko']]
                               + [x for m in p['megas'] for x in (m['id'], m['name_ko'])])

    async def _items(self) -> list[dict]:
        return (await self._get('options/', {}, cache=True))['items']

    async def item_id(self, text: str) -> str | None:
        """도구 한글 이름 또는 ID → ID."""
        q = (text or '').strip().lower().replace(' ', '')
        return next((i['id'] for i in await self._items() if q in (i['id'], i['name_ko'].replace(' ', '').lower())), None)

    async def move_id(self, text: str) -> str | None:
        """기술 한글 이름 또는 ID → ID."""
        q = (text or '').strip().lower().replace(' ', '')
        moves = (await self._get('options/', {}, cache=True)).get('moves', [])
        return next((m['id'] for m in moves if q in (m['id'], m['name_ko'].replace(' ', '').lower())), None)

    async def set_issues(self, sample: dict) -> list[str]:
        """육성형에서 도구와 기술이 서로 안 맞는 점 (공개 샘플에도 가끔 있음: 구애스카프 + 방어 등)."""
        moves = {m['id']: m for m in (await self._get('options/', {}, cache=True)).get('moves', [])}
        status = [moves[x]['name_ko'] for x in sample.get('moves') or [] if moves.get(x, {}).get('category') == 'Status']
        item = sample.get('item') or ''
        name = next((i['name_ko'] for i in await self._items() if i['id'] == item), item)
        if status and item == 'assaultvest':
            return [f"{name}를 들면 변화기를 쓸 수 없는데 {'·'.join(status)}가 있어요"]
        if status and item in ('choicescarf', 'choiceband', 'choicespecs'):
            return [f"{name}는 처음 고른 기술만 계속 써야 해서 {'·'.join(status)} 같은 변화기와 잘 안 맞아요"]
        return []

    async def moves_without(self, question: str) -> list[str]:
        """질문이 "빛의장막 리플렉터 없는 건"처럼 기술을 빼 달라는 말이면 그 기술 한글 이름들."""
        if not re.search(r'없는|없이|빼고|말고|안 쓰는|안쓰는', question or ''):
            return []
        moves = (await self._get('options/', {}, cache=True)).get('moves', [])
        q = (question or '').replace(' ', '')
        hits = [m['name_ko'] for m in moves if len(m['name_ko']) >= 2 and m['name_ko'].replace(' ', '') in q]
        return [h for h in hits if not any(h != o and h in o for o in hits)]      # 긴 이름 안의 짧은 이름은 빼고

    async def item_in(self, question: str) -> str | None:
        """질문에 들어 있는 도구 이름 (가장 긴 것) → ID. "X 말고"처럼 빼 달라는 말이면 None."""
        if re.search(r'말고|빼고|대신|말구|싫', question or ''):
            return None
        q = (question or '').replace(' ', '')
        hits = [i for i in await self._items() if len(i['name_ko']) >= 2 and i['name_ko'].replace(' ', '') in q]
        return max(hits, key=lambda i: len(i['name_ko']))['id'] if hits else None

    async def find_pokemon(self, text: str) -> dict | None:
        """글 속 포켓몬 한글 이름(가장 긴 것) → {'id': 메가 전 폼 ID, 'stone': 메가스톤 ID 또는 None, 'name_ko': 이름}."""
        items = (await self._get('pokemon/', {'format': self.format}, cache=True))['items']
        q = (text or '').replace(' ', '')
        hits = [(p['name_ko'], p['id'], None) for p in items] + \
               [(m['name_ko'], p['id'], m['item']) for p in items for m in p['megas']]
        found = [h for h in hits if h[0] and len(h[0]) >= 2 and h[0].replace(' ', '') in q]
        if not found:       # "대쓰여너"처럼 폼 이름(-수컷 등)을 빼고 말한 경우
            found = [h for h in hits if '-' in (h[0] or '') and len(h[0].split('-')[0]) >= 2
                     and h[0].split('-')[0].replace(' ', '') in q][:1]
        hits = found
        if not hits:
            return None
        name, pid, stone = max(hits, key=lambda h: len(h[0]))
        return {'id': pid, 'stone': stone, 'name_ko': name}

    async def pokemon_in(self, question: str) -> bool:
        """질문에 이번 레귤레이션 포켓몬(메가 폼 포함) 한글 이름이 들어 있는지."""
        items = (await self._get('pokemon/', {'format': self.format}, cache=True))['items']
        q = (question or '').replace(' ', '')
        return any(len(n) >= 2 and n in q for p in items for n in [p['name_ko']] + [m['name_ko'] for m in p['megas']])

    async def party_names(self, party: list[dict | None]) -> list[str]:
        """화면 파티 멤버마다 한글 이름 (메가스톤을 들면 메가 폼 이름). 화면 상황에 붙여 모델이 ID를 외워 맞히지 않게."""
        items = (await self._get('pokemon/', {'format': self.format}, cache=True))['items']
        base = {p['id']: p['name_ko'] for p in items}
        mega = {(p['id'], m['item']): m['name_ko'] for p in items for m in p['megas']}
        return [mega.get((m.get('pokemon'), m.get('item'))) or base.get(m.get('pokemon'), '')
                for m in party if m]

    async def _mega(self, name: str) -> tuple[str, str] | None:
        """메가 폼 이름이면 (메가 전 폼 ID, 메가스톤 ID). 샘플은 메가 전 폼 + 메가스톤으로 저장돼 있음."""
        q = (name or '').strip().lower()
        items = (await self._get('pokemon/', {'format': self.format}, cache=True))['items']
        for p in items:
            for m in p['megas']:
                if q in (m['id'], m['name_ko'].lower()):
                    return p['id'], m['item']
        return None

    async def tool_search_samples(self, pokemon: str | None = None, format: str | None = None, source: str | None = None,
                                  role: str | None = None, item: str | None = None,
                                  without: list[str] | str | None = None) -> dict | list:
        """샘플 3개 + 그 포켓몬 샘플 전체의 형태 분포. role을 주면 그 역할(예: 막이, 특수 딜러) 샘플만,
        item(한글 이름이나 ID)을 주면 그 도구를 든 샘플만 (메가 폼 이름이면 그 메가스톤),
        without(기술 한글 이름이나 ID)을 주면 그 기술이 하나도 없는 샘플만."""
        if not (pokemon or '').strip():
            raise ToolError('pokemon(포켓몬 이름)이 필요함. 후보 이름은 화면 파티나 get_ranking·find_partners 결과에서 고를 것')
        if not await self._known_name(pokemon):
            raise ToolError(f'"{pokemon}"는 이번 레귤레이션 포켓몬 목록에 없는 이름. '
                            '지어낸 이름을 쓰지 말고 화면·get_ranking·find_partners·search_pokemon 결과의 이름을 쓸 것')
        mega = await self._mega(pokemon)
        item_id = mega[1] if mega else (await self.item_id(item) if item else None)
        if item and not item_id:
            raise ToolError(f'"{item}"는 도구 목록에 없는 이름')
        without = [without] if isinstance(without, str) else list(without or [])
        drop = {await self.move_id(x) or x for x in without}
        d = await self._get('samples/', {'q': mega[0] if mega else pokemon, 'item': item_id, 'format': self._fmt(format),
                                         'source': source, 'size': 30 if role or drop else 3})
        rows = [s for s in d['results'] if (not role or any(role in r for r in s.get('roles', [])))
                and not drop & set(s['sample'].get('moves') or [])][:3]
        out = []
        for s in rows:
            m = s['member']
            out.append({
                'source': s['source_label'], 'roles': s.get('roles', []), 'sample': compact_sample(s['sample']),
                'readable': readable(m),
            })
        if not out:
            try:                                    # 답에 쓸 한글 이름 (못 구하면 받은 그대로)
                items = {i['id']: i['name_ko'] for i in await self._items()}
                ko = (await self.party_names([{'pokemon': mega[0] if mega else pokemon, 'item': item_id or ''}]))[0] or pokemon
            except (httpx.HTTPError, KeyError, ToolError):
                items, ko = {}, pokemon
            without_ko = '·'.join(without) + ' 없는' if without else None
            what = ' '.join(x for x in (ko, items.get(item_id, item), role, without_ko) if x)
            return [{'result': f'{what} 샘플 없음',
                     'none': {'pokemon': ko, 'item': items.get(item_id, item), 'role': ' '.join(x for x in (without_ko, role) if x)}}]
        return {'shapes': d.get('shapes'), 'samples': out}

    async def tool_search_teams(self, pokemon: str | None = None, format: str | None = None,
                                source: str | None = None, page: int = 1) -> dict:
        d = await self._get('teams/', {'q': pokemon, 'format': self._fmt(format), 'source': source,
                                       'page': page, 'size': 5})
        return {'count': d['count'], 'teams': [{
            'id': t['id'], 'title': t['title'], 'source': t['source_label'],
            **{k: t[k] for k in ('event', 'placement') if t[k]},
            'members': [m['name_ko'] for m in t['members']]} for t in d['results']]}

    async def tool_get_team(self, id: int) -> dict:
        t = await self._get(f'teams/{int(id)}/')
        return {
            'id': t['id'], 'title': t['title'], 'source': t['source_label'],
            # sample: propose_party·check_party에 그대로 넣는 육성형 (ID), name: 답변에 쓰는 한글 이름 (기술 등을 모델이 번역해 지어내지 않게)
            'members': [{
                'sample': compact_sample({
                    'pokemon': m['base'], 'item': (m['item'] or {}).get('id', ''), 'ability': m['base_ability'],
                    'nature': (m['nature'] or {}).get('id', ''), 'sp': m['sp'],
                    'moves': [x['id'] for x in m['moves'] if x]}),
                'name': readable(m),
                **({'brought': m['brought'], 'lead': m['lead']} if m['brought'] is not None else {}),
            } for m in t['members']],
        }

    async def tool_get_speed_tiers(self, format: str | None = None, top: int = 50,
                                   min_speed: int | None = None, max_speed: int | None = None) -> list[str]:
        d = await self._get('speed/', {'format': self._fmt(format), 'top': min(max(int(top or 50), 1), 200)})
        lines = []
        for row in d['rows']:
            if (min_speed is not None and row['speed'] < min_speed) or (max_speed is not None and row['speed'] > max_speed):
                continue
            lines.append(f"{row['speed']}: " + ', '.join(f"{e['pokemon']['name_ko']}({e['label']})" for e in row['entries']))
        return lines[:80] or ['해당 구간에 포켓몬 없음']

    async def _post(self, path: str, body: dict) -> dict:
        r = await self.client.post(path, json=body)
        _raise_input_error(r)
        return r.json()

    async def tool_check_party(self, members: list[dict], candidates: list[dict] | None = None,
                               format: str | None = None) -> dict:
        d = await self._post('party/check/', {'members': members, 'candidates': candidates or [],
                                              'format': self._fmt(format)})
        # 후보 비교를 부를 때는 지금 파티 점검은 이미 본 것이므로 비교 결과만 (짧게)
        return {'candidates': d['candidates']} if candidates and 'candidates' in d else d

    async def tool_find_partners(self, pokemon: list[str] | str, format: str | None = None, top: int = 8) -> dict:
        keys = [pokemon] if isinstance(pokemon, str) else list(pokemon or [])
        d = await self._get('partners/', {'pokemon': ','.join(keys[:3]), 'format': self._fmt(format),
                                          'top': min(max(int(top or 8), 1), 30)})
        return {'with': d['with'], 'teams': d['teams'],
                'partners': [{k: p[k] for k in ('name_ko', 'count', 'pct')} for p in d['partners']]}

    async def tool_find_threats(self, members: list[dict], format: str | None = None, top: int = 40) -> dict:
        d = await self._post('threats/', {'members': [{'pokemon': m.get('pokemon'), 'item': m.get('item', '')}
                                                       for m in members or []],
                                          'format': self._fmt(format), 'top': min(max(int(top or 40), 1), 100)})
        return {**d, 'threats': d['threats'][:5]}

    async def _validate(self, sample: dict) -> dict:
        r = await self.client.post('validate/', json=sample)
        r.raise_for_status()
        return r.json()

    async def tool_validate_set(self, **sample) -> dict:
        return await self._validate(sample)

    async def tool_propose_party(self, members: list[dict]) -> dict:
        if not 1 <= len(members or []) <= 6:
            raise ToolError('멤버는 1~6마리')
        problems = []
        for kind, key in (('포켓몬', 'pokemon'), ('도구', 'item')):          # 같은 포켓몬·같은 도구는 하나씩
            seen = [m.get(key) for m in members if m.get(key)]
            dup = sorted({x for x in seen if seen.count(x) > 1})
            if dup:
                problems.append({'slot': 'party', 'errors': [f'같은 {kind} 중복: {", ".join(dup)}']})
        for i, m in enumerate(members, 1):
            v = await self._validate(m)
            errs = [c['message'] for c in v['checks'] if c['level'] == 'error']
            if errs:
                problems.append({'slot': i, 'pokemon': m.get('pokemon'), 'errors': errs})
        if problems:
            return {'shown': False, 'problems': problems, 'hint': '고쳐서 다시 propose_party를 부를 것'}
        self.proposed = [{
            'pokemon': m['pokemon'], 'item': m.get('item', ''), 'ability': m.get('ability', ''),
            'nature': m.get('nature', ''), 'sp': {s: int((m.get('sp') or {}).get(s, 0) or 0) for s in STATS},
            'moves': ([*(m.get('moves') or []), '', '', '', ''])[:4],
        } for m in members]
        return {'shown': True, 'count': len(members)}


def _raise_input_error(r: httpx.Response) -> None:
    """back이 404(없는 ID)·400(잘못된 입력)을 주면 모델에게 돌려줄 오류로."""
    if r.status_code in (400, 404):
        try:
            detail = r.json()
        except ValueError:
            detail = r.text
        raise ToolError(detail.get('detail', detail) if isinstance(detail, dict) and 'detail' in detail else str(detail))
    r.raise_for_status()
