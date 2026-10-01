"""프론트(Vue)용 조회 API."""
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.api.common import FORMATS, format_key, get_format, get_ruleset, label, names, pokemon_brief
from apps.dex.ids import to_id
from apps.dex.models import Item, Move, Nature, Pokemon
from apps.dex.stats import SP_MAX_TOTAL, STATS, calc_stats, sp_problems
from apps.dex.typechart import TYPE_KO, TYPES, chart, defense_profile, matchups
from apps.meta.models import SP_STATS, RankSnapshot, Team, TeamMember, UsageStat


def latest_usage(ruleset, fmt: str, source: str = 'opgg'):
    """가장 최근 스냅샷의 사용률 queryset (시즌·날짜 기준)."""
    qs = UsageStat.objects.filter(ruleset=ruleset, format_key=format_key(ruleset, fmt), source=source)
    last = qs.order_by('-snapshot_date', '-season').values('snapshot_date', 'season').first()
    if not last:
        return qs.none(), None
    return qs.filter(**last), last


def rank_board(ruleset, fmt: str) -> dict:
    """최신 순위 스냅샷 + 직전 스냅샷 대비 변동.

    {'captured_at', 'compared_to', 'season', 'rows': {pokemon_key: {rank, prev_rank, change, season_change}}}
    직전 스냅샷에 없던 포켓몬은 prev_rank/change가 None.
    """
    qs = RankSnapshot.objects.filter(ruleset=ruleset, format_key=format_key(ruleset, fmt), source='opgg')
    times = list(qs.order_by('-captured_at').values_list('captured_at', flat=True).distinct()[:2])
    if not times:
        return {'captured_at': None, 'compared_to': None, 'season': None, 'rows': {}}
    prev = {r.pokemon_key: r.rank for r in qs.filter(captured_at=times[1])} if len(times) > 1 else {}
    rows, season = {}, None
    for r in qs.filter(captured_at=times[0]).order_by('rank'):
        season = r.season
        p = prev.get(r.pokemon_key)
        rows[r.pokemon_key] = {'rank': r.rank, 'prev_rank': p, 'change': None if p is None else p - r.rank,
                               'season_change': r.season_change}
    return {'captured_at': times[0], 'compared_to': times[1] if len(times) > 1 else None,
            'season': season, 'rows': rows}


@api_view(['GET'])
def ranking(request):
    """랭킹: 인게임 픽률 순위와 직전 스냅샷(전날 갱신) 대비 변동.

    GET /api/ranking/?format=doubles&limit=50
    """
    rs, fmt = get_ruleset(request), get_format(request)
    limit = int(request.query_params.get('limit', 0)) or None
    board = rank_board(rs, fmt)
    rows = list(board['rows'].items())[:limit]
    return Response({
        'ruleset': rs.id, 'format': fmt, 'season': board['season'],
        'captured_at': board['captured_at'], 'compared_to': board['compared_to'],
        'items': [{**r, 'is_new': board['compared_to'] is not None and r['prev_rank'] is None,
                   'pokemon': pokemon_brief(rs.id, key)} for key, r in rows],
    })


STAT_FIELDS = (('hp', 'hp'), ('atk', 'atk'), ('def', 'defense'), ('spa', 'spa'), ('spd', 'spd'), ('spe', 'spe'))


def stats_of(p: Pokemon) -> dict:
    return {k: getattr(p, f) for k, f in STAT_FIELDS}




@api_view(['GET'])
def pokemon_list(request):
    """포켓몬 목록 (메가 폼은 기본 폼의 megas에). 검색·필터·정렬은 화면에서.

    GET /api/pokemon/?format=doubles
    """
    rs, fmt = get_ruleset(request), get_format(request)
    ranks = rank_board(rs, fmt)['rows']
    all_p = list(Pokemon.objects.filter(ruleset=rs).order_by('showdown_id'))
    megas = {}   # 기본 폼 id → 메가 폼 목록 (메가스톤 id 포함: 샘플은 기본 폼 + 메가스톤으로 저장)
    for p in all_p:
        if p.is_mega:
            megas.setdefault(to_id(p.base_species), []).append({
                'id': p.showdown_id, 'name': p.name, 'name_ko': p.name_ko or p.name,
                'types': [t for t in (p.type1, p.type2) if t], 'stats': stats_of(p), 'bst': p.bst,
                'item': to_id(p.required_item),
            })
    items = []
    for p in all_p:
        if p.is_mega:
            continue
        u = ranks.get(p.showdown_id)
        items.append({
            'id': p.showdown_id, 'num': p.num, 'name': p.name, 'name_ko': p.name_ko or p.name,
            'types': [t for t in (p.type1, p.type2) if t], 'stats': stats_of(p), 'bst': p.bst,
            'has_mega': p.showdown_id in megas, 'megas': megas.get(p.showdown_id, []),
            'rank': u['rank'] if u else None, 'change': u['change'] if u else None,
        })
    return Response({'ruleset': rs.id, 'format': fmt, 'count': len(items), 'items': items})


def form_detail(p: Pokemon) -> dict:
    types = [t for t in (p.type1, p.type2) if t]
    return {
        'id': p.showdown_id, 'name': p.name, 'name_ko': p.name_ko or p.name, 'forme': p.forme,
        'is_mega': p.is_mega, 'required_item': p.required_item, 'types': types,
        'stats': stats_of(p), 'bst': p.bst, 'weight_kg': p.weight_kg,
        'abilities': [{
            'id': pa.ability.showdown_id, 'name': pa.ability.name, 'name_ko': pa.ability.name_ko or pa.ability.name,
            'desc': pa.ability.short_desc, 'slot': pa.slot, 'hidden': pa.slot == 'H',
        } for pa in p.ability_slots.select_related('ability').order_by('slot')],
        'matchups': matchups(types),
    }


MIN_PCT = 1.0     # SP 배분·성격은 경우의 수가 많아 1% 미만은 생략


def usage_detail(ruleset, u: UsageStat | None) -> dict | None:
    if not u:
        return None
    out = {'rank': u.rank, 'prev_rank': u.prev_rank, 'change': u.rank_change,
           'move': [], 'item': [], 'ability': [], 'nature': [], 'spread': []}
    for d in u.details.all():
        if d.kind not in out:
            continue
        if d.kind in ('spread', 'nature') and d.pct < MIN_PCT:
            continue
        if d.kind == 'spread':
            out['spread'].append({'sp': dict(zip(SP_STATS, map(int, d.target_key.split('/')))), 'pct': d.pct})
            continue
        row = label(ruleset.id, d.kind, d.target_key) or {'id': d.target_key}
        if d.kind == 'nature':
            n = names(ruleset.id)['nature'].get(d.target_key, {})
            row.update(plus=n.get('plus_stat') or None, minus=n.get('minus_stat') or None)
        out[d.kind].append({**row, 'pct': d.pct})
    return out


@api_view(['GET'])
def pokemon_detail(request, sid: str):
    """포켓몬 상세: 폼(기본 + 메가)별 정보, 싱글·더블 사용률, 배우는 기술.

    GET /api/pokemon/garchomp/  (메가 폼 ID를 넣으면 기본 폼 기준으로 응답)
    """
    rs = get_ruleset(request)
    p = Pokemon.objects.filter(ruleset=rs, showdown_id=sid).first()
    if not p:
        raise NotFound(f'{sid}: 이 레귤레이션에 없는 포켓몬')
    if p.is_mega:
        p = Pokemon.objects.get(ruleset=rs, showdown_id=to_id(p.base_species))
    megas = Pokemon.objects.filter(ruleset=rs, base_species=p.base_species, is_mega=True).order_by('showdown_id')
    usage = {}
    for fmt in FORMATS:
        u = UsageStat.objects.filter(pk__in=latest_usage(rs, fmt)[0].filter(pokemon_key=p.showdown_id)) \
            .prefetch_related('details').first()
        usage[fmt] = usage_detail(rs, u)
    learnset = [{
        'id': m.showdown_id, 'name': m.name, 'name_ko': m.name_ko or m.name, 'type': m.type,
        'category': m.category, 'power': m.power or None, 'accuracy': m.accuracy, 'pp': m.pp,
    } for m in Move.objects.filter(learners__pokemon=p).order_by('name_ko')]
    return Response({
        'ruleset': rs.id, 'id': p.showdown_id, 'num': p.num, 'name_ko': p.name_ko or p.name,
        'forms': [form_detail(f) for f in (p, *megas)],
        'usage': usage, 'learnset': learnset,
    })


SOURCE_LABEL = dict(Team.SOURCES)


def team_title(t: Team) -> str:
    if t.source == 'showdown_replay':
        return f'{t.player or "익명"}의 리플레이 파티'
    return t.name or f'{SOURCE_LABEL.get(t.source, t.source)} #{t.pk}'


def team_summary(t: Team, members: list[TeamMember]) -> dict:
    return {
        'id': t.pk, 'title': team_title(t), 'source': t.source, 'source_label': SOURCE_LABEL.get(t.source, t.source),
        'format': t.format_key.rsplit('_', 1)[-1], 'player': t.player, 'date': t.played_on,
        'rating': t.rating, 'result': t.result or None, 'external_id': t.external_id,
        'members': [pokemon_brief(t.ruleset_id, m.pokemon_key) for m in members],
    }


class TeamPagination(PageNumberPagination):
    page_size = 8
    page_size_query_param = 'size'
    max_page_size = 50


@api_view(['GET'])
def team_list(request):
    """파티 목록. GET /api/teams/?format=doubles&source=showdown_replay&q=망나뇽&page=2

    format: singles / doubles (생략 시 전체), source: opgg_replica / showdown_replay (생략 시 전체),
    q: 포함 포켓몬 이름(한글/영문) 일부
    """
    rs = get_ruleset(request)
    qs = Team.objects.filter(ruleset=rs).order_by('-played_on', '-id')
    fmt = request.query_params.get('format')
    if fmt:
        qs = qs.filter(format_key=format_key(rs, get_format(request)))
    if src := request.query_params.get('source'):
        qs = qs.filter(source=src)
    if q := request.query_params.get('q', '').strip():
        keys = [sid for sid, p in names(rs.id)['pokemon'].items()
                if q in (p['name_ko'] or '') or q.lower() in p['name'].lower()]
        qs = qs.filter(members__pokemon_key__in=keys).distinct()
    pager = TeamPagination()
    page = pager.paginate_queryset(qs.prefetch_related('members'), request)
    return pager.get_paginated_response([team_summary(t, list(t.members.all())) for t in page])


def member_detail(t: Team, m: TeamMember) -> dict:
    rid = t.ruleset_id
    nature = names(rid)['nature'].get(m.nature_key)
    return {
        'slot': m.slot, 'pokemon': pokemon_brief(rid, m.pokemon_key),
        'item': label(rid, 'item', m.item_key), 'ability': label(rid, 'ability', m.ability_key),
        'nature': nature and {'id': nature['id'], 'name_ko': nature['name_ko'],
                              'plus': nature['plus_stat'] or None, 'minus': nature['minus_stat'] or None},
        'sp': {s: getattr(m, f'sp_{s}') for s in SP_STATS},
        'moves': [label(rid, 'move', k) for k in m.moves],
        'is_mega': m.is_gimmick_user, 'brought': m.brought, 'lead': m.lead,
    }


def weakness_table(members: list[dict]) -> dict:
    """파티 약점표: 멤버별 18타입 배율 + 타입별 약점(×2 이상) 마리 수."""
    rows = [{'pokemon': m['pokemon']['id'], 'cells': defense_profile(m['pokemon']['types'])} for m in members]
    return {'types': TYPES, 'rows': rows,
            'weak_count': {t: sum(r['cells'][t] > 1 for r in rows) for t in TYPES}}


@api_view(['GET'])
def team_detail(request, pk: int):
    """파티 상세: 멤버 육성 정보 + 약점표. GET /api/teams/123/"""
    t = Team.objects.filter(pk=pk).prefetch_related('members').first()
    if not t:
        raise NotFound('없는 파티')
    ms = list(t.members.all())
    members = [member_detail(t, m) for m in ms]
    return Response({**team_summary(t, ms), 'members': members, 'weakness': weakness_table(members)})


@api_view(['GET'])
def options(request):
    """샘플 제작·파티 빌딩용 선택지: 도구, 성격, 타입(한글), 타입 상성표. GET /api/options/"""
    rs = get_ruleset(request)
    n = names(rs.id)
    return Response({
        'ruleset': rs.id,
        'items': [{'id': i['showdown_id'], 'name': i['name'], 'name_ko': i['name_ko'] or i['name'],
                   'mega_from': i['mega_from'] or None, 'mega_to': i['mega_to'] or None}
                  for i in sorted(n['item'].values(), key=lambda x: x['name_ko'] or x['name'])],
        'natures': [{'id': x['id'], 'name': x['name'], 'name_ko': x['name_ko'],
                     'plus': x['plus_stat'] or None, 'minus': x['minus_stat'] or None}
                    for x in n['nature'].values()],
        'types': [{'id': t, 'name_ko': TYPE_KO[t]} for t in TYPES],
        'typechart': {a: {d: m for (a2, d), m in chart().items() if a2 == a} for a in TYPES},
    })


@api_view(['POST'])
def validate_set(request):
    """샘플(육성형) 적합성 검사 + 실수치. POST /api/validate/

    body: {"pokemon": "garchomp", "item": "lifeorb", "ability": "roughskin", "nature": "jolly",
           "sp": {"hp": 2, "atk": 32, "spe": 32}, "moves": ["earthquake", "dragonclaw"]}
    """
    rs = get_ruleset(request)
    body = request.data
    checks = []

    def add(level, msg):
        checks.append({'level': level, 'message': msg})

    p = Pokemon.objects.filter(ruleset=rs, showdown_id=body.get('pokemon', '')).first()
    if not p:
        return Response({'valid': False, 'checks': [{'level': 'error', 'message': '포켓몬을 선택하세요'}],
                         'stats': None})
    base_p = Pokemon.objects.get(ruleset=rs, showdown_id=to_id(p.base_species)) if p.is_mega else p

    abilities = {pa.ability.showdown_id: pa.ability for pa in base_p.ability_slots.select_related('ability')}
    ability = body.get('ability') or ''
    if not ability:
        add('warn', '특성이 비어 있음')
    elif ability not in abilities:
        add('error', f'{base_p.name_ko}은(는) 이 특성을 가질 수 없음')

    item_key = body.get('item') or ''
    item = Item.objects.filter(ruleset=rs, showdown_id=item_key).first() if item_key else None
    if item_key and not item:
        add('error', '이 레귤레이션에서 쓸 수 없는 도구')
    elif item and item.mega_from and to_id(item.mega_from) != base_p.showdown_id:
        add('error', f'{item.name_ko}은(는) {base_p.name_ko}의 메가스톤이 아님')
    if not ability or ability in abilities:
        if not checks or all(c['level'] != 'error' for c in checks):
            add('ok', '특성 · 도구 조합 합법')

    nature = Nature.objects.filter(id=body.get('nature') or '').first()
    if not nature:
        add('warn', '성격이 비어 있음 (무보정으로 계산)')

    sp = {s: int((body.get('sp') or {}).get(s, 0) or 0) for s in STATS}
    problems = sp_problems(sp)
    for msg in problems:
        add('error', msg)
    left = SP_MAX_TOTAL - sum(sp.values())
    if not problems:
        add('ok', f'SP {SP_MAX_TOTAL} 모두 배분됨') if left == 0 else add('warn', f'SP {left}포인트 남음')

    moves = [m for m in (body.get('moves') or []) if m]
    learnable = set(Move.objects.filter(learners__pokemon=base_p).values_list('showdown_id', flat=True))
    bad = [m for m in moves if m not in learnable]
    if bad:
        add('error', f'배울 수 없는 기술: {", ".join(label(rs.id, "move", m)["name_ko"] for m in bad)}')
    if len(set(moves)) != len(moves):
        add('error', '같은 기술이 중복됨')
    if len(moves) < 4:
        add('error', f'기술 칸 {4 - len(moves)}개가 비어 있음')
    elif not bad and len(set(moves)) == 4:
        add('ok', '기술 4개 모두 배울 수 있음')

    stats = calc_stats(stats_of(p), sp, nature and nature.plus_stat or None, nature and nature.minus_stat or None)
    return Response({'valid': all(c['level'] != 'error' for c in checks), 'checks': checks, 'stats': stats})
