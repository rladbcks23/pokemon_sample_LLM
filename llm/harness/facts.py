"""근거 묶음: 설명 작성·심사가 볼 수 있는 사실 전부 (DESCRIPTION_RUBRIC.md 0번).

back(Django)을 이 프로세스 안에서 불러 DB와 파티 판단 도구(party_check·threats)를 그대로 쓴다.
설명 속 숫자·이름은 이 묶음에 있는 것만 허용되므로, 묶음은 이름을 한글로 풀어 둔다.
"""
import hashlib
import json
import sys
from pathlib import Path

LLM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LLM / 'training'))

from inproc_back import _dj  # noqa: E402  (Django 설정도 여기서)

from apps.api.common import format_key, names  # noqa: E402
from apps.api.party import _base, member_profile, party_check  # noqa: E402
from apps.api.views import SET_SOURCES, SOURCE_LABEL, latest_usage, norm_nature, rank_board, shown_key  # noqa: E402
from apps.dex.models import Move, Ruleset  # noqa: E402
from apps.dex.typechart import TYPE_KO, TYPES, defense_profile  # noqa: E402
from apps.meta.models import SP_STATS, PokemonSet, Team  # noqa: E402

from harness.rubric import grounding_text, packet_hash  # noqa: E402,F401  (예전 import 경로 유지)

STAT_KO = {'hp': 'H', 'atk': 'A', 'def': 'B', 'spa': 'C', 'spd': 'D', 'spe': 'S'}
CATEGORY_KO = {'Physical': '물리', 'Special': '특수', 'Status': '변화'}
RARE_SHAPE_PCT = 10         # 형태 분포에서 이 비율 미만이면 드문 형태
TOP_PICKS = 30              # 커버리지 계산: 이 픽률 순위 안의 포켓몬
# 명중 판정이 없는 기술 대상 (자기·우리 편·필드)
NO_ACCURACY_TARGETS = {'self', 'allySide', 'adjacentAlly', 'allies', 'adjacentAllyOrSelf', 'allyTeam', 'all', 'foeSide'}


class Facts:
    def __init__(self):
        self.rs = Ruleset.objects.order_by('-start_date').first()
        self.rid = self.rs.id
        self.n = names(self.rid)
        # names()의 기술에는 설명이 없어서 따로 (나무위키 한글 설명)
        self.move_desc = dict(Move.objects.filter(ruleset=self.rs).values_list('showdown_id', 'short_desc'))
        self.move_target = dict(Move.objects.filter(ruleset=self.rs).values_list('showdown_id', 'target'))
        self._usage, self._top = {}, {}

    # ------------------------------------------------------------ 사용률·상성

    def usage(self, fmt: str, key: str) -> dict:
        """그 포켓몬의 최신 사용률 상세 {kind: {id: pct}} (항목마다 10위까지만 있음)."""
        if fmt not in self._usage:
            qs, _ = latest_usage(self.rs, fmt)
            self._usage[fmt] = {u.pokemon_key: u for u in qs.prefetch_related('details')}
        u = self._usage[fmt].get(key)
        out = {}
        for d in (u.details.all() if u else []):
            out.setdefault(d.kind, {})[d.target_key] = d.pct
        return out

    def top_picks(self, fmt: str) -> list[tuple[str, list[str]]]:
        """픽률 상위 포켓몬 (한글 이름, 영문 타입)."""
        if fmt not in self._top:
            rows = sorted(rank_board(self.rs, fmt)['rows'].items(), key=lambda x: x[1]['rank'])[:TOP_PICKS]
            self._top[fmt] = [(self.ko('pokemon', k), [t for t in (p['type1'], p['type2']) if t])
                              for k, _ in rows if (p := self.n['pokemon'].get(k))]
        return self._top[fmt]

    @staticmethod
    def weak_to(types: list[str]) -> list[str]:
        prof = defense_profile(types)
        return [f'{TYPE_KO[t]}{" ×4" if prof[t] >= 4 else ""}' for t in TYPES if prof[t] >= 2]

    def coverage(self, fmt: str, moves: list[str], self_key: str) -> dict:
        """공격기마다 효과가 굉장한 타입과, 픽률 상위 중 이 기술로만 ×2 이상 찌르는 포켓몬."""
        attacks = [x for x in moves if (self.n['move'].get(x) or {}).get('category') in ('Physical', 'Special')]
        me = self.ko('pokemon', self_key)
        hit = {x: {name for name, types in self.top_picks(fmt) if name != me
                   and defense_profile(types)[self.n['move'][x]['type']] >= 2} for x in attacks}
        out = {}
        for x in attacks:
            t = self.n['move'][x]['type']
            only = sorted(hit[x] - set().union(*(hit[y] for y in attacks if y != x)))
            out[x] = {'super_effective_on': [TYPE_KO[d] for d in TYPES if defense_profile([d])[t] >= 2],
                      f'only_this_hits_top{TOP_PICKS}': only[:6]}
        return out

    # ------------------------------------------------------------ 공통

    def ko(self, kind: str, key: str) -> str:
        row = self.n[kind].get(key) or {}
        return row.get('name_ko') or row.get('name') or key

    @staticmethod
    def as_sample(s) -> dict:
        return {'pokemon': s.pokemon_key, 'item': s.item_key, 'ability': s.ability_key,
                'nature': norm_nature(s.nature_key), 'sp': {st: getattr(s, f'sp_{st}') for st in SP_STATS},
                'moves': [x for x in s.moves if x]}

    @staticmethod
    def sample_key(fmt: str, m: dict) -> str:
        """DB를 다시 적재하면 PokemonSet ID가 바뀌므로 육성 내용으로 키를 만든다."""
        raw = json.dumps([fmt, m['pokemon'], m['item'], m['ability'], m['nature'], m['sp'], sorted(m['moves'])])
        return 'S-' + hashlib.sha1(raw.encode()).hexdigest()[:12]

    def sp_text(self, sp: dict) -> str:
        return ' '.join(f'{STAT_KO[s]}{v}' for s, v in sp.items() if v) or '없음'

    def brief(self, fmt: str, m: dict) -> dict:
        """육성형 한 개를 한글로 (파티 멤버 요약에도 씀)."""
        shown = shown_key(self.rid, m['pokemon'], m['item'])
        p = self.n['pokemon'][shown]
        prof = member_profile(self.rid, m, fmt)
        out = {'name_ko': self.ko('pokemon', shown), 'types': [TYPE_KO[t] for t in (p['type1'], p['type2']) if t],
               'item': self.ko('item', m['item']) if m['item'] else '없음', 'ability': self.ko('ability', m['ability']),
               'nature': self.ko('nature', m['nature']), 'sp': self.sp_text(m['sp']),
               'moves': [self.ko('move', x) for x in m['moves']], 'roles': prof['roles'], 'speed': prof['speed']}
        if shown != m['pokemon']:
            out['mega_from'] = self.ko('pokemon', m['pokemon'])
        if prof.get('speed_note'):
            out['speed_note'] = prof['speed_note']
        return out

    # ------------------------------------------------------------ 샘플

    def samples(self, fmt: str | None = None, pokemon: str | None = None):
        """설명을 쓸 샘플: OP.GG 샘플 → 대회 팀 → OP.GG 팀 순서. 같은 육성은 한 번만."""
        qs = PokemonSet.objects.filter(ruleset=self.rs)
        if fmt:
            qs = qs.filter(format_key=format_key(self.rs, fmt))
        if pokemon:
            qs = qs.filter(pokemon_key=pokemon)
        seen = set()
        for src in SET_SOURCES:
            for s in qs.filter(source=src).order_by('id'):
                f = s.format_key.rsplit('_', 1)[-1]
                m = self.as_sample(s)
                k = self.sample_key(f, m)
                if k not in seen:
                    seen.add(k)
                    yield k, f, s

    def sample_packet(self, fmt: str, s) -> dict:
        m = self.as_sample(s)
        shown = shown_key(self.rid, m['pokemon'], m['item'])
        base = _base(self.rid, shown)
        info = self.brief(fmt, m)
        use = self.usage(fmt, m['pokemon'])
        cov = self.coverage(fmt, m['moves'], shown)
        move_rows = []
        for x in m['moves']:
            mv = self.n['move'].get(x) or {}
            move_rows.append({'name_ko': self.ko('move', x), 'type': TYPE_KO.get(mv.get('type'), ''),
                              'category': CATEGORY_KO.get(mv.get('category'), ''), 'power': mv.get('power') or None,
                              'accuracy': self.accuracy(x),
                              'usage_pct': use.get('move', {}).get(x, '10위 밖'), **cov.get(x, {}),
                              'desc': self.move_desc.get(x, '')})
        p = self.n['pokemon'][shown]
        same = [o for o in PokemonSet.objects.filter(ruleset=self.rs, format_key=s.format_key, pokemon_key=s.pokemon_key)
                if self.sample_key(fmt, self.as_sample(o)) != self.sample_key(fmt, m)]
        shapes = {}
        for o in [s, *same]:
            r = member_profile(self.rid, self.as_sample(o), fmt)['roles'][0].split(' (')[0]
            shapes[r] = shapes.get(r, 0) + 1
        total = sum(shapes.values())
        mine = info['roles'][0].split(' (')[0]
        pct = round(shapes[mine] * 100 / total)
        return {
            'kind': 'sample', 'format': '싱글' if fmt == 'singles' else '더블',
            'source': SET_SOURCES.get(s.source, s.source), 'name': s.name or None,
            'pokemon': {**{k: info[k] for k in ('name_ko', 'types')}, **({'mega_from': info['mega_from']} if 'mega_from' in info else {}),
                        'base_stats': {STAT_KO[k]: v for k, v in base.items()},
                        'weak_to': self.weak_to([t for t in (p['type1'], p['type2']) if t])},
            'item': {'name_ko': info['item'], 'usage_pct': use.get('item', {}).get(m['item'], '10위 밖'),
                     'desc': self._desc('item', m['item'])},
            'ability': {'name_ko': info['ability'], 'usage_pct': use.get('ability', {}).get(m['ability'], '10위 밖'),
                        'desc': self._desc('ability', m['ability'])},
            'nature': info['nature'], 'sp': info['sp'], 'moves': move_rows,
            'usage_note': f'usage_pct = 이 포켓몬({info["name_ko"]})을 쓰는 사람 중 그 기술·도구·특성을 쓰는 비율 (OP.GG, 10위까지만). '
                          'accuracy = 명중률 (100도 회피가 오르거나 명중이 떨어지면 빗나갈 수 있음), "필중" = 회피·명중 랭크와 상관없이 맞음, '
                          '없음(null) = 명중 판정이 없는 기술(자기·필드 대상). '
                          f'only_this_hits_top{TOP_PICKS} = 픽률 상위 {TOP_PICKS} 중 이 샘플의 다른 공격기로는 ×2를 못 찌르고 이 기술로만 찌르는 포켓몬',
            'roles': info['roles'], 'speed': info['speed'], **({'speed_note': info['speed_note']} if 'speed_note' in info else {}),
            **({'speed_with_scarf': info['speed'] * 3 // 2} if m['item'] == 'choicescarf' else {}),
            'shapes': {'total': total, **dict(sorted(shapes.items(), key=lambda kv: -kv[1])),
                       'this': mine, 'this_pct': pct, 'rare': pct < RARE_SHAPE_PCT},
            'others': self._others(fmt, m, same),
        }

    def _others(self, fmt: str, m: dict, same: list) -> list[dict]:
        """같은 포켓몬 다른 샘플과의 차이 (도구·SP·기술). 많이 겹치는 순서로 5개."""
        rows = []
        for o in same:
            om = self.as_sample(o)
            diff = {}
            if om['item'] != m['item']:
                diff['item'] = self.ko('item', om['item']) if om['item'] else '없음'
            if om['sp'] != m['sp']:
                diff['sp'] = self.sp_text(om['sp'])
            if om['nature'] != m['nature']:
                diff['nature'] = self.ko('nature', om['nature'])
            only_me = [self.ko('move', x) for x in m['moves'] if x not in om['moves']]
            only_o = [self.move_brief(fmt, om['pokemon'], x) for x in om['moves'] if x not in m['moves']]
            if only_me or only_o:
                diff['moves'] = {'this_only': only_me, 'other_only': only_o}
            diff['role'] = member_profile(self.rid, om, fmt)['roles'][0]
            rows.append((len(only_me) + ('item' in diff) + ('sp' in diff), diff))
        seen, out = set(), []
        for _, d in sorted(rows, key=lambda r: r[0]):
            k = json.dumps(d, ensure_ascii=False, sort_keys=True)
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out[:5]

    def accuracy(self, key: str):
        """명중률. 필중(회피·명중 랭크와 상관없이 맞음)과 명중 100(랭크가 바뀌면 빗나갈 수 있음)은 다르다.
        DB에 명중이 없으면: 상대를 노리는 기술은 필중, 자기·우리 편·필드 대상은 명중 판정이 없음(None)."""
        acc = (self.n['move'].get(key) or {}).get('accuracy')
        if acc:
            return acc
        return None if self.move_target.get(key) in NO_ACCURACY_TARGETS else '필중'

    def move_brief(self, fmt: str, pokemon: str, key: str) -> dict:
        """다른 샘플이 대신 쓰는 기술: 이 샘플의 기술과 비교할 수 있게 위력·명중·사용률·효과."""
        mv = self.n['move'].get(key) or {}
        return {'name_ko': self.ko('move', key), 'type': TYPE_KO.get(mv.get('type'), ''),
                'category': CATEGORY_KO.get(mv.get('category'), ''), 'power': mv.get('power') or None,
                'accuracy': self.accuracy(key), 'usage_pct': self.usage(fmt, pokemon).get('move', {}).get(key, '10위 밖'),
                'desc': self.move_desc.get(key, '')}

    def _desc(self, kind: str, key: str) -> str:
        if kind == 'move':
            return self.move_desc.get(key, '')
        return (self.n[kind].get(key) or {}).get('short_desc') or ''

    # ------------------------------------------------------------ 파티

    def parties(self, fmt: str | None = None):
        qs = Team.objects.filter(ruleset=self.rs, source__in=['opgg_replica', 'vgcpastes']).exclude(is_legal=False)
        if fmt:
            qs = qs.filter(format_key=format_key(self.rs, fmt))
        for t in qs.order_by('source', 'placement', 'id').prefetch_related('members'):
            ms = [self.as_sample(m) for m in sorted(t.members.all(), key=lambda m: m.slot)]
            if len(ms) != 6:
                continue
            f = t.format_key.rsplit('_', 1)[-1]
            raw = json.dumps([f, sorted(self.sample_key(f, m) for m in ms)])
            yield 'P-' + hashlib.sha1(raw.encode()).hexdigest()[:12], f, t, ms

    def party_packet(self, fmt: str, t, ms: list[dict]) -> dict:
        check = party_check(self.rid, ms, fmt)
        r = _dj.post('/api/threats/', data=json.dumps({'members': ms, 'format': fmt, 'top': 40}),
                     content_type='application/json')
        threats = r.json().get('threats', [])[:5] if r.status_code == 200 else []
        return {
            'kind': 'party', 'format': '싱글' if fmt == 'singles' else '더블',
            'source': SOURCE_LABEL.get(t.source, t.source),
            **{k: v for k, v in (('name', t.name), ('event', t.event), ('player', t.player),
                                 ('placement', t.placement)) if v},
            'members': [self.brief(fmt, m) for m in ms],
            'summary': check['summary'], 'warnings': check['warnings'],
            'threats': [{'name_ko': x['name_ko'], 'rank': x['rank'], 'targets': x['targets']} for x in threats],
            'mega_stones': sum(1 for m in ms if shown_key(self.rid, m['pokemon'], m['item']) != m['pokemon']),
        }
