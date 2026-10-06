"""에이전트 도구: back API를 불러 사실(종족값·기술·사용률·파티)을 조회한다.

도구 결과는 모델이 읽을 만큼만 줄여서 돌려준다 (배우는 기술 전체 같은 긴 목록은 요청할 때만).
"""
import json

import httpx

STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
FORMAT = {'type': 'string', 'enum': ['singles', 'doubles'], 'description': '생략하면 지금 화면의 싱글/더블'}
SAMPLE = {
    'type': 'object',
    'description': '육성형. 모든 값은 영문 ID (도구 결과에 나온 id)',
    'properties': {
        'pokemon': {'type': 'string', 'description': '메가진화 전 폼 ID (메가는 메가스톤을 item에)'},
        'item': {'type': 'string'},
        'ability': {'type': 'string'},
        'nature': {'type': 'string'},
        'sp': {'type': 'object', 'description': 'hp/atk/def/spa/spd/spe. 능력치마다 0~32, 합계 66',
               'properties': {s: {'type': 'integer'} for s in STATS}},
        'moves': {'type': 'array', 'items': {'type': 'string'}, 'description': '기술 4개'},
    },
    'required': ['pokemon', 'item', 'ability', 'nature', 'sp', 'moves'],
}

TOOLS = [
    {
        'name': 'search_pokemon',
        'description': '포켓몬을 이름(한글/영문) 일부로 찾는다. ID·타입·종족값·픽률 순위·메가 폼을 돌려준다. '
                       '다른 도구에 넣을 포켓몬 ID를 모를 때 먼저 쓴다.',
        'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'format': FORMAT},
                         'required': ['query']},
    },
    {
        'name': 'get_pokemon',
        'description': '포켓몬 상세: 폼(기본·메가)별 타입·종족값·특성, 싱글/더블 사용률 상위(기술·도구·특성·성격·SP 배분). '
                       'include_learnset=true면 배울 수 있는 기술 전체도 준다 (샘플을 새로 짤 때만).',
        'input_schema': {'type': 'object', 'properties': {
            'id': {'type': 'string', 'description': '포켓몬 ID (search_pokemon 결과의 id)'},
            'format': FORMAT, 'include_learnset': {'type': 'boolean'}}, 'required': ['id']},
    },
    {
        'name': 'get_ranking',
        'description': '인게임 픽률 순위와 직전 스냅샷 대비 변동. 메타에서 많이 쓰이는 포켓몬을 볼 때.',
        'input_schema': {'type': 'object', 'properties': {
            'format': FORMAT, 'limit': {'type': 'integer', 'description': '기본 30'}}},
    },
    {
        'name': 'search_samples',
        'description': '공개 포켓몬 샘플(실제로 쓰인 육성형)을 3개까지 찾는다. 결과의 sample은 propose_party에 그대로 넣을 수 있다.',
        'input_schema': {'type': 'object', 'properties': {
            'pokemon': {'type': 'string', 'description': '포켓몬 이름(한글/영문) 일부'}, 'format': FORMAT,
            'source': {'type': 'string', 'enum': ['opgg_sample', 'vgcpastes_team', 'opgg_team']}},
            'required': ['pokemon']},
    },
    {
        'name': 'search_teams',
        'description': '파티 샘플(OP.GG 상위 파티, 대회 팀, 리플레이)을 찾는다. pokemon을 주면 그 포켓몬이 들어간 파티만.',
        'input_schema': {'type': 'object', 'properties': {
            'pokemon': {'type': 'string'}, 'format': FORMAT, 'page': {'type': 'integer'},
            'source': {'type': 'string', 'enum': ['opgg_replica', 'vgcpastes', 'showdown_replay']}}},
    },
    {
        'name': 'get_team',
        'description': '파티 샘플 상세: 멤버 육성(도구·특성·성격·SP·기술)과 타입별 약점 마리 수. 리플레이는 선출·선봉도.',
        'input_schema': {'type': 'object', 'properties': {'id': {'type': 'integer'}}, 'required': ['id']},
    },
    {
        'name': 'analyze_party',
        'description': '파티의 방어 상성: 멤버별 타입·약점, 그리고 약점(×2 이상)이 1마리 이상인 공격 타입별 약점·반감·무효 마리 수. '
                       '메가스톤을 든 멤버는 메가 폼 타입으로 계산한다.',
        'input_schema': {'type': 'object', 'properties': {'members': {
            'type': 'array', 'items': {'type': 'object', 'properties': {
                'pokemon': {'type': 'string'}, 'item': {'type': 'string'}}, 'required': ['pokemon']}}},
            'required': ['members']},
    },
    {
        'name': 'get_speed_tiers',
        'description': '픽률 상위 포켓몬의 Lv50 스피드 실수치표 (최속·준속, 스카프·특성·랭크업 보정 포함). '
                       'min_speed/max_speed로 구간만 볼 수 있다.',
        'input_schema': {'type': 'object', 'properties': {
            'format': FORMAT, 'top': {'type': 'integer', 'description': '픽률 상위 몇 마리 (기본 50)'},
            'min_speed': {'type': 'integer'}, 'max_speed': {'type': 'integer'}}},
    },
    {
        'name': 'validate_set',
        'description': '육성형이 규칙에 맞는지(특성·도구·기술·SP) 검사하고 Lv50 실수치를 계산한다.',
        'input_schema': SAMPLE,
    },
    {
        'name': 'propose_party',
        'description': '사용자 화면에 추천 파티 카드를 띄운다 (사용자가 눌러서 파티에 넣을 수 있음). '
                       '모든 멤버가 validate_set 기준으로 합법이어야 표시되고, 아니면 문제를 돌려준다.',
        'input_schema': {'type': 'object', 'properties': {
            'members': {'type': 'array', 'items': SAMPLE, 'description': '1~6마리'}}, 'required': ['members']},
    },
]

# 화면에 보여 줄 진행 상태
STATUS = {
    'search_pokemon': '포켓몬 찾는 중', 'get_pokemon': '포켓몬 정보 확인 중', 'get_ranking': '픽률 순위 확인 중',
    'search_samples': '샘플 찾는 중', 'search_teams': '파티 샘플 찾는 중', 'get_team': '파티 확인 중',
    'analyze_party': '약점 계산 중', 'get_speed_tiers': '스피드표 확인 중', 'validate_set': '육성형 검사 중',
    'propose_party': '추천 파티 검사 중',
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
        if r.status_code == 404:
            raise ToolError(r.json().get('detail', '없음'))
        r.raise_for_status()
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
                       'abilities': [{'id': a['id'], 'name_ko': a['name_ko'], 'desc': a['desc']} for a in f['abilities']]}
                      for f in d['forms']],
            'format': fmt,
            'usage': u and {
                'rank': u['rank'],
                **{k: _top(u[k], 6) for k in ('move', 'item', 'ability', 'nature')},
                'spread': [{'sp': _sp_text(s['sp']), 'pct': s['pct']} for s in u['spread'][:4]],
            },
        }
        if include_learnset:
            out['learnset'] = [{k: m[k] for k in ('id', 'name_ko', 'type', 'category', 'power', 'accuracy')}
                               for m in d['learnset']]
        return out

    async def tool_get_ranking(self, format: str | None = None, limit: int = 30) -> dict:
        d = await self._get('ranking/', {'format': self._fmt(format), 'limit': min(max(int(limit or 30), 1), 100)})
        return {'format': d['format'], 'captured_at': d['captured_at'],
                'items': [{'rank': r['rank'], 'change': r['change'], 'id': r['pokemon']['id'],
                           'name_ko': r['pokemon']['name_ko']} for r in d['items']]}

    async def tool_search_samples(self, pokemon: str, format: str | None = None, source: str | None = None) -> list[dict]:
        d = await self._get('samples/', {'q': pokemon, 'format': self._fmt(format), 'source': source, 'size': 3})
        out = []
        for s in d['results']:
            m = s['member']
            out.append({
                'source': s['source_label'], 'sample': compact_sample(s['sample']),
                'readable': f"{m['pokemon']['name_ko']} @ {(m['item'] or {}).get('name_ko', '-')} / "
                            f"{(m['ability'] or {}).get('name_ko', '-')} / {(m['nature'] or {}).get('name_ko', '-')} / "
                            f"SP {_sp_text(m['sp'])} / " + ', '.join(x['name_ko'] for x in m['moves'] if x),
            })
        return out or [{'result': f'"{pokemon}" 샘플 없음'}]

    async def tool_search_teams(self, pokemon: str | None = None, format: str | None = None,
                                source: str | None = None, page: int = 1) -> dict:
        d = await self._get('teams/', {'q': pokemon, 'format': self._fmt(format), 'source': source,
                                       'page': page, 'size': 8})
        return {'count': d['count'], 'teams': [{
            'id': t['id'], 'title': t['title'], 'source': t['source_label'], 'rating': t['rating'],
            'event': t['event'] or None, 'placement': t['placement'] or None, 'result': t['result'],
            'members': [m['name_ko'] for m in t['members']]} for t in d['results']]}

    async def tool_get_team(self, id: int) -> dict:
        t = await self._get(f'teams/{int(id)}/')
        weak = {k: v for k, v in t['weakness']['weak_count'].items() if v >= 2}
        return {
            'id': t['id'], 'title': t['title'], 'source': t['source_label'], 'format': t['format'],
            'members': [{
                'pokemon': m['pokemon']['name_ko'], 'base_id': m['base'],
                'item': (m['item'] or {}).get('name_ko'), 'ability': (m['ability'] or {}).get('name_ko'),
                'nature': (m['nature'] or {}).get('name_ko'), 'sp': _sp_text(m['sp']),
                'moves': [x['name_ko'] for x in m['moves'] if x],
                **({'brought': m['brought'], 'lead': m['lead']} if m['brought'] is not None else {}),
            } for m in t['members']],
            'weak_types_2plus': weak,
        }

    async def tool_analyze_party(self, members: list[dict]) -> dict:
        opts = await self._get('options/', cache=True)
        chart = opts['typechart']
        type_ko = {t['id']: t['name_ko'] for t in opts['types']}
        by_id = {p['id']: p for p in (await self._get('pokemon/', {'format': self.format}, cache=True))['items']}
        rows = []
        for m in members[:6]:
            p = by_id.get(m.get('pokemon', ''))
            if not p:
                raise ToolError(f"없는 포켓몬 ID: {m.get('pokemon')}")
            form = next((x for x in p['megas'] if x['item'] and x['item'] == m.get('item')), None) or p
            rows.append({'name_ko': form['name_ko'], 'types': form['types'],
                         'cells': {a: _mul(chart, a, form['types']) for a in chart}})
        summary = {}      # 약점이 1마리 이상인 타입만, 약점 많은 순 (결과를 짧게)
        for a in sorted(chart, key=lambda a: -sum(r['cells'][a] > 1 for r in rows)):
            cnt = {'weak': sum(r['cells'][a] > 1 for r in rows), 'resist': sum(0 < r['cells'][a] < 1 for r in rows),
                   'immune': sum(r['cells'][a] == 0 for r in rows)}
            if cnt['weak']:
                summary[type_ko.get(a, a)] = cnt
        return {
            'members': [{'name_ko': r['name_ko'], 'types': [type_ko.get(t, t) for t in r['types']],
                         'weak_to': [type_ko.get(a, a) + f"×{r['cells'][a]:g}" for a in chart if r['cells'][a] > 1]}
                        for r in rows],
            'by_attack_type': summary,
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


def _mul(chart: dict, attack: str, types: list[str]) -> float:
    out = 1.0
    for d in types:
        out *= chart[attack].get(d, 1)
    return out
