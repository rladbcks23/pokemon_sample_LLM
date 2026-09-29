"""Showdown 리플레이 로그 해석.

한 판의 로그에서 양쪽 파티(팀 프리뷰 6마리), 오픈 팀시트 육성 정보, 배틀에 나온 포켓몬, 선봉, 메가 사용, 승패를 뽑는다.
선출/선봉 학습 데이터의 원본으로도 쓴다.
"""
from dataclasses import dataclass, field

from apps.dex.ids import to_id


@dataclass
class ReplaySide:
    side: str                                            # p1 / p2
    player: str = ''
    result: str = ''                                     # win / lose / '' (승패 정보 없음)
    species: list[str] = field(default_factory=list)     # 팀 프리뷰 순서
    sets: dict[str, dict] = field(default_factory=dict)  # 오픈 팀시트: 종 → {item, ability, moves, nature}
    brought: set[str] = field(default_factory=set)       # 배틀에 나온 포켓몬
    lead: set[str] = field(default_factory=set)          # 1턴 전에 나온 포켓몬
    mega: set[str] = field(default_factory=set)          # 메가진화한 포켓몬


def parse_replay(log: str) -> list[ReplaySide]:
    sides = {s: ReplaySide(side=s) for s in ('p1', 'p2')}
    winner, turn_started = None, False
    for line in log.split('\n'):
        p = line.split('|')
        if len(p) < 3:
            continue
        tag = p[1]
        if tag == 'player' and len(p) > 3 and p[3]:
            sides[p[2]].player = p[3]
        elif tag == 'poke':                         # 팀 프리뷰: |poke|p1|Garchomp, L50, M|
            sides[p[2]].species.append(to_id(p[3].split(',')[0]))
        elif tag == 'showteam':                     # 오픈 팀시트: 이름|종|도구|특성|기술|성격|...]
            for packed in '|'.join(p[3:]).split(']'):
                f = packed.split('|')
                if len(f) < 6:
                    continue
                sides[p[2]].sets[to_id(f[1] or f[0])] = {
                    'item': to_id(f[2]), 'ability': to_id(f[3]),
                    'moves': [to_id(m) for m in f[4].split(',') if m], 'nature': to_id(f[5])}
        elif tag in ('switch', 'drag'):             # |switch|p1a: 별명|Garchomp, L50, M|100/100
            side, sid = sides[p[2][:2]], to_id(p[3].split(',')[0])
            side.brought.add(sid)
            if not turn_started:
                side.lead.add(sid)
        elif tag == '-mega':                        # |-mega|p1b: 별명|Blastoise|Blastoisinite
            sides[p[2][:2]].mega.add(to_id(p[3]))
        elif tag == 'turn':
            turn_started = True
        elif tag == 'win':
            winner = p[2]
    if winner is not None:
        for s in sides.values():
            s.result = 'win' if s.player == winner else 'lose'
    return list(sides.values())


def match_species(sid: str, candidates: set[str]) -> bool:
    """팀 프리뷰 종과 배틀 중 종 이름 매칭 (폼이 바뀌어 보이는 경우 앞부분 일치로 허용)."""
    return sid in candidates or any(c.startswith(sid) or sid.startswith(c) for c in candidates)
