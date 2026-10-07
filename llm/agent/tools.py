"""에이전트 도구: back API를 불러 사실(종족값·기술·사용률·파티)을 조회한다.

도구 설명·결과는 짧게 유지한다 (로컬 4B 모델의 문맥 길이·학습 길이 때문). 배우는 기술 전체 같은 긴 목록은 요청할 때만.
"""
import json

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
                            'role로 원하는 형태(막이, 특수 딜러, 서포터 등)만. sample은 propose_party에 그대로.',
          {'pokemon': STR, 'format': FORMAT, 'role': STR}, ('pokemon',)),
    _tool('search_teams', '실제 파티 목록(OP.GG 상위·대회 팀). pokemon을 주면 그 포켓몬이 든 파티만.',
          {'pokemon': STR, 'format': FORMAT}),
    _tool('get_team', '파티 상세: 멤버 육성형(sample은 propose_party에 그대로).', {'id': INT}, ('id',)),
    _tool('check_party', '파티 점검: 멤버별 역할·SP·스피드, 역할 수·물리/특수 딜러 수·메가진화 포켓몬 수, '
                         '2마리 이상 겹치는 약점과 받아 줄 멤버, 경고. candidates(최대 3)를 주면 한 마리씩 넣어 본 비교.',
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
        return hits[:10] or [{'result': f'"{query}"에 맞는 포켓몬 없음'}]

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

    async def tool_search_samples(self, pokemon: str, format: str | None = None, source: str | None = None,
                                  role: str | None = None) -> dict | list:
        """샘플 3개 + 그 포켓몬 샘플 전체의 형태 분포. role을 주면 그 역할(예: 막이, 특수 딜러) 샘플만."""
        d = await self._get('samples/', {'q': pokemon, 'format': self._fmt(format), 'source': source,
                                         'size': 30 if role else 3})
        rows = [s for s in d['results'] if not role or any(role in r for r in s.get('roles', []))][:3]
        out = []
        for s in rows:
            m = s['member']
            out.append({
                'source': s['source_label'], 'roles': s.get('roles', []), 'sample': compact_sample(s['sample']),
                'readable': f"{m['pokemon']['name_ko']} @ {(m['item'] or {}).get('name_ko', '-')} / "
                            f"{(m['ability'] or {}).get('name_ko', '-')} / {(m['nature'] or {}).get('name_ko', '-')} / "
                            f"SP {_sp_text(m['sp'])} / " + ', '.join(x['name_ko'] for x in m['moves'] if x),
            })
        if not out:
            return [{'result': f'"{pokemon}" ' + (f'{role} ' if role else '') + '샘플 없음'}]
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
            # sample: propose_party·check_party에 그대로 넣는 육성형 (ID), name: 답변에 쓰는 "이름 @ 도구" (짧게)
            'members': [{
                'sample': compact_sample({
                    'pokemon': m['base'], 'item': (m['item'] or {}).get('id', ''), 'ability': m['base_ability'],
                    'nature': (m['nature'] or {}).get('id', ''), 'sp': m['sp'],
                    'moves': [x['id'] for x in m['moves'] if x]}),
                'name': f"{m['pokemon']['name_ko']} @ {(m['item'] or {}).get('name_ko', '-')}",
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
