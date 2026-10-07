"""파티 빌딩 판단용 API: 파티 점검(역할·밸런스·중복), 같이 쓰인 포켓몬, 위협 포켓몬.

LLM 코치가 "어떤 포지션이 비었는지", "누구와 같이 쓰이는지", "누가 약점을 찌르는지"를
지어내지 않고 데이터로 말하게 하려고 만든 것. 역할 기준은 CLAUDE.md의 정의를 따른다.

- 기점잡이(싱글)·서포터(더블): 벽·스텔스록·순풍·배턴터치, 더블은 속이기·날따름·트릭룸 등으로 판을 깔아 주는 역할
- 랭크업 딜러: 용의춤·칼춤·나쁜음모 등으로 랭크를 올리는 메인 딜러
- 물리/특수/혼합 딜러: 공격·특공(과 스피드) 위주
- 막이: HP·방어·특방 위주. 방어 쪽이면 물리막이, 특방 쪽이면 특수막이
- 내구조정: 딜러인데 HP·방어·특방에도 SP를 나눠 준 형태
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
# 더블 서포터 기술 (2개 이상이면 서포터)
DOUBLES_SUPPORT = {'fakeout', 'followme', 'ragepowder', 'helpinghand', 'icywind', 'electroweb', 'snarl', 'partingshot',
                   'encore', 'taunt', 'spore', 'sleeppowder', 'thunderwave', 'willowisp', 'coaching', 'wideguard',
                   'allyswitch', 'lifedew', 'pollenpuff'}

BULK_SP = 40          # HP+방어+특방 SP가 이 이상이고
LOW_OFFENSE_SP = 16   # 공격·특공 SP가 각각 이 이하면 막이
TUNED_BULK_SP = 16    # 딜러인데 HP+방어+특방 SP가 이 이상이면 내구조정
WASTED_SP = 8         # 공격(특공) SP가 이 이상인데 물리(특수)기가 없으면 경고
MAX_MEGA = 2          # 메가진화 포켓몬 3마리 이상이면 경고 (배틀마다 메가진화는 한 번)
COMMON_MOVE_PCT = 10  # 위협 계산: 이 사용률 이상인 기술만 찌르는 기술로 셈
STAT_KO = {'hp': 'H', 'atk': 'A', 'def': 'B', 'spa': 'C', 'spd': 'D', 'spe': 'S'}


def _types(p: dict) -> list[str]:
    return [t for t in (p['type1'], p['type2']) if t]


def _base(rid: str, key: str) -> dict:
    from apps.dex.models import Pokemon
    p = Pokemon.objects.get(ruleset_id=rid, showdown_id=key)
    return {'hp': p.hp, 'atk': p.atk, 'def': p.defense, 'spa': p.spa, 'spd': p.spd, 'spe': p.spe}


def member_profile(rid: str, m: dict, fmt: str = 'singles') -> dict:
    """육성형 하나 → 역할(하나 또는 딜러+기점잡이)·공격 형태·투자·스피드."""
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
    has_sp = any(sp.values())
    src = sp if has_sp else base
    offense = max(src['atk'], src['spa'])
    bulk = src['hp'] + src['def'] + src['spd']
    bulky = (bulk >= BULK_SP and offense <= LOW_OFFENSE_SP) if has_sp else bulk >= offense * 3 + src['spe']
    # 내구조정: 딜러인데 공격 외에 HP·방어·특방에도 SP를 나눠 준 형태
    tuned = has_sp and not bulky and offense >= 12 and bulk >= TUNED_BULK_SP
    # 역할은 SP 분배와 기술 배치로 정한다 (종족값은 안 봄). SP가 내구 위주여도 공격기가 3개 이상이고
    # 말려 죽이기·판 깔기 기술이 없으면 딜러(내구조정) — 예: 내구에 몰아 준 4공격기 메가리자몽Y
    if bulky and has_sp and len(phys) + len(spec) >= 3 and not set(moves) & (STALL | SETUP_SUPPORT):
        bulky, tuned = False, True

    # 딜러라면 물리/특수/혼합 (기술 수와 투자로)
    style = None
    if not bulky and (phys or spec):
        # 혼합: 두 쪽 기술 수가 같거나, 공격·특공 양쪽에 SP를 줬을 때
        if phys and spec and (len(phys) == len(spec) or (src['atk'] >= 12 and src['spa'] >= 12)):
            style = '혼합'
        elif len(phys) > len(spec) or (len(phys) == len(spec) and src['atk'] >= src['spa']):
            style = '물리'
        else:
            style = '특수'

    # 판을 까는 역할: 싱글은 기점잡이(벽·스텔스록·순풍 등), 더블은 서포터(속이기·날따름·순풍·트릭룸 등 2개 이상)
    if fmt == 'doubles':
        support = '서포터' if len(set(moves) & (DOUBLES_SUPPORT | SETUP_SUPPORT)) >= 2 else None
    else:
        support = '기점잡이' if set(moves) & SETUP_SUPPORT else None

    roles = []
    if support:
        roles.append(support)            # 막이와 같이 붙이지 않음 (판을 까는 쪽이 우선)
    if bulky and not support:
        if src['def'] >= src['spd'] + 8:
            wall = '물리막이'
        elif src['spd'] >= src['def'] + 8:
            wall = '특수막이'
        else:
            wall = '막이'
        roles.append(wall)
    elif style:
        tag = ', 내구조정' if tuned else ''
        if set(moves) & BOOST:
            roles.append(f'랭크업 딜러 ({style}{tag})')
        else:
            roles.append(f'{style} 딜러' + (' (내구조정)' if tuned else ''))
    if not roles:
        roles.append('보조')
    attack = '혼합' if phys and spec else '물리' if phys else '특수' if spec else '변화기만'

    # 공격 SP를 줬는데 그쪽 공격기가 없음 (샘플 정제용 경고)
    wasted = [label for stat, label, mv in (('atk', '공격', phys), ('spa', '특공', spec))
              if has_sp and sp[stat] >= WASTED_SP and not mv]

    nature = n['nature'].get(norm_nature(m.get('nature', ''))) or {}
    spe = calc_stat('spe', base['spe'], sp['spe'], nature.get('plus_stat') or None, nature.get('minus_stat') or None)
    # 모델이 읽는 결과는 짧게: 이름·역할·SP·스피드만 (타입·기술은 화면 상황과 다른 도구에 있음)
    out = {
        'pokemon': key, 'name_ko': p['name_ko'] or p['name'], 'roles': roles,
        'sp': ' '.join(f'{STAT_KO[s]}{v}' for s, v in sp.items() if v) or '없음 (종족값으로 판단)', 'speed': spe,
        '_types': _types(p), '_style': style, '_wasted': wasted, '_mega': shown != key,
    }
    if m.get('item') == 'choicescarf':
        out['speed_note'] = '구애스카프 ×1.5'
    return out


def party_check(rid: str, members: list[dict], fmt: str = 'singles') -> dict:
    profs = [member_profile(rid, m, fmt) for m in members]
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
    megas = sum(p['_mega'] for p in profs)
    if megas > MAX_MEGA:
        warnings.append(f'메가진화 포켓몬 {megas}마리: 배틀마다 메가진화는 한 번이라 선출이 제한되고 메가 2마리를 같이 낼 수 있음')
    if len(members) >= 4 and (phys == 0 or spec == 0):
        warnings.append(('특수 딜러 없음 (물리 쪽만)' if phys else '물리 딜러 없음 (특수 쪽만)') if phys or spec else '딜러가 없음')
    profiles = [defense_profile(p['_types']) for p in profs]
    weak = {TYPE_KO[a]: sum(x[a] > 1 for x in profiles) for a in TYPES}
    weak = dict(sorted(((k, v) for k, v in weak.items() if v >= 2), key=lambda kv: -kv[1]))   # 2마리 이상만 (짧게)
    # 겹치는 약점마다 그 공격을 반감·무효로 받아 줄 멤버 (없으면 빈 목록)
    ko2en = {v: k for k, v in TYPE_KO.items()}
    cover = {t: [p['name_ko'] for p, x in zip(profs, profiles) if x[ko2en[t]] < 1] for t in weak}
    if weak and max(weak.values()) >= 3:
        warnings.append('약점 3마리 이상: ' + ', '.join(f'{k} {v}마리' for k, v in weak.items() if v >= 3))
    for p in profs:
        if p['_wasted']:
            warnings.append(f"{p['name_ko']}: {'·'.join(p['_wasted'])} SP를 줬는데 그쪽 공격기가 없음")
        del p['_types'], p['_style'], p['_wasted'], p['_mega']
    return {
        'members': profs,
        'summary': {
            'roles': dict(role_count), 'physical_attackers': phys, 'special_attackers': spec, 'mega_pokemon': megas,
            'weak_types_2plus': weak, 'weak_cover': cover,
        },
        'warnings': warnings,
    }


def compare_candidates(rid: str, members: list[dict], candidates: list[dict], fmt: str, base: dict) -> list[dict]:
    """후보를 지금 파티에 한 마리씩 넣어 봤을 때: 역할·SP, 받아 주게 되는 약점 타입, 새로 늘어나는 약점 타입, 새 경고."""
    bw, bc = base['summary']['weak_types_2plus'], base['summary']['weak_cover']
    out = []
    for c in candidates:
        after = party_check(rid, members + [c], fmt)
        aw, ac = after['summary']['weak_types_2plus'], after['summary']['weak_cover']
        me = after['members'][-1]
        row = {'name_ko': me['name_ko'], 'roles': me['roles'], 'sp': me['sp'],
               'covers': [t for t in bw if t not in aw or len(ac[t]) > len(bc[t])],
               'new_weak': [f'{t} {v}마리' for t, v in aw.items() if v > bw.get(t, 0)]}
        new_warn = [w for w in after['warnings'] if w not in base['warnings'] and not w.startswith('약점 3마리 이상')]
        if new_warn:
            row['warnings'] = new_warn
        out.append(row)
    return out


@api_view(['POST'])
def check_party(request):
    """파티 점검: 멤버별 역할·SP·스피드, 역할 수, 물리/특수, 메가 수, 중복, 약점.
    candidates를 주면 후보를 한 마리씩 넣어 봤을 때의 비교도 (도구를 여러 번 부르지 않게).

    POST /api/party/check/  body: {"members": [육성형 …], "candidates": [육성형 …], "format": "doubles"}
    (더블이면 기점잡이 대신 서포터)
    """
    rs = get_ruleset(request)
    members = [m for m in (request.data.get('members') or []) if m and m.get('pokemon')]
    if not members:
        raise ValidationError({'members': '멤버가 비어 있음'})
    fmt = request.data.get('format') if request.data.get('format') in ('singles', 'doubles') else 'singles'
    out = party_check(rs.id, members[:6], fmt)
    cands = [c for c in (request.data.get('candidates') or []) if c and c.get('pokemon')][:3]
    if cands and len(members) < 6:
        out['candidates'] = compare_candidates(rs.id, members[:5], cands, fmt, out)
    return Response(out)


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
        moves = [(d.target_key, d.pct) for d in sorted(u.details.all(), key=lambda d: -d.pct) if d.kind == 'move'][:10]
        attacks = [(n['move'][x], pct) for x, pct in moves if x in n['move'] and n['move'][x]['category'] != 'Status']
        hits, rare = [], []
        for name_ko, types in member_types:
            supers = [(mv, pct) for mv, pct in attacks if _mult(mv['type'], types) >= 2]
            common = [a for a in supers if a[1] >= COMMON_MOVE_PCT]
            # 기술 사용률 10% 이상이면 찌름으로 셈, 그보다 낮으면 '가끔'으로 따로 (사용률 표시)
            pick = max(common or supers, key=lambda a: (_mult(a[0]['type'], types), a[1]), default=None)
            if not pick:
                continue
            mv, pct = pick
            line = f"{name_ko}←{mv['name_ko']} {pct:g}%({TYPE_KO.get(mv['type'])} ×{_mult(mv['type'], types):g})"
            (hits if common else rare).append(line)
        if len(hits) >= need:
            out.append({'id': key, 'name_ko': n['pokemon'][key]['name_ko'], 'rank': r['rank'],
                        'hits': len(hits), 'targets': hits, **({'sometimes': rare} if rare else {})})
    out.sort(key=lambda x: (-x['hits'], x['rank']))
    return Response({'format': fmt, 'checked_top': top, 'need_hits': need, 'threats': out[:8],
                     'note': f'기술 사용률 {COMMON_MOVE_PCT:g}% 이상인 공격기로 찌르는 멤버 수 (sometimes: 그보다 드물게 쓰는 기술). '
                             '특성에 의한 무효·대미지 크기는 반영하지 않음'})


def _mult(attack: str, types: list[str]) -> float:
    return defense_profile(types)[attack]
