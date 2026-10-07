"""파티 빌딩 판단용 API: 파티 점검(역할·밸런스·중복), 같이 쓰인 포켓몬, 위협 포켓몬.

LLM 코치가 "어떤 포지션이 비었는지", "누구와 같이 쓰이는지", "누가 약점을 찌르는지"를
지어내지 않고 데이터로 말하게 하려고 만든 것. 역할 기준은 CLAUDE.md의 정의를 따른다.

- 기점잡이: 벽·스텔스록·순풍·배턴터치 등으로 판을 깔아 주는 역할 (랭크업 딜러와 같이 씀)
- 랭크업 딜러: 용의춤·칼춤·나쁜음모 등으로 랭크를 올리는 메인 딜러
- 물리/특수/혼합 딜러: 공격·특공(과 스피드) 위주
- 막이: HP·방어·특방 위주. 상태이상·회복 기술이 있으면 "말려 죽이기"
"""
import math
from collections import Counter

from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.api.common import format_key, get_format, get_ruleset, names
from apps.api.views import latest_usage, norm_nature, rank_board, shown_key
from apps.dex.stats import calc_stat
from apps.dex.typechart import TYPE_KO, TYPES, defense_profile
from apps.meta.models import Team, TeamMember

# 기점잡이 기술 (벽·스텔스록 등 설치·순풍·트릭룸·배턴터치)
SETUP_SUPPORT = {'reflect', 'lightscreen', 'auroraveil', 'stealthrock', 'spikes', 'toxicspikes', 'stickyweb',
                 'tailwind', 'trickroom', 'batonpass'}
# 랭크업 기술 (공격·특공·스피드를 올림. 방어만 올리는 철벽 등은 막이 쪽이라 뺌)
BOOST = {'swordsdance', 'dragondance', 'nastyplot', 'calmmind', 'quiverdance', 'bulkup', 'shellsmash', 'bellydrum',
         'coil', 'shiftgear', 'agility', 'rockpolish', 'tidyup', 'growth', 'curse', 'howl'}
# 말려 죽이기 (상태이상·씨뿌리기·회복·강제 교체)
STALL = {'toxic', 'willowisp', 'leechseed', 'recover', 'roost', 'slackoff', 'softboiled', 'wish', 'synthesis',
         'moonlight', 'strengthsap', 'haze', 'whirlwind', 'roar'}
# 더블 보조 (역할을 정하지는 않고 태그로만)
DOUBLES_SUPPORT = {'fakeout', 'followme', 'ragepowder', 'helpinghand', 'icywind', 'electroweb', 'snarl', 'partingshot'}

BULK_SP = 40          # HP+방어+특방 SP가 이 이상이고
LOW_OFFENSE_SP = 16   # 공격·특공 SP가 각각 이 이하면 막이
MAX_MEGA = 2          # 메가스톤 3개 이상이면 경고 (배틀마다 메가진화는 한 번)
STAT_KO = {'hp': 'H', 'atk': 'A', 'def': 'B', 'spa': 'C', 'spd': 'D', 'spe': 'S'}


def _types(p: dict) -> list[str]:
    return [t for t in (p['type1'], p['type2']) if t]


def _base(rid: str, key: str) -> dict:
    from apps.dex.models import Pokemon
    p = Pokemon.objects.get(ruleset_id=rid, showdown_id=key)
    return {'hp': p.hp, 'atk': p.atk, 'def': p.defense, 'spa': p.spa, 'spd': p.spd, 'spe': p.spe}


def member_profile(rid: str, m: dict) -> dict:
    """육성형 하나 → 역할·공격 형태·투자·스피드."""
    n = names(rid)
    key = m.get('pokemon', '')
    if key not in n['pokemon']:
        raise ValidationError({'pokemon': f'없는 포켓몬 ID: {key}'})
    shown = shown_key(rid, key, m.get('item', ''))
    p = n['pokemon'][shown]
    base = _base(rid, shown)
    sp = {s: int((m.get('sp') or {}).get(s, 0) or 0) for s in STAT_KO}
    moves = [x for x in (m.get('moves') or []) if x]
    info = [n['move'].get(x) or {} for x in moves]
    phys = [x for x, i in zip(moves, info) if i.get('category') == 'Physical']
    spec = [x for x, i in zip(moves, info) if i.get('category') == 'Special']

    # 투자: SP가 비어 있으면 종족값으로 판단
    src = sp if any(sp.values()) else base
    offense = max(src['atk'], src['spa'])
    bulk = src['hp'] + src['def'] + src['spd']
    bulky = (bulk >= BULK_SP and offense <= LOW_OFFENSE_SP) if any(sp.values()) else bulk >= offense * 3 + src['spe']

    # 딜러라면 물리/특수/혼합 (기술 수와 투자로)
    style = None
    if not bulky and (phys or spec):
        if phys and spec and abs(src['atk'] - src['spa']) <= 8:     # 두 쪽 기술이 다 있고 투자도 비슷하면
            style = '혼합'
        elif len(phys) > len(spec) or (len(phys) == len(spec) and src['atk'] >= src['spa']):
            style = '물리'
        else:
            style = '특수'

    roles = []
    if set(moves) & SETUP_SUPPORT:
        roles.append('기점잡이')
    if bulky:
        roles.append('막이' + (' (말려 죽이기)' if set(moves) & STALL else ''))
    elif style and set(moves) & BOOST:
        roles.append(f'랭크업 딜러 ({style})')
    elif style:
        roles.append(f'{style} 딜러')
    if not roles:
        roles.append('보조')
    attack = '혼합' if phys and spec else '물리' if phys else '특수' if spec else '변화기만'

    nature = n['nature'].get(norm_nature(m.get('nature', ''))) or {}
    spe = calc_stat('spe', base['spe'], sp['spe'], nature.get('plus_stat') or None, nature.get('minus_stat') or None)
    tags = sorted({n['move'][x]['name_ko'] for x in moves if x in DOUBLES_SUPPORT | STALL | BOOST | SETUP_SUPPORT
                   and x in n['move']})
    return {
        'pokemon': key, 'name_ko': p['name_ko'] or p['name'], 'types': [TYPE_KO.get(t, t) for t in _types(p)],
        'roles': roles, 'attack': f'{attack} (물리기 {len(phys)}·특수기 {len(spec)})',
        'sp': ' '.join(f'{STAT_KO[s]}{v}' for s, v in sp.items() if v) or '없음 (종족값으로 판단)',
        'speed': spe, 'speed_note': '구애스카프 ×1.5' if m.get('item') == 'choicescarf' else None,
        'item': m.get('item', ''), 'mega': shown != key, 'key_moves': tags,
        '_types': _types(p), '_style': style,
    }


def party_check(rid: str, members: list[dict]) -> dict:
    profs = [member_profile(rid, m) for m in members]
    role_count = Counter(r.split(' (')[0] for p in profs for r in p['roles'])
    phys = sum(p['_style'] in ('물리', '혼합') for p in profs)      # 딜러만 셈 (막이·기점잡이의 견제기는 제외)
    spec = sum(p['_style'] in ('특수', '혼합') for p in profs)
    warnings = []
    dup_p = [k for k, c in Counter(m.get('pokemon') for m in members).items() if c > 1]
    dup_i = [k for k, c in Counter(m.get('item') for m in members if m.get('item')).items() if c > 1]
    n = names(rid)
    if dup_p:
        warnings.append('같은 포켓몬 중복: ' + ', '.join(n['pokemon'][k]['name_ko'] for k in dup_p))
    if dup_i:
        warnings.append('같은 도구 중복: ' + ', '.join((n['item'].get(k) or {}).get('name_ko') or k for k in dup_i))
    megas = sum(p['mega'] for p in profs)
    if megas > MAX_MEGA:
        warnings.append(f'메가스톤 {megas}개: 배틀마다 메가진화는 한 번이라 선출이 제한되고 메가 2마리를 같이 낼 수 있음')
    if len(members) >= 4 and (phys == 0 or spec == 0):
        warnings.append(('특수 딜러 없음 (물리 쪽만)' if phys else '물리 딜러 없음 (특수 쪽만)') if phys or spec else '딜러가 없음')
    profiles = [defense_profile(p['_types']) for p in profs]
    weak = {TYPE_KO[a]: sum(x[a] > 1 for x in profiles) for a in TYPES}
    weak = dict(sorted(((k, v) for k, v in weak.items() if v >= 2), key=lambda kv: -kv[1]))   # 2마리 이상만 (짧게)
    if weak and max(weak.values()) >= 3:
        warnings.append('약점 3마리 이상: ' + ', '.join(f'{k} {v}마리' for k, v in weak.items() if v >= 3))
    for p in profs:
        del p['_types'], p['_style']
    return {
        'members': profs,
        'summary': {
            'roles': dict(role_count), 'physical_attackers': phys, 'special_attackers': spec, 'mega_stones': megas,
            'weak_types_2plus': weak,
        },
        'warnings': warnings,
    }


@api_view(['POST'])
def check_party(request):
    """파티 점검: 멤버별 역할·공격 형태·스피드, 역할 수, 물리/특수, 메가 수, 중복, 약점.

    POST /api/party/check/  body: {"members": [육성형 …]}
    """
    rs = get_ruleset(request)
    members = [m for m in (request.data.get('members') or []) if m and m.get('pokemon')]
    if not members:
        raise ValidationError({'members': '멤버가 비어 있음'})
    return Response(party_check(rs.id, members[:6]))


def team_queryset(rs, fmt: str | None):
    """같이 쓰인 포켓몬·위협 계산에 쓰는 파티: OP.GG 상위 파티 + VGCPastes 대회 팀 (합법만, 리플레이 제외)."""
    qs = Team.objects.filter(ruleset=rs, source__in=['opgg_replica', 'vgcpastes']).exclude(is_legal=False)
    return qs.filter(format_key=format_key(rs, fmt)) if fmt else qs


@api_view(['GET'])
def partners(request):
    """같이 쓰인 포켓몬: 주어진 포켓몬이 모두 든 실제 상위 파티에서 나머지 멤버의 등장 횟수.

    GET /api/partners/?pokemon=rillaboom,incineroar&format=doubles&top=12
    """
    rs, fmt = get_ruleset(request), get_format(request)
    keys = [k for k in request.query_params.get('pokemon', '').split(',') if k]
    n = names(rs.id)
    bad = [k for k in keys if k not in n['pokemon']]
    if not keys or bad:
        raise ValidationError({'pokemon': f'없는 포켓몬 ID: {bad}' if bad else 'pokemon이 비어 있음'})
    top = min(int(request.query_params.get('top', 12)), 30)
    teams = team_queryset(rs, fmt)
    for k in keys:
        teams = teams.filter(members__pokemon_key=k)
    ids = list(teams.values_list('id', flat=True).distinct())
    count = Counter()
    for tid, key in TeamMember.objects.filter(team_id__in=ids).values_list('team_id', 'pokemon_key'):
        if key not in keys:
            count[key] += 1
    total = len(ids)
    rank = rank_board(rs, fmt)['rows']
    return Response({
        'format': fmt, 'with': [n['pokemon'][k]['name_ko'] for k in keys], 'teams': total,
        'partners': [{'id': k, 'name_ko': n['pokemon'][k]['name_ko'], 'count': c, 'pct': round(c * 100 / total, 1),
                      'rank': (rank.get(k) or {}).get('rank')} for k, c in count.most_common(top)],
    })


@api_view(['POST'])
def threats(request):
    """위협 포켓몬: 픽률 상위 중 많이 쓰는 공격 기술(사용률 상위 10)의 타입으로 파티 여러 마리의 약점을 찌르는 포켓몬.

    POST /api/threats/  body: {"members": [{"pokemon", "item"}], "format": "singles", "top": 40}
    특성(부유·저수 등)에 의한 무효는 반영하지 않는다.
    """
    rs = get_ruleset(request)
    fmt = request.data.get('format') or 'doubles'
    if fmt not in ('singles', 'doubles'):
        raise ValidationError({'format': 'singles 또는 doubles'})
    n = names(rs.id)
    members = [m for m in (request.data.get('members') or []) if m and m.get('pokemon') in n['pokemon']]
    if not members:
        raise ValidationError({'members': '멤버가 비어 있음'})
    top = min(int(request.data.get('top', 40)), 100)
    shown = [shown_key(rs.id, m['pokemon'], m.get('item', '')) for m in members]
    member_types = [(n['pokemon'][k]['name_ko'], _types(n['pokemon'][k])) for k in shown]
    ranked = sorted(rank_board(rs, fmt)['rows'].items(), key=lambda x: x[1]['rank'])[:top]
    usage = {u.pokemon_key: u for u in latest_usage(rs, fmt)[0].filter(pokemon_key__in=[k for k, _ in ranked])
             .prefetch_related('details')}
    need = max(2, math.ceil(len(members) / 2))
    out = []
    for key, r in ranked:
        u = usage.get(key)
        if not u or key in {m['pokemon'] for m in members}:
            continue
        moves = [d.target_key for d in sorted(u.details.all(), key=lambda d: -d.pct) if d.kind == 'move'][:10]
        attacks = [(x, n['move'][x]) for x in moves if x in n['move'] and n['move'][x]['category'] != 'Status']
        hits = []
        for name_ko, types in member_types:
            best = max(attacks, key=lambda a: _mult(a[1]['type'], types), default=None)
            if best and _mult(best[1]['type'], types) >= 2:
                hits.append(f"{name_ko}←{best[1]['name_ko']}({TYPE_KO.get(best[1]['type'])} ×{_mult(best[1]['type'], types):g})")
        if len(hits) >= need:
            out.append({'id': key, 'name_ko': n['pokemon'][key]['name_ko'], 'rank': r['rank'],
                        'hits': len(hits), 'targets': hits})
    out.sort(key=lambda x: (-x['hits'], x['rank']))
    return Response({'format': fmt, 'checked_top': top, 'need_hits': need, 'threats': out[:8],
                     'note': '사용률 상위 공격 기술의 타입 기준. 특성에 의한 무효·대미지 크기는 반영하지 않음'})


def _mult(attack: str, types: list[str]) -> float:
    return defense_profile(types)[attack]
