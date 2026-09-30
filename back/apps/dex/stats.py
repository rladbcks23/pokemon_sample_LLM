"""챔피언스 실수치 계산 (Lv50, 개체값 31 고정, SP 방식).

Showdown champions mod의 statModify와 같은 공식:
- HP      = 종족값 + SP + 75
- 그 외   = floor((종족값 + SP + 20) × 성격 보정)   (보정: 상승 1.1 / 하락 0.9, 소수점 버림)
"""
STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
SP_MAX_PER_STAT = 32
SP_MAX_TOTAL = 66


def calc_stat(stat: str, base: int, sp: int, plus: str | None = None, minus: str | None = None) -> int:
    if stat == 'hp':
        return base + sp + 75
    value = base + sp + 20
    if stat == plus:
        value = value * 110 // 100
    elif stat == minus:
        value = value * 90 // 100
    return value


def calc_stats(base: dict, sp: dict, plus: str | None = None, minus: str | None = None) -> dict:
    return {s: calc_stat(s, base[s], sp.get(s, 0), plus, minus) for s in STATS}


def sp_problems(sp: dict) -> list[str]:
    """SP 규칙 위반 목록 (스탯당 0~32, 합계 66 이하)."""
    out = [f'{s} SP {v}: 스탯당 0~{SP_MAX_PER_STAT}' for s, v in sp.items() if not 0 <= v <= SP_MAX_PER_STAT]
    total = sum(sp.values())
    if total > SP_MAX_TOTAL:
        out.append(f'SP 합계 {total}: 최대 {SP_MAX_TOTAL}')
    return out
