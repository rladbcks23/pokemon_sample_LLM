"""스피드표: 픽률 상위 포켓몬의 Lv50 스피드 실수치를 같은 값끼리 묶어 빠른 순으로.

포켓몬마다 실제로 쓰이는 투자(최속·준속·무보정·최저속)와 스피드 보정(스카프, 쓱쓱·곡예 같은 특성,
용춤·껍질깨기 같은 기술, 메가진화)을 사용률 데이터에서 골라 한 줄씩 만든다.

    무보정 = 종족값 + 20          최저속 = 무보정 × 0.9
    준속   = 무보정 + 32          최속   = 준속 × 1.1
    스카프·1랭크업 ×1.5, 2랭크업·쓱쓱 등 ×2
"""
from collections import defaultdict

from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.api.common import get_format, get_ruleset
from apps.dex.ids import to_id
from apps.dex.models import Pokemon
from apps.dex.stats import calc_stat
from apps.meta.models import UsageStat

MIN_PCT = 10.0       # 도구·특성·기술은 이 % 이상 쓰일 때만 그 보정을 넣음
INVEST_PCT = 15.0    # 투자(성격·SP)도 이 % 이상일 때만

# 날씨·필드·도구 소비로 스피드 2배가 되는 특성 (메가 폼 특성도 포함)
DOUBLE_ABILITIES = {'swiftswim', 'chlorophyll', 'sandrush', 'slushrush', 'surgesurfer', 'unburden', 'weakarmor'}
# 스피드 랭크를 올리는 기술: (올리는 랭크, 쓴 횟수를 앞에 붙일지)
BOOST_MOVES = {
    'dragondance': (1, True), 'quiverdance': (1, True), 'flamecharge': (1, True), 'shellsmash': (2, True),
    'agility': (2, False), 'rockpolish': (2, False), 'autotomize': (2, False), 'shiftgear': (2, False),
}
STAGE = {1: 1.5, 2: 2.0}


def investments(u: dict | None) -> list[tuple[str, int, str | None, str | None]]:
    """사용률의 성격·SP 배분에서 쓰이는 투자 → [(이름, 스피드 SP, 올리는 성격, 내리는 성격)]."""
    if not u:
        return [('최속', 32, 'spe', None)]
    fast = sum(n['pct'] for n in u['nature'] if n.get('plus') == 'spe')
    slow = sum(n['pct'] for n in u['nature'] if n.get('minus') == 'spe')
    mid = sum(n['pct'] for n in u['nature'] if n.get('plus') != 'spe' and n.get('minus') != 'spe')
    s32 = sum(x['pct'] for x in u['spread'] if x['sp']['spe'] >= 30)
    s0 = sum(x['pct'] for x in u['spread'] if x['sp']['spe'] == 0)
    out = []
    if fast >= INVEST_PCT:
        out.append(('최속', 32, 'spe', None))
    if mid >= INVEST_PCT and s32 >= INVEST_PCT:
        out.append(('준속', 32, None, None))
    if mid >= INVEST_PCT and s0 >= 30 and slow < INVEST_PCT:
        out.append(('무보정', 0, None, None))
    if slow >= INVEST_PCT:
        out.append(('최저속', 0, None, 'spe'))
    return out or [('최속', 32, 'spe', None)]


def boosts(u: dict | None, ability_ids: set[str], names: dict) -> list[tuple[str, float]]:
    """스피드 보정 → [(이름, 배율)]. 아무것도 안 한 상태(이름 '', ×1)가 맨 앞."""
    out = [('', 1.0)]
    if not u:
        return out
    if any(i['id'] == 'choicescarf' and i['pct'] >= MIN_PCT for i in u['item']):
        out.append(('스카프', 1.5))
    abilities = {a['id'] for a in u['ability'] if a['pct'] >= MIN_PCT} | ability_ids
    for a in sorted(abilities & DOUBLE_ABILITIES):
        out.append((names.get(a, a), 2.0))
    if 'speedboost' in abilities:
        out += [('1가속', 1.5), ('2가속', 2.0)]
    for m in u['move']:
        if m['id'] in BOOST_MOVES and m['pct'] >= MIN_PCT:
            stage, count = BOOST_MOVES[m['id']]
            out.append((f"1{m['name_ko']}" if count else m['name_ko'], STAGE[stage]))
    return out


@api_view(['GET'])
def speed_tiers(request):
    """GET /api/speed/?format=doubles&top=50 → {'rows': [{'speed', 'entries': [{pokemon, label, rank}]}]}"""
    from apps.api.views import latest_usage, mega_ability, mega_owner, rank_board, usage_detail

    rs, fmt = get_ruleset(request), get_format(request)
    top = min(int(request.query_params.get('top', 50) or 50), 300)
    ranks = sorted(rank_board(rs, fmt)['rows'].items(), key=lambda x: x[1]['rank'])[:top]
    all_p = {p.showdown_id: p for p in Pokemon.objects.filter(ruleset=rs).prefetch_related('ability_slots__ability')}
    ids = {k for k, p in all_p.items() if not p.is_mega}
    megas = defaultdict(list)
    for p in all_p.values():
        if p.is_mega:
            megas[mega_owner(rs, p, ids)].append(p)
    usage_qs = latest_usage(rs, fmt)[0].prefetch_related('details')
    usage = {u.pokemon_key: usage_detail(rs, u) for u in usage_qs.filter(pokemon_key__in=[k for k, _ in ranks])}
    ability_ko = {pa.ability.showdown_id: pa.ability.name_ko for p in all_p.values() for pa in p.ability_slots.all()}

    rows = defaultdict(list)          # 스피드 → 줄
    for key, r in ranks:
        p = all_p.get(key)
        if not p:
            continue
        u = usage.get(key)
        stone_pct = {m.showdown_id: sum(i['pct'] for i in (u or {}).get('item', []) if i['id'] == to_id(m.required_item))
                     for m in megas.get(key, [])}
        forms = []
        if sum(stone_pct.values()) < 90:           # 거의 다 메가진화하면 메가 전 폼은 뺌
            forms.append((p, set(), False))
        for m in megas.get(key, []):
            if stone_pct[m.showdown_id] >= MIN_PCT:
                ab = mega_ability(m)
                forms.append((m, {ab['id']} if ab else set(), True))
        for form, fixed_ab, is_mega in forms:
            entries = defaultdict(list)          # (스피드) → 라벨들 (같은 값이면 쓱쓱/고속이동처럼 합침)
            u_form = u if not is_mega else {**u, 'item': [], 'ability': []} if u else None   # 메가는 스카프·원래 특성 X
            for inv, sp, plus, minus in investments(u):
                base = calc_stat('spe', form.spe, sp, plus, minus)
                for name, mult in boosts(u_form, fixed_ab, ability_ko):
                    if name and inv in ('무보정', '최저속'):
                        continue                  # 보정은 스피드에 투자한 경우만
                    entries[int(base * mult)].append((inv, name))
            for spe, labels in entries.items():
                by_inv = defaultdict(list)     # 같은 투자끼리: "준속 쓱쓱/고속이동"
                for inv, name in labels:
                    by_inv[inv].append(name)
                label = ', '.join(f"{inv} {'/'.join(n for n in names if n)}".strip() for inv, names in by_inv.items())
                rows[spe].append({
                    'pokemon': {'id': form.showdown_id, 'name_ko': form.name_ko or form.name, 'is_mega': is_mega},
                    'label': label, 'rank': r['rank'],
                })
    out = [{'speed': s, 'entries': sorted(e, key=lambda x: x['rank'])} for s, e in sorted(rows.items(), reverse=True)]
    return Response({'ruleset': rs.id, 'format': fmt, 'top': top, 'rows': out})
