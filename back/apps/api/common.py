"""API 공통: 레귤레이션·포맷 파라미터, 한글 이름 조회."""
from functools import lru_cache

from rest_framework.exceptions import NotFound, ValidationError

from apps.dex.models import Ability, Item, Move, Nature, Pokemon, Ruleset

FORMATS = ('singles', 'doubles')


def get_ruleset(request) -> Ruleset:
    """?ruleset=champions_mc (없으면 가장 최근 레귤레이션)."""
    rid = request.query_params.get('ruleset')
    rs = Ruleset.objects.filter(id=rid).first() if rid else Ruleset.objects.order_by('-start_date').first()
    if not rs:
        raise NotFound('레귤레이션이 없습니다')
    return rs


def get_format(request, default: str = 'doubles') -> str:
    fmt = request.query_params.get('format', default)
    if fmt not in FORMATS:
        raise ValidationError({'format': f'singles 또는 doubles (받은 값: {fmt})'})
    return fmt


def format_key(ruleset: Ruleset, fmt: str) -> str:
    return f'{ruleset.id}_{fmt}'


@lru_cache(maxsize=8)
def names(ruleset_id: str) -> dict:
    """레귤레이션별 ID → 표시 정보. meta 테이블은 ID 문자열만 갖고 있어서 응답에 이름을 붙일 때 쓴다."""
    return {
        'pokemon': {p['showdown_id']: p for p in Pokemon.objects.filter(ruleset_id=ruleset_id).values(
            'showdown_id', 'name', 'name_ko', 'base_species', 'forme', 'is_mega', 'type1', 'type2', 'num')},
        'move': {m['showdown_id']: m for m in Move.objects.filter(ruleset_id=ruleset_id).values(
            'showdown_id', 'name', 'name_ko', 'type', 'category', 'power', 'accuracy', 'pp')},
        'item': {i['showdown_id']: i for i in Item.objects.filter(ruleset_id=ruleset_id).values(
            'showdown_id', 'name', 'name_ko', 'mega_from', 'mega_to', 'short_desc')},
        'ability': {a['showdown_id']: a for a in Ability.objects.filter(ruleset_id=ruleset_id).values(
            'showdown_id', 'name', 'name_ko', 'short_desc')},
        'nature': {n['id']: n for n in Nature.objects.values('id', 'name', 'name_ko', 'plus_stat', 'minus_stat')},
    }


def pokemon_brief(ruleset_id: str, sid: str) -> dict:
    """목록·카드용 포켓몬 요약: id, 이름, 타입."""
    p = names(ruleset_id)['pokemon'].get(sid)
    if not p:
        return {'id': sid, 'name': sid, 'name_ko': sid, 'types': []}
    return {'id': sid, 'name': p['name'], 'name_ko': p['name_ko'] or p['name'],
            'types': [t for t in (p['type1'], p['type2']) if t], 'is_mega': p['is_mega']}


def label(ruleset_id: str, kind: str, key: str) -> dict:
    """도구·기술·특성·성격 ID → {id, name_ko, ...}."""
    if not key:
        return None
    row = names(ruleset_id)[kind].get(key)
    if not row:
        return {'id': key, 'name': key, 'name_ko': key}
    out = {'id': key, 'name': row['name'], 'name_ko': row['name_ko'] or row['name']}
    if kind == 'move':
        out.update(type=row['type'], category=row['category'])
    return out
