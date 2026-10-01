"""Showdown 내보내기(팀 텍스트, pokepaste) 해석.

    Aang (Staraptor) @ Staraptite
    Ability: Intimidate
    Level: 50
    EVs: 32 HP / 30 SpA / 4 Spe        ← 챔피언스는 이 칸이 SP
    Modest Nature
    - Weather Ball

반환: [{species, item, ability, nature, sp, moves}]  (이름은 화면 표기 그대로, ID 변환은 쓰는 쪽에서)
"""
import re

from apps.meta.models import SP_STATS

EV_STAT = {'HP': 'hp', 'Atk': 'atk', 'Def': 'def', 'SpA': 'spa', 'SpD': 'spd', 'Spe': 'spe'}


def parse_set(block: str) -> dict | None:
    lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
    if not lines:
        return None
    head, _, item = lines[0].partition(' @ ')
    head = re.sub(r'\s*\((M|F)\)\s*$', '', head.strip())          # 성별
    m = re.search(r'\(([^()]+)\)\s*$', head)                     # 별명 (종)
    out = {'species': (m.group(1) if m else head).strip(), 'item': item.strip(), 'ability': '', 'nature': '',
           'sp': None, 'moves': []}
    for l in lines[1:]:
        if l.startswith('Ability:'):
            out['ability'] = l[len('Ability:'):].strip()
        elif l.endswith(' Nature'):
            out['nature'] = l[:-len(' Nature')].strip()
        elif l.startswith('EVs:'):
            sp = dict.fromkeys(SP_STATS, 0)
            for part in l[len('EVs:'):].split('/'):
                n, _, stat = part.strip().partition(' ')
                if stat in EV_STAT and n.isdigit():
                    sp[EV_STAT[stat]] = int(n)
            out['sp'] = sp
        elif l.startswith('-'):
            out['moves'].append(l[1:].strip())
    return out


def parse_paste(text: str) -> list[dict]:
    return [s for s in (parse_set(b) for b in re.split(r'\r?\n\s*\r?\n', text.strip())) if s]
