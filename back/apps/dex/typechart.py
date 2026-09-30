"""타입 상성 계산. API와 LLM 도구가 같이 쓴다.

type_chart 테이블(공격 타입 × 방어 타입 배율)을 한 번 읽어 메모리에 둔다.
특성에 의한 무효(부유, 저수 등)는 반영하지 않는다.
"""
from functools import lru_cache

TYPES = ['Normal', 'Fire', 'Water', 'Electric', 'Grass', 'Ice', 'Fighting', 'Poison', 'Ground',
         'Flying', 'Psychic', 'Bug', 'Rock', 'Ghost', 'Dragon', 'Dark', 'Steel', 'Fairy']

TYPE_KO = {
    'Normal': '노말', 'Fire': '불꽃', 'Water': '물', 'Electric': '전기', 'Grass': '풀', 'Ice': '얼음',
    'Fighting': '격투', 'Poison': '독', 'Ground': '땅', 'Flying': '비행', 'Psychic': '에스퍼', 'Bug': '벌레',
    'Rock': '바위', 'Ghost': '고스트', 'Dragon': '드래곤', 'Dark': '악', 'Steel': '강철', 'Fairy': '페어리',
}


@lru_cache(maxsize=1)
def chart() -> dict[tuple[str, str], float]:
    from apps.dex.models import TypeChart
    return {(t.attacking, t.defending): t.multiplier for t in TypeChart.objects.all()}


def multiplier(attacking: str, defending: list[str]) -> float:
    """공격 타입 하나가 방어 타입들(1~2개)에 주는 배율."""
    c = chart()
    m = 1.0
    for d in defending:
        if d:
            m *= c.get((attacking, d), 1.0)
    return m


def defense_profile(defending: list[str]) -> dict[str, float]:
    """방어 타입 조합이 18개 공격 타입에서 받는 배율."""
    return {t: multiplier(t, defending) for t in TYPES}


def matchups(defending: list[str]) -> dict[str, list[dict]]:
    """약점(×2, ×4) / 반감(½, ¼) / 무효(0)로 나눈 목록."""
    out = {'weak': [], 'resist': [], 'immune': []}
    for t, m in defense_profile(defending).items():
        if m == 0:
            out['immune'].append({'type': t, 'multiplier': m})
        elif m > 1:
            out['weak'].append({'type': t, 'multiplier': m})
        elif m < 1:
            out['resist'].append({'type': t, 'multiplier': m})
    out['weak'].sort(key=lambda x: -x['multiplier'])
    out['resist'].sort(key=lambda x: x['multiplier'])
    return out
