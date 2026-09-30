"""프론트(Vue)용 조회 API."""
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.api.common import FORMATS, format_key, get_format, get_ruleset, label, names, pokemon_brief
from apps.dex.ids import to_id
from apps.dex.models import Move, Pokemon
from apps.dex.typechart import matchups
from apps.meta.models import SP_STATS, UsageStat


def latest_usage(ruleset, fmt: str, source: str = 'opgg'):
    """가장 최근 스냅샷의 사용률 queryset (시즌·날짜 기준)."""
    qs = UsageStat.objects.filter(ruleset=ruleset, format_key=format_key(ruleset, fmt), source=source)
    last = qs.order_by('-snapshot_date', '-season').values('snapshot_date', 'season').first()
    if not last:
        return qs.none(), None
    return qs.filter(**last), last


@api_view(['GET'])
def ranking(request):
    """랭킹(메타): 인게임 픽률 순위와 직전 시즌 대비 변동.

    GET /api/ranking/?format=doubles&limit=50
    """
    rs, fmt = get_ruleset(request), get_format(request)
    limit = int(request.query_params.get('limit', 0)) or None
    qs, last = latest_usage(rs, fmt)
    rows = qs.order_by('rank')[:limit] if limit else qs.order_by('rank')
    return Response({
        'ruleset': rs.id, 'format': fmt,
        'season': last and last['season'], 'snapshot_date': last and last['snapshot_date'],
        'items': [{
            'rank': u.rank, 'prev_rank': u.prev_rank, 'change': u.rank_change,
            'is_new': u.prev_rank is None,
            'pokemon': pokemon_brief(rs.id, u.pokemon_key),
        } for u in rows],
    })


STAT_FIELDS = (('hp', 'hp'), ('atk', 'atk'), ('def', 'defense'), ('spa', 'spa'), ('spd', 'spd'), ('spe', 'spe'))


def stats_of(p: Pokemon) -> dict:
    return {k: getattr(p, f) for k, f in STAT_FIELDS}


def usage_ranks(ruleset, fmt: str) -> dict[str, UsageStat]:
    qs, _ = latest_usage(ruleset, fmt)
    return {u.pokemon_key: u for u in qs}


@api_view(['GET'])
def pokemon_list(request):
    """포켓몬 목록 (메가 폼 제외, 메가 가능 여부 표시). 검색·필터·정렬은 화면에서.

    GET /api/pokemon/?format=doubles
    """
    rs, fmt = get_ruleset(request), get_format(request)
    ranks = usage_ranks(rs, fmt)
    all_p = list(Pokemon.objects.filter(ruleset=rs))
    mega_bases = {to_id(p.base_species) for p in all_p if p.is_mega}
    items = []
    for p in all_p:
        if p.is_mega:
            continue
        u = ranks.get(p.showdown_id)
        items.append({
            'id': p.showdown_id, 'num': p.num, 'name': p.name, 'name_ko': p.name_ko or p.name,
            'types': [t for t in (p.type1, p.type2) if t], 'stats': stats_of(p), 'bst': p.bst,
            'has_mega': p.showdown_id in mega_bases,
            'rank': u.rank if u else None, 'change': u.rank_change if u else None,
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


def usage_detail(ruleset, u: UsageStat | None) -> dict | None:
    if not u:
        return None
    out = {'rank': u.rank, 'prev_rank': u.prev_rank, 'change': u.rank_change,
           'move': [], 'item': [], 'ability': [], 'nature': [], 'spread': []}
    for d in u.details.all():
        if d.kind not in out:
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
