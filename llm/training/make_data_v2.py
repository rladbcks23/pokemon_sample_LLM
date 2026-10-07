"""파인튜닝 데이터 v2: 사용자 질문을 바탕으로 한 다중 턴 파티 빌딩 대화 (유료 API 없음).

v1(make_data.py)은 생성 코드가 후보를 골라 결과만 보여 줬다. v2는 모델이 배울 행동을 대화에 드러낸다.
    1. 조건에 따라 후보 비교·선택 (check_party·find_partners 결과로 비교)
    2. 고정 멤버·도구/포켓몬 중복·메가 수 같은 제약 지키기
    3. 후속 요청에 맞춰 추천 고치기 (다중 턴)
    4. 도구 결과에 근거한 짧은 장점·단점
    5. 정보가 부족하면 확인 질문
    6. 조건 충돌·검색 실패면 한계를 정직하게 (맞는 후보가 없으면 억지로 추천하지 않음)

- 도구 결과는 llm/agent/tools.py를 back에 직접 붙여 실행한 실제 값. 판단(무엇이 비었는지, 어느 후보가 나은지)은
  같은 도구 결과로 계산하고, 답변의 숫자는 도구 결과에 있거나 그 차이(메가 종족값 변화)만 쓴다 (아니면 버림)
- 공격 SP를 줬는데 그쪽 공격기가 없는 이상한 샘플은 쓰지 않는다
- 답변은 짧게 (채팅창이 좁음): 후보는 "장점/단점" 한 줄, 육성형 전체는 추천 카드에 나오므로 이름@도구·역할만
- 대화마다 시나리오·조건·원본 ID·묶음(group)·DB 버전·자동 검사·검수 상태를 같이 기록한다
- 학습/평가는 group(원본 팀·샘플)으로 나눈다 (같은 원본의 변형이 양쪽에 섞이지 않게)
- 기존 train.jsonl/eval.jsonl은 건드리지 않는다. 결과는 training/data_v2/

    cd llm
    ..\\.venv\\Scripts\\python training\\make_data_v2.py              # 검수용 20개 → data_v2/review.jsonl, review.md
"""
import argparse
import asyncio
import hashlib
import json
import random
import re
import subprocess
from collections import Counter
from pathlib import Path

LLM = Path(__file__).resolve().parents[1]

from inproc_back import ROOT, back_client  # noqa: E402  (Django 설정도 여기서)

from agent.prompt import FORMAT_KO, screen_context  # noqa: E402
from agent.tools import ToolError, Tools, compact_sample  # noqa: E402
from apps.api.common import names  # noqa: E402
from apps.api.party import WASTED_SP, party_check  # noqa: E402
from apps.api.views import norm_nature, rank_board, shown_key  # noqa: E402
from apps.dex.models import Ruleset  # noqa: E402
from apps.meta.models import SP_STATS, PokemonSet, Team  # noqa: E402

OUT = LLM / 'training/data_v2'
STAT_OF = {'H': 'hp', 'A': 'atk', 'B': 'def', 'C': 'spa', 'D': 'spd', 'S': 'spe'}


class Skip(Exception):
    """재료가 맞지 않아 이 대화는 만들지 않음."""


# ---------------------------------------------------------------- DB 재료

class Dex:
    def __init__(self):
        self.rs = Ruleset.objects.order_by('-start_date').first()
        self.rid = self.rs.id
        self.n = names(self.rid)
        self.rank = {f: {k: r['rank'] for k, r in rank_board(self.rs, f)['rows'].items()} for f in FORMAT_KO}
        self.sets = {}
        for s in PokemonSet.objects.filter(ruleset=self.rs):
            self.sets.setdefault((s.format_key.rsplit('_', 1)[-1], s.pokemon_key), []).append(s)
        self.teams = {f: [] for f in FORMAT_KO}
        for t in Team.objects.filter(ruleset=self.rs, source__in=['opgg_replica', 'vgcpastes']) \
                .exclude(is_legal=False).prefetch_related('members'):
            ms = [self.sample(m) for m in t.members.all()]
            if len(ms) == 6 and not any(self.odd(m) for m in ms):
                self.teams[t.format_key.rsplit('_', 1)[-1]].append((t.id, ms))

    @staticmethod
    def sample(m) -> dict:
        return compact_sample({'pokemon': m.pokemon_key, 'item': m.item_key, 'ability': m.ability_key,
                               'nature': norm_nature(m.nature_key), 'sp': {s: getattr(m, f'sp_{s}') for s in SP_STATS},
                               'moves': [x for x in m.moves if x]})

    def odd(self, s: dict) -> bool:
        """공격(특공) SP를 줬는데 물리(특수) 공격기가 없는 샘플 (정제 대상)."""
        cats = {(self.n['move'].get(x) or {}).get('category') for x in s.get('moves') or []}
        sp = s.get('sp') or {}
        return (sp.get('atk', 0) >= WASTED_SP and 'Physical' not in cats) or \
            (sp.get('spa', 0) >= WASTED_SP and 'Special' not in cats)

    def ko(self, kind: str, key: str) -> str:
        row = self.n[kind].get(key) or {}
        return row.get('name_ko') or row.get('name') or key

    def is_stone(self, item: str) -> bool:
        return bool((self.n['item'].get(item) or {}).get('mega_to'))

    def find_set(self, fmt: str, key: str, item: str | None, stats: str) -> tuple[dict, int]:
        """사용자 표기(예: CS메가가디안 = 특공·스피드 투자 + 메가스톤)에 가장 맞는 실제 샘플."""
        want = {STAT_OF[c] for c in stats}
        best = None
        for f in (fmt, 'doubles' if fmt == 'singles' else 'singles'):
            for s in self.sets.get((f, key), []):
                if (item and s.item_key != item) or self.odd(self.sample(s)):
                    continue
                score = sum(getattr(s, f'sp_{x}') for x in want) - sum(getattr(s, f'sp_{x}') for x in set(SP_STATS) - want)
                if best is None or score > best[0]:
                    best = (score, s)
            if best:
                break
        if not best:
            raise Skip(f'샘플 없음: {key} {item}')
        return self.sample(best[1]), best[1].pk

    def party_check(self, members: list[dict], fmt: str) -> dict:
        return party_check(self.rid, members, fmt)


DEX: Dex

# 사용자가 준 질문 5개 (화면 파티는 실제 샘플 중 표기에 가장 맞는 것으로)
USER_PARTY = {
    'q1': ('singles', [('gardevoir', 'gardevoirite', 'CS'), ('blaziken', 'blazikenite', 'AS'), ('glimmora', 'focussash', 'CS'),
                       ('meowscarada', 'choicescarf', 'AS'), ('rotomwash', 'leftovers', 'HDB')]),
    'q2': ('doubles', [('rillaboom', 'miracleseed', 'HA')]),
    'q3': ('doubles', [('sableye', 'sitrusberry', 'HB'), ('gardevoir', 'gardevoirite', 'CS'), ('blaziken', 'blazikenite', 'AS'),
                       ('glimmora', 'focussash', 'CS'), ('meowscarada', 'choicescarf', 'AS'), ('rotomwash', 'leftovers', 'HDB')]),
    'q4': ('singles', [('gardevoir', 'gardevoirite', 'CS'), ('blaziken', 'blazikenite', 'AS')]),
    'q5': ('doubles', [('incineroar', 'sitrusberry', 'HB')]),
}


def user_party(qid: str) -> tuple[str, list[dict], list[int]]:
    fmt, spec = USER_PARTY[qid]
    party, ids = [], []
    for key, item, stats in spec:
        s, pk = DEX.find_set(fmt, key, item, stats)
        party.append(s)
        ids.append(pk)
    return fmt, party, ids


# ---------------------------------------------------------------- 대화 기록

class Dialogue:
    """여러 턴 대화. 턴마다 [화면] 상황 + 질문 → 도구 호출 → 최종 답변. 서버와 같게 지난 턴은 글만 남는다."""

    def __init__(self, tools: Tools, fmt: str, scenario: str, behaviors: list[str], rng=None):
        self.tools, self.fmt, self.rng = tools, fmt, rng or random.Random(0)
        self.meta = {'scenario': scenario, 'behaviors': behaviors, 'format': fmt, 'conditions': {}, 'sources': {}}
        self.turns: list[dict] = []
        self.tool_errors: list[str] = []

    def ask(self, text: str, party: list[dict]) -> None:
        self.turns.append({'user': text, 'party': [dict(p) for p in party], 'steps': [], 'final': None,
                           'proposed': None, 'derived': []})

    async def call(self, name: str, **args):
        turn = self.turns[-1]
        try:
            out = await self.tools.run(name, args)
        except ToolError as e:
            out = f'오류: {e}'
            self.tool_errors.append(f'{name}: {e}')
        turn['steps'].append({'role': 'assistant', 'content': '',
                              'tool_calls': [{'type': 'function', 'function': {'name': name, 'arguments': args}}]})
        turn['steps'].append({'role': 'tool', 'content': out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)})
        if name == 'propose_party':
            if not (isinstance(out, dict) and out.get('shown')):
                raise Skip(f'propose_party 실패: {out}')
            turn['proposed'] = self.tools.proposed
            self.tools.proposed = None
        return out

    def answer(self, text: str, derived: list | None = None) -> None:
        """derived: 도구 결과에서 계산한 숫자 (예: 메가 종족값 변화 +50). 근거 검사에서 허용."""
        self.turns[-1]['final'] = text.strip()
        self.turns[-1]['derived'] = [str(x) for x in derived or []]

    def records(self) -> list[list[dict]]:
        """학습용: 턴마다 한 대화 (지난 턴은 질문·답변 글만, 마지막 질문 앞에 [화면])."""
        out = []
        for i, t in enumerate(self.turns):
            msgs = []
            for p in self.turns[:i]:
                msgs += [{'role': 'user', 'content': p['user']}, {'role': 'assistant', 'content': p['final']}]
            party = t['party'] + [None] * (6 - len(t['party']))
            msgs.append({'role': 'user', 'content': screen_context(self.fmt, party) + '\n\n' + t['user']})
            out.append(msgs + t['steps'] + [{'role': 'assistant', 'content': t['final']}])
        return out


def numbers_grounded(msgs: list[dict], derived: list[str]) -> list[str]:
    """마지막 답변 숫자 중 앞선 내용(질문·도구 결과·지난 답변)과 계산한 값 어디에도 없는 것."""
    seen = ' '.join(m['content'] for m in msgs[:-1] if isinstance(m.get('content'), str))
    have = set(re.findall(r'\d+(?:\.\d+)?', seen)) | set(derived)
    return [x for x in re.findall(r'\d+(?:\.\d+)?', msgs[-1]['content']) if x not in have]


def auto_checks(d: Dialogue) -> dict:
    fixed = d.meta['conditions'].get('fixed', [])
    res = {'tool_errors': d.tool_errors, 'ungrounded_numbers': [], 'fixed_kept': True, 'no_duplicates': True,
           'excluded_respected': True, 'mega_stones_le_2': True, 'odd_samples': []}
    for rec, t in zip(d.records(), d.turns):
        res['ungrounded_numbers'] += numbers_grounded(rec, t['derived'])
    excluded = d.meta['conditions'].get('excluded_role')
    for i, t in enumerate(d.turns):
        p = t['proposed']
        if not p:
            continue
        pairs = [(m['pokemon'], m['item']) for m in p]
        if any((f['pokemon'], f['item']) not in pairs for f in fixed):
            res['fixed_kept'] = False
        mons = [m['pokemon'] for m in p]
        items = [m['item'] for m in p if m['item']]
        if len(set(mons)) != len(mons) or len(set(items)) != len(items):
            res['no_duplicates'] = False
        if sum(DEX.is_stone(x) for x in items) > 2:
            res['mega_stones_le_2'] = False
        res['odd_samples'] += [m['pokemon'] for m in p if DEX.odd(compact_sample(m))
                               and m['pokemon'] not in {f['pokemon'] for f in fixed}]
        if excluded and i > 0:
            added = [m for m in p if m['pokemon'] not in {f['pokemon'] for f in fixed}]
            roles = [r for prof in DEX.party_check(added, d.fmt)['members'] for r in prof['roles']] if added else []
            if role_matches(roles, excluded):
                res['excluded_respected'] = False
    res['ok'] = (not res['tool_errors'] and not res['ungrounded_numbers'] and res['fixed_kept']
                 and res['no_duplicates'] and res['excluded_respected'] and not res['odd_samples'])
    return res


# ---------------------------------------------------------------- 판단 (도구 결과로 계산)

def josa(word: str, with_batchim: str, without: str) -> str:
    """받침에 맞는 조사: josa('어흥염', '이', '가') → '어흥염이', josa('고릴타', '이랑', '랑') → '고릴타랑'."""
    ch = word[-1] if word else ''
    batchim = '가' <= ch <= '힣' and (ord(ch) - 0xAC00) % 28 != 0
    return word + (with_batchim if batchim else without)


def roles_text(summary: dict) -> str:
    return '·'.join(f'{k} {v}' for k, v in summary['roles'].items())


def other_warnings(check: dict) -> list[str]:
    """경고 중 약점 경고는 답변에서 뺀다 (남는 약점은 말하지 않음)."""
    return [w for w in check['warnings'] if not w.startswith('약점 3마리 이상')]


def role_of(check: dict, key: str) -> str:
    return next((', '.join(m['roles']) for m in check['members'] if m['pokemon'] == key), '')


def decide_need(check: dict) -> tuple[str, str, str | None]:
    """빈 포지션·이유·받아 줄 멤버가 필요한 약점 타입 (check_party 결과만으로)."""
    s = check['summary']
    roles, phys, spec = s['roles'], s['physical_attackers'], s['special_attackers']
    support = '서포터' if '서포터' in roles or check.get('_fmt') == 'doubles' else '기점잡이'
    top_weak = next(iter(s['weak_types_2plus']), None)
    if roles.get('랭크업 딜러') and not roles.get(support):
        return support, f"랭크업 딜러가 {roles['랭크업 딜러']}마리 있는데 판을 깔아 줄 {josa(support, '이', '가')} 없어요", None
    if phys == 0 and spec:
        return '물리 딜러', f'딜러가 특수 {spec}마리뿐이에요', None
    if spec == 0 and phys:
        return '특수 딜러', f'딜러가 물리 {phys}마리뿐이에요', None
    if not any(k.endswith('막이') for k in roles):
        return '막이', '대미지를 받아 줄 막이가 없어요', None
    if spec - phys >= 2:
        return '물리 딜러', f'특수 딜러 {spec}마리에 물리 딜러 {phys}마리라 물리 쪽이 적어요', None
    if phys - spec >= 2:
        return '특수 딜러', f'물리 딜러 {phys}마리에 특수 딜러 {spec}마리라 특수 쪽이 적어요', None
    if top_weak and s['weak_types_2plus'][top_weak] >= 3:
        n, c = s['weak_types_2plus'][top_weak], len(s['weak_cover'][top_weak])
        return (f'{top_weak} 받아 줄 포켓몬',
                f'{top_weak} 약점이 {n}마리인데 받아 줄 멤버는 {c}마리예요', top_weak)
    return '조합·상성', '역할은 이미 고르게 있어요', None


def weak_change(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """(장점 타입: 받아 줄 멤버가 늘거나 약점이 사라짐, 단점 타입: 약점 마리 수가 늘어남)."""
    b, a = before['summary'], after['summary']
    bw, aw = b['weak_types_2plus'], a['weak_types_2plus']
    good = [k for k in bw if (k in aw and len(a['weak_cover'][k]) > len(b['weak_cover'][k])) or k not in aw]
    bad = [k for k, v in aw.items() if v > bw.get(k, 0)]
    return good, bad


def pros_cons(before: dict, after: dict) -> str:
    good, bad = weak_change(before, after)
    parts = [f"장점: {', '.join(good)} 받아 줌" if good else '장점: 겹치는 약점을 받아 주진 않음']
    if bad:
        parts.append(f"단점: {', '.join(bad)} 약점 늘어남")
    return ' / '.join(parts)


def role_matches(roles: list[str], want: str) -> bool:
    """'물리 딜러'는 랭크업 딜러(물리)·혼합 딜러도 물리 쪽으로 보고, '막이'는 물리/특수막이를 다 포함."""
    for r in roles:
        if want in ('물리 딜러', '특수 딜러'):
            side = want[:2]
            if r.startswith(want) or (r.startswith('랭크업 딜러') and side in r) or r.startswith('혼합'):
                return True
        elif want == '막이':
            if '막이' in r.split(' (')[0]:
                return True
        elif r.startswith(want):
            return True
    return False


def search_args(key: str, role: str | None) -> dict:
    return {'pokemon': DEX.ko('pokemon', key), **({'role': role} if role else {})}


async def candidate_samples(tools: Tools, key: str, party: list[dict], role: str | None = None) -> tuple[list[dict], dict]:
    """search_samples(필요한 역할이 있으면 role로) 결과 중 정제 통과·도구 안 겹침·메가 수 안 넘김인 샘플들, 형태 분포."""
    res = await tools.run('search_samples', search_args(key, role))
    if not isinstance(res, dict):
        return [], {}
    items = {m['item'] for m in party if m.get('item')}
    megas = sum(DEX.is_stone(m.get('item', '')) for m in party)
    ok = [r for r in res.get('samples', []) if r['sample']['pokemon'] == key and r['sample']['item'] not in items
          and not DEX.odd(r['sample']) and not (DEX.is_stone(r['sample']['item']) and megas >= 2)]
    return ok, res.get('shapes') or {}


MIN_SHAPE_SHARE = 0.1     # 후보 샘플의 형태가 그 포켓몬 샘플 중 이 비율 이상일 때만
ROLE_ARG = {'막이': '막이', '물리 딜러': '물리 딜러', '특수 딜러': '특수 딜러', '기점잡이': '기점잡이', '서포터': '서포터'}


async def ranked_candidates(tools: Tools, fmt: str, party: list[dict], pool: list[dict], need: str, weak: str | None,
                            limit: int = 10) -> list[dict]:
    """후보(같이 쓰인 포켓몬 또는 픽률 순위)를 필요한 조건·장단점으로 점수 매김 (생성 코드의 계획용).
    후보마다 샘플 3개 중 조건에 맞는 샘플을 먼저 고른다."""
    base = DEX.party_check(party, fmt)
    have = {m['pokemon'] for m in party}
    out = []
    for p in pool:
        if p['id'] in have or len(out) >= limit:
            continue
        best = None
        role_arg = None if weak else ROLE_ARG.get(need)
        found, shapes = await candidate_samples(tools, p['id'], party, role_arg)
        if not found and role_arg:          # 그 역할 샘플이 없으면 일반 검색으로
            role_arg = None
            found, shapes = await candidate_samples(tools, p['id'], party)
        for r in found:
            after = DEX.party_check(party + [r['sample']], fmt)
            roles = after['members'][-1]['roles']
            # 그 포켓몬에서 잘 안 쓰는 형태(샘플의 10% 미만)는 후보로 안 씀 (예: 막이형 리자몽 1/137)
            share = shapes.get(roles[0].split(' (')[0], 0) / max(shapes.get('total', 0), 1)
            if not shapes.get('total') or share < MIN_SHAPE_SHARE:       # 형태 분포를 모르면 근거가 없어 뺌
                continue
            good, bad = weak_change(base, after)
            fits = (weak in good) if weak else (need == '조합·상성' or role_matches(roles, need))
            score = p.get('pct', 0) / 20 + (3 if fits else 0) + len(good) - len(bad) + share * 2
            score -= 1 if base['summary']['roles'].get(roles[0].split(' (')[0], 0) >= 2 else 0   # 이미 많은 역할
            c = {'partner': p, 'sample': r, 'roles': roles, 'score': score, 'fits': fits, 'bad': bad,
                 'shapes': shapes, 'role_arg': role_arg}
            if best is None or (c['fits'], c['score']) > (best['fits'], best['score']):
                best = c
        if best:
            out.append(best)
    out.sort(key=lambda c: -c['score'])
    return out


def pick_core(party: list[dict], fmt: str) -> dict:
    """같이 쓰인 포켓몬을 찾을 기준 멤버: 픽률이 가장 높은 고정 멤버."""
    return min(party, key=lambda m: DEX.rank[fmt].get(m['pokemon'], 999))


def short(s: dict) -> str:
    """답변용 짧은 표기: 이름 @ 도구. 메가스톤을 들면 메가 폼 이름 (육성형 전체는 추천 카드에)."""
    shown = shown_key(DEX.rid, s['pokemon'], s.get('item', ''))
    return f"{DEX.ko('pokemon', shown)} @ {DEX.ko('item', s['item']) if s.get('item') else '-'}"


def sp_of(check: dict, key: str) -> str:
    """check_party 결과의 SP 분배 (예: H2 C32 S32)."""
    return next((m['sp'] for m in check['members'] if m['pokemon'] == key), '')


# ---------------------------------------------------------------- 시나리오

FILL_ONE_Q = ['현재 파티에 어울리는 샘플 하나 추천해줘', '한 자리 남았는데 뭐 넣을까?', '마지막 한 마리 추천해줘',
              '이 파티에 부족한 포지션 채워줘']


def cand_line(c: dict, after: dict, base: dict, core_ko: str, partners: dict, fmt: str) -> str:
    p = c['partner']
    where = (f"{core_ko} 파티 {partners['teams']}개 중 {p['count']}개" if 'count' in p
             else f"{FORMAT_KO[fmt]} 픽률 {p['rank']}위")
    role = last_role(after).replace(' (', '·').replace(')', '')       # 랭크업 딜러 (물리) → 랭크업 딜러·물리
    shape, sh = c['roles'][0].split(' (')[0], c.get('shapes') or {}
    share = f", {shape}형 샘플 {sh[shape]}/{sh['total']}" if sh.get(shape) and sh.get('total') else ''
    return f"- {p['name_ko']} ({role}{share}) — {where}\n  {pros_cons(base, after)}"


def last_role(check: dict) -> str:
    return ', '.join(check['members'][-1]['roles'])


async def fill_one(rng, tools, fmt, party, question, src):
    """1번: 5마리 파티에 빈 포지션을 판단해 후보를 비교하고 1마리 추천 → "그 역할 말고" 후속."""
    d = Dialogue(tools, fmt, 'fill_one', ['후보 비교', '제약 준수', '장단점', '후속 수정', '한계 설명'])
    d.meta['conditions']['fixed'] = party
    d.meta['sources'] = src
    d.ask(question, party)
    base = await d.call('check_party', members=party)
    base['_fmt'] = fmt
    need, why, weak = decide_need(base)
    core = pick_core(party, fmt)
    core_ko = DEX.ko('pokemon', core['pokemon'])
    partners = await d.call('find_partners', pokemon=[core['pokemon']])
    cands = await ranked_candidates(tools, fmt, party, partners['partners'], need, weak)
    ranking = None
    if not any(c['fits'] for c in cands):          # 같이 쓰인 후보 중 맞는 게 없으면 픽률 순위에서
        ranking = await d.call('get_ranking', limit=30)
        pool = [{'id': x['id'], 'name_ko': x['name_ko'], 'rank': x['rank']} for x in ranking['items']]
        cands = await ranked_candidates(tools, fmt, party, pool, need, weak, limit=30)
    fits = [c for c in cands if c['fits']]
    if not fits or len(cands) < 2:
        raise Skip('맞는 후보 없음')
    a = fits[0]
    b = next((c for c in fits if c is not a and c['roles'] != a['roles']),
             next((c for c in cands if c is not a), None))
    for c in (a, b):
        await d.call('search_samples', **search_args(c['partner']['id'], c['role_arg']))
    after_a = await d.call('check_party', members=party + [a['sample']['sample']])
    after_b = await d.call('check_party', members=party + [b['sample']['sample']])
    await d.call('propose_party', members=party + [a['sample']['sample']])

    def why_pick(a, b) -> str:
        if not b['fits']:
            return f"{need}에 맞는 쪽이라서" if need != '조합·상성' else '장점이 더 많아서'
        if len(a['bad']) < len(b['bad']):
            return '단점이 더 적어서'
        return '같이 쓰인 횟수와 장점을 합쳐 더 나아서'

    head = f"**{need}**{josa(need, '을', '를')[len(need):]}" if need != '조합·상성' else ''
    if need == '조합·상성':
        text = f"지금 파티: {roles_text(base['summary'])}. 역할은 고르게 있어서 같이 쓰인 횟수와 상성으로 골랐어요.\n"
    else:
        text = f"지금 파티: {roles_text(base['summary'])}. {why}. 그래서 {head} 찾았어요.\n"
    if ranking:
        text += f"({josa(core_ko, '과', '와')} 같이 쓰인 포켓몬 중엔 없어서 픽률 상위 30마리에서 찾음)\n"
    text += (f"\n{cand_line(a, after_a, base, core_ko, partners, fmt)}\n{cand_line(b, after_b, base, core_ko, partners, fmt)}\n"
             f"\n→ **{short(a['sample']['sample'])}** ({sp_of(after_a, a['sample']['sample']['pokemon'])}) 추천 (화면에 띄움). "
             f"{why_pick(a, b)}요.".replace('서요.', '서예요.'))
    if other_warnings(after_a):
        text += '\n주의: ' + '; '.join(other_warnings(after_a))
    if not ranking and partners['teams'] < 10:
        text += f"\n참고: {josa(core_ko, '이', '가')} 든 상위 파티가 {partners['teams']}개뿐이라 같이 쓰인 횟수는 근거가 약해요."
    d.answer(text)

    # 후속: 추천한 역할 말고. 약점을 늘리는 후보는 억지로 추천하지 않는다
    role = a['roles'][0].split(' (')[0]
    if role.endswith('막이'):
        role = '막이'
    d.meta['conditions']['excluded_role'] = role
    d.ask(f'{role} 말고', party)
    # 빼 달라는 역할이 처음 필요했던 역할이면, 그 역할 대신 상성이 나아지는 쪽으로 다시 본다
    drop_need = need != '조합·상성' and not weak and role_matches([need], role)

    def ok(c):
        """빼 달라는 역할이 아니고, 처음 문제였던 약점을 악화시키지 않고, 3마리 이상 겹치는 약점을 새로 만들지 않고,
        이미 2마리 있는 역할이 아닌 후보."""
        if role_matches(c['roles'], role) or (weak and weak in c['bad']):
            return False
        after = DEX.party_check(party + [c['sample']['sample']], fmt)
        aw = after['summary']['weak_types_2plus']
        if any(aw.get(t, 0) >= 3 for t in c['bad']):
            return False
        if base['summary']['roles'].get(c['roles'][0].split(' (')[0], 0) >= 2:
            return False
        good, _ = weak_change(base, after)
        return bool(good) if drop_need else c['fits']
    if ranking:                 # 지난 턴 도구 결과는 대화에 남지 않으므로 다시 조회
        await d.call('get_ranking', limit=30)
    else:
        await d.call('find_partners', pokemon=[core['pokemon']])
    alt = [c for c in cands if ok(c)]
    if not alt and not ranking:             # 같이 쓰인 후보에 없으면 픽률 순위까지
        rank2 = await d.call('get_ranking', limit=30)
        pool = [{'id': x['id'], 'name_ko': x['name_ko'], 'rank': x['rank']} for x in rank2['items']]
        alt = [c for c in await ranked_candidates(tools, fmt, party, pool, need, weak, limit=30) if ok(c)]
    if not alt:
        if drop_need:
            what = "상성을 보완하면서 약점이 3마리 이상 겹치지 않는"
        elif weak:
            what = f"{weak} 공격을 받아 주면서 약점이 3마리 이상 겹치지 않는"
        else:
            what = f"{need}에 맞으면서 약점이 3마리 이상 겹치지 않는"
        d.answer(f"{josa(role, '을', '를')} 빼면 {what} 후보가 없어요. 억지로 넣으면 오히려 파티가 약해져요.\n"
                 f"- 앞에서 추천한 {josa(a['partner']['name_ko'], '을', '를')} 쓰거나\n"
                 f"- 지금 멤버 한 마리를 바꾸는 것까지 같이 볼 수 있어요 (바꿔도 되는 멤버를 알려 주세요)")
        return d
    alt.sort(key=lambda c: -c['score'])
    c = alt[0]
    await d.call('search_samples', **search_args(c['partner']['id'], c['role_arg']))
    after_c = await d.call('check_party', members=party + [c['sample']['sample']])
    await d.call('propose_party', members=party + [c['sample']['sample']])
    lead = (f"{josa(role, '을', '를')} 빼면 {need}는 채울 수 없어서, 대신 상성을 보완하는 쪽으로 봤어요.\n"
            if drop_need else f"{josa(role, '을', '를')} 빼고 다시 보면:\n")
    text = (lead + f"→ **{short(c['sample']['sample'])}** ({sp_of(after_c, c['sample']['sample']['pokemon'])}) 추천 (화면에 띄움)\n"
            f"{cand_line(c, after_c, base, core_ko, partners, fmt)}")
    if other_warnings(after_c):
        text += '\n주의: ' + '; '.join(other_warnings(after_c))
    d.answer(text)
    return d


async def team_from_search(d: Dialogue, tools, fmt, fixed: list[dict], core_key: str, partners: dict) -> tuple[dict, list]:
    """search_teams 결과에서 고정 멤버와 도구가 안 겹치고 정제를 통과하고 같이 쓰인 상위 포켓몬이 많은 팀 → get_team."""
    res = await d.call('search_teams', pokemon=DEX.ko('pokemon', core_key))
    top = {p['name_ko'] for p in partners['partners'][:6]}
    fixed_items = {m['item'] for m in fixed if m.get('item')}
    best = None
    for t in res.get('teams', []):
        team = await tools.run('get_team', {'id': t['id']})
        others = [m for m in team['members'] if m['sample']['pokemon'] not in {f['pokemon'] for f in fixed}]
        if any(m['sample']['item'] in fixed_items or DEX.odd(m['sample']) for m in others):
            continue
        overlap = sum(any(x in m['readable'].split(' @')[0] for x in top) for m in others)
        if best is None or overlap > best[0]:
            best = (overlap, t, team)
    if not best:
        raise Skip('맞는 팀 없음')
    team = await d.call('get_team', id=best[1]['id'])
    return best[1], team


def assemble(fixed: list[dict], team: dict) -> list[dict]:
    """고정 멤버 + 팀의 나머지 (같은 포켓몬은 고정 멤버 육성 우선, 메가스톤은 2개까지)."""
    party = list(fixed)
    megas = sum(DEX.is_stone(m.get('item', '')) for m in party)
    for m in team['members']:
        s = m['sample']
        if len(party) >= 6 or s['pokemon'] in {p['pokemon'] for p in party}:
            continue
        if DEX.is_stone(s['item']):
            if megas >= 2:
                continue
            megas += 1
        party.append(s)
    return party


def party_lines(check: dict, members: list[dict]) -> str:
    """추천 멤버: 이름 @ 도구 (SP 분배). 역할·기술은 추천 카드를 누르면 보임."""
    return '\n'.join(f"- {short(m)} ({sp_of(check, m['pokemon'])})" for m in members)


def party_tail(check: dict) -> str:
    s = check['summary']
    text = f"구성: {roles_text(s)} / 메가진화 포켓몬 {s['mega_pokemon']}마리"
    if other_warnings(check):
        text += '\n주의: ' + '; '.join(other_warnings(check))
    return text


CORE_Q = ['{name_rang} 어울리는 파티 짜줘', '{name} 중심으로 파티 만들어줘', '{name} 쓰고 싶은데 파티 짜줘']


async def core_team(rng, tools, fmt, fixed, question, follow, src):
    """2·5번: 핵심 포켓몬 1마리로 실제 상위 파티를 바탕으로 6마리 → 도구 질문 / "이게 최선이야?"."""
    d = Dialogue(tools, fmt, 'core_team', ['조합 근거', '제약 준수'] + (['후속 질문'] if follow else []))
    d.meta['conditions']['fixed'] = fixed
    d.meta['sources'] = src
    core = fixed[0]
    name = DEX.ko('pokemon', core['pokemon'])
    d.ask(question.format(name=name, name_rang=josa(name, '이랑', '랑')), fixed)
    partners = await d.call('find_partners', pokemon=[core['pokemon']])
    t, team = await team_from_search(d, tools, fmt, fixed, core['pokemon'], partners)
    d.meta['sources']['team_ids'] = [t['id']]
    party = assemble(fixed, team)
    if len(party) < 6:
        raise Skip('6마리가 안 됨')
    check = await d.call('check_party', members=party)
    await d.call('propose_party', members=party)
    used = [p for p in partners['partners'][:8] if p['id'] in {m['pokemon'] for m in party}]
    text = (f"상위 파티 '{t['title']}'({t['source']})를 바탕으로 짰어요. {name} 육성은 그대로예요 (화면에 띄움).\n"
            + party_lines(check, party[1:]) + '\n\n')
    if used:
        text += (f"{josa(name, '이', '가')} 든 상위 파티 {partners['teams']}개 중 같이 쓰인 비율: "
                 + ', '.join(f"{p['name_ko']} {p['pct']}%" for p in used[:3]) + '\n')
    d.answer(text + party_tail(check))
    if follow == 'item':
        await follow_item(d, party, core)
    elif follow == 'best':
        await follow_best(d, party, core)
    return d


async def follow_item(d: Dialogue, party: list[dict], core: dict):
    """사용률을 먼저 보여 주고, 지금 파티에서 겹치지 않는 메타 도구를 추천 (바꾸지는 않음)."""
    name, item = DEX.ko('pokemon', core['pokemon']), DEX.ko('item', core['item'])
    d.ask(f'{name} {item} 말고 쓰는 아이템 뭐가 있을까?', party)
    info = await d.call('get_pokemon', id=core['pokemon'])
    u = info.get('usage') or {}
    items = u.get('item', [])
    others = [x for x in items if x['id'] != core['item']]
    if not others:
        d.answer(f'{name}의 {FORMAT_KO[d.fmt]} 도구 사용률 데이터에는 {item} 말고 다른 도구가 없어요.')
        return
    taken = {m['item']: DEX.ko('pokemon', m['pokemon']) for m in party if m['pokemon'] != core['pokemon']}
    usage = ' · '.join(f"{x['name_ko']} {x['pct']}%" for x in items[:5])
    pick = next((x for x in others if x['id'] not in taken and not DEX.is_stone(x['id'])), None)
    text = f"{FORMAT_KO[d.fmt]} {name} 도구 사용률: {usage}\n\n"
    skipped = [x for x in others[:3] if x['id'] in taken]
    if pick:
        text += f"지금 파티라면 **{pick['name_ko']}**{josa(pick['name_ko'], '이', '가')[len(pick['name_ko']):]} 좋아요. {item} 다음으로 많이 쓰이고 다른 멤버와 안 겹쳐요."
    else:
        text += '사용률 상위 도구는 지금 파티의 다른 멤버와 모두 겹쳐요.'
    if skipped:
        text += '\n(' + ', '.join(f"{x['name_ko']}는 {josa(taken[x['id']], '이', '가')} 들고 있어서 제외" for x in skipped) + ')'
    d.answer(text)
    if not pick:
        return
    # 후속: 추천한 도구도 싫다고 하면 다음 후보로 이어 가기
    d.ask(d.rng.choice([f"{pick['name_ko']} 말고 다른 거 없어?", '다른 템으로 바꾸고 싶어', f"{pick['name_ko']}는 별로야"]), party)
    info = await d.call('get_pokemon', id=core['pokemon'])
    items = (info.get('usage') or {}).get('item', [])
    nxt = next((x for x in items if x['id'] not in (core['item'], pick['id']) and x['id'] not in taken
                and not DEX.is_stone(x['id'])), None)
    if not nxt:
        d.answer(f"{pick['name_ko']} 말고는 사용률 데이터에서 다른 멤버와 안 겹치는 도구가 더 없어요. "
                 "다른 멤버의 도구를 바꾸는 것까지 같이 볼까요?")
        return
    d.answer(f"{pick['name_ko']} 말고 다른 템으로 바꾸고 싶다면 **{nxt['name_ko']}**({nxt['pct']}%){josa(nxt['name_ko'], '이', '가')[len(nxt['name_ko']):]} 다음이에요. "
             "이것도 지금 파티의 다른 멤버와 안 겹쳐요.")


async def follow_best(d: Dialogue, party: list[dict], core: dict):
    name = DEX.ko('pokemon', core['pokemon'])
    d.ask('이게 최선이야?', party)
    partners = await d.call('find_partners', pokemon=[core['pokemon']])
    check = await d.call('check_party', members=party)
    have = {m['pokemon'] for m in party}
    missing = [p for p in partners['partners'][:6] if p['id'] not in have][:2]
    text = ("최선이라고 단정할 수는 없어요. 제가 가진 데이터는 픽률·같이 쓰인 횟수·상성·역할이고, 승률이나 대미지 계산은 없거든요.\n"
            f"이 기준으로는 {josa(name, '이', '가')} 든 상위 파티 {partners['teams']}개에서 자주 같이 쓰인 포켓몬 위주로, "
            f"{roles_text(check['summary'])} 구성이에요.\n")
    if missing:
        text += ('대안: 같이 많이 쓰였지만 지금 파티에 없는 '
                 + ', '.join(f"{p['name_ko']}({p['pct']}%)" for p in missing) + '를 넣는 방법도 있어요.\n')
    text += '원하는 컨셉(막이 사이클, 스윕, 컨셉 파티 등)이나 꼭 넣고·빼고 싶은 포켓몬을 알려 주면 거기에 맞춰 다시 짤게요.'
    d.answer(text)


MOVES_Q = ['{name} 스킬 뭐 줘야해?', '{name} 기술 배치 추천해줘', '{name} 기술 4개 골라줘']
STAT_EN = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')


async def fill_moves(rng, tools, fmt, party, target_idx, question, src):
    """3번: 기술이 빈 멤버의 기술 → "메가진화 써 일반 써?" (종족값 변화·장단점)."""
    d = Dialogue(tools, fmt, 'fill_moves', ['샘플·사용률 근거', '제약 준수', '후속 비교', '장단점'])
    target = dict(party[target_idx])
    key = target['pokemon']
    name = DEX.ko('pokemon', key)
    screen = [dict(m) for m in party]
    screen[target_idx] = {**target, 'moves': []}
    d.meta['conditions']['fixed'] = [m for i, m in enumerate(party) if i != target_idx]
    d.meta['conditions']['target'] = key
    d.meta['sources'] = src
    d.ask(question.format(name=name), screen)
    info = await d.call('get_pokemon', id=key)
    res = await d.call('search_samples', pokemon=name)
    rows = res.get('samples', []) if isinstance(res, dict) else []
    mine = [r for r in rows if r['sample']['pokemon'] == key and not DEX.odd(r['sample'])]
    pick = next((r for r in mine if r['sample']['item'] == target['item']), None) or (mine[0] if mine else None)
    if not pick:
        raise Skip('샘플 없음')
    moves = pick['sample']['moves']
    filled = [dict(m) for m in screen]
    filled[target_idx] = {**target, 'moves': moves}
    check = await d.call('check_party', members=filled)
    await d.call('propose_party', members=filled)
    pct = {x['id']: x['pct'] for x in (info.get('usage') or {}).get('move', [])}
    mv = ', '.join(DEX.ko('move', m) + (f" {pct[m]}%" if m in pct else '') for m in moves)
    label = pick['source'] if pick['source'].endswith('샘플') else pick['source'] + ' 샘플'
    text = (f"{label} 기술 배치를 추천해요 (도구·SP는 그대로, 화면에 띄움).\n- {mv}\n"
            + (f"  (%: {FORMAT_KO[fmt]} 기술 사용률)\n" if any(m in pct for m in moves) else '')
            + f"- 역할: {', '.join(check['members'][target_idx]['roles'])} / 파티: {roles_text(check['summary'])}")
    if other_warnings(check):
        text += '\n주의: ' + '; '.join(other_warnings(check))
    d.answer(text)

    forms = info.get('forms', [])
    mega = next((f for f in forms if f.get('mega_stone')), None)
    stone = mega and next((i for i, row in DEX.n['item'].items() if row['name'] == mega['mega_stone']), None)
    if not stone:
        return d
    d.ask(f'{name} 메가진화 써 아니면 일반 {name} 써?', filled)
    info2 = await d.call('get_pokemon', id=key)
    with_stone = [dict(m) for m in filled]
    with_stone[target_idx] = {**filled[target_idx], 'item': stone}
    check2 = await d.call('check_party', members=with_stone)
    items = {x['id']: x['pct'] for x in (info2.get('usage') or {}).get('item', [])}
    base_s, mega_s = forms[0]['stats'], mega['stats']
    delta = {k: mega_s[k] - base_s[k] for k in STAT_EN if mega_s[k] != base_s[k]}
    diff = ', '.join(f"{k} {v:+d}" for k, v in delta.items())
    up = [k for k, v in delta.items() if v > 0]
    down = [k for k, v in delta.items() if v < 0]
    abil = ', '.join(a['name_ko'] for a in mega['abilities'])
    stone_ko, cur_ko = DEX.ko('item', stone), DEX.ko('item', target['item'])
    megas = check2['summary']['mega_pokemon']
    pros = [f"{'·'.join(up)} 상승" if up else None, f"특성 {abil}"]
    cons = [f"{'·'.join(down)} 하락" if down else None, f"{josa(cur_ko, '을', '를')} 못 듦",
            f"메가진화 포켓몬 {megas}마리 → 선출 제한" if megas > 2 else None]
    use = (f"사용률: {stone_ko} {items[stone]}%" if stone in items else f"사용률 상위 6개에 {josa(stone_ko, '은', '는')} 없음")
    use += f", {cur_ko} {items[target['item']]}%" if target['item'] in items else ''
    text = (f"메가진화 변화: {diff}\n- 장점: {', '.join(x for x in pros if x)}\n- 단점: {', '.join(x for x in cons if x)}\n"
            f"- {FORMAT_KO[fmt]} {use}\n\n")
    if megas > 2:
        text += f"이미 메가가 {megas - 1}마리라 지금 파티에서는 **일반 {name} + {cur_ko}**를 추천해요."
    elif stone in items and target['item'] in items and items[stone] > items[target['item']]:
        text += f"메가진화 포켓몬이 {megas}마리라 부담이 없고 사용률도 메가 쪽이 높아서 **메가 {name}**도 좋아요."
    else:
        text += f"사용률은 일반 쪽이 높아서, 특별한 이유가 없으면 **일반 {name}**가 무난해요."
    d.answer(text, derived=[abs(v) for v in delta.values()] + [megas - 1])
    return d


REST_Q = ['나머지 대충 어울리게 짜줘', '남은 자리 알아서 채워줘', '이 둘이랑 어울리게 파티 완성해줘']


async def fill_rest(rng, tools, fmt, fixed, question, src):
    """4번: 2마리 고정 → 나머지 4마리 → "약점 다 찌르는 포켓몬 누가 있어?"."""
    d = Dialogue(tools, fmt, 'fill_rest', ['조합 근거', '제약 준수', '후속 질문'])
    d.meta['conditions']['fixed'] = fixed
    d.meta['sources'] = src
    d.ask(question, fixed)
    both = await d.call('find_partners', pokemon=[m['pokemon'] for m in fixed])
    core = pick_core(fixed, fmt)
    core_ko = DEX.ko('pokemon', core['pokemon'])
    partners = both if both['teams'] >= 5 else await d.call('find_partners', pokemon=[core['pokemon']])
    t, team = await team_from_search(d, tools, fmt, fixed, core['pokemon'], partners)
    d.meta['sources']['team_ids'] = [t['id']]
    party = assemble(fixed, team)
    if len(party) < 6:
        raise Skip('6마리가 안 됨')
    check = await d.call('check_party', members=party)
    await d.call('propose_party', members=party)
    names_fixed = '·'.join(DEX.ko('pokemon', m['pokemon']) for m in fixed)
    if both['teams'] < 5:
        text = (f"{josa(names_fixed, '이', '가')} 같이 든 상위 파티는 {both['teams']}개뿐이라, {josa(core_ko, '이', '가')} 든 "
                f"상위 파티 '{t['title']}'를 바탕으로 짰어요 (화면에 띄움).\n")
    else:
        text = f"{josa(names_fixed, '이', '가')} 같이 든 상위 파티 '{t['title']}'를 바탕으로 짰어요 (화면에 띄움).\n"
    d.answer(text + party_lines(check, party[len(fixed):]) + '\n\n' + party_tail(check))

    d.ask('이거 약점 다 찌르는 포켓몬 누가있어?', party)
    th = await d.call('find_threats', members=[{'pokemon': m['pokemon'], 'item': m['item']} for m in party])
    if not th['threats']:
        d.answer(f"픽률 상위 {th['checked_top']}마리 중에 {th['need_hits']}마리 이상을 약점으로 찌르는 포켓몬은 없어요.")
        return d
    lines = []
    for x in th['threats'][:3]:
        types = list(dict.fromkeys(re.findall(r'\((\S+) ×', ' '.join(x['targets']))))
        line = f"- {x['name_ko']} (픽률 {x['rank']}위) — {x['hits']}마리, {'·'.join(types)} 공격"
        rare = [re.match(r'\S+←(.+?) (\d+(?:\.\d+)?)%\((\S+) ×', t) for t in x.get('sometimes', [])]
        rare = list(dict.fromkeys(f"{m.group(1)} {m.group(2)}%" for m in rare if m))
        if rare:
            line += f"\n  가끔: {', '.join(rare)}"
        lines.append(line)
    d.answer(f"픽률 상위 {th['checked_top']}마리 중 자주 쓰는 기술로 우리 파티 {th['need_hits']}마리 이상을 찌르는 포켓몬이에요.\n"
             + '\n'.join(lines) + '\n(기술 사용률 10% 이상만 셈'
             + (', "가끔"은 그보다 드물게 쓰는 기술' if any('가끔' in x for x in lines) else '')
             + '. 특성에 의한 무효·대미지 크기는 반영 안 함)')
    return d


CLARIFY_Q = ['파티 짜줘', '좋은 파티 하나 만들어줘', '파티 추천해줘']


async def clarify(rng, tools, fmt, question, core_key, src):
    """확인 질문: 화면이 비어 있고 핵심 포켓몬·컨셉을 모름 → 되묻기 → 답을 받아 짜기."""
    d = Dialogue(tools, fmt, 'clarify', ['확인 질문', '조합 근거'])
    d.meta['sources'] = src
    d.ask(question, [])
    d.answer(f"{FORMAT_KO[fmt]} 파티로 짤게요. 두 가지만 알려 주세요.\n"
             "- 꼭 넣고 싶은 핵심 포켓몬 (없으면 픽률 상위에서 골라 볼게요)\n"
             "- 컨셉: 막이 사이클, 스윕, 균형, 한 타입 컨셉 파티 등 (안 정하면 균형 파티)")
    name = DEX.ko('pokemon', core_key)
    d.ask(f'{name} 넣고 균형 있게', [])
    partners = await d.call('find_partners', pokemon=[core_key])
    t, team = await team_from_search(d, tools, fmt, [], core_key, partners)
    d.meta['sources']['team_ids'] = [t['id']]
    party = assemble([], team)
    check = await d.call('check_party', members=party)
    await d.call('propose_party', members=party)
    d.answer(f"{josa(name, '이', '가')} 든 상위 파티 '{t['title']}'를 바탕으로 했어요 (화면에 띄움).\n"
             + party_lines(check, party) + '\n\n' + party_tail(check))
    return d


async def full_party(rng, tools, fmt, party, src):
    """한계: 이미 6마리인데 더 추천 → 6마리가 최대라고 말하고, 역할이 겹치는 멤버를 바꿀 후보로."""
    d = Dialogue(tools, fmt, 'full_party', ['한계 설명', '근거'])
    d.meta['conditions']['fixed'] = party
    d.meta['sources'] = src
    d.ask(rng.choice(['한 마리 더 추천해줘', '여기에 하나 더 넣고 싶어']), party)
    check = await d.call('check_party', members=party)
    roles = check['summary']['roles']
    dup = max(roles.items(), key=lambda kv: kv[1])
    who = [m['name_ko'] for m in check['members'] if any(r.startswith(dup[0]) for r in m['roles'])]
    d.answer(f"파티는 6마리가 최대라 더 넣을 수 없어요. 대신 한 마리를 바꿀 수는 있어요.\n"
             f"지금은 {josa(dup[0], '이', '가')} {dup[1]}마리({', '.join(who)})로 가장 많아서, 바꾼다면 이 중 하나가 무난해요. "
             "바꿀 멤버나 넣고 싶은 포켓몬을 알려 주세요.")
    return d


# 이번 레귤레이션 목록에 없는지 실행할 때 다시 확인한다 (있으면 안 씀)
NOT_IN_DEX = ['뮤츠', '레쿠쟈', '가이오가', '그란돈', '자시안', '무한다이노', '칼라이트', '버드렉스']


async def not_found(rng, tools, fmt, name, src):
    """한계: 이번 레귤레이션에 없는(검색되지 않는) 포켓몬 → 지어내지 않고 정직하게, 다시 묻기."""
    d = Dialogue(tools, fmt, 'not_found', ['검색 실패', '한계 설명', '확인 질문'])
    d.meta['sources'] = src
    d.ask(rng.choice([f'{name} 샘플 짜줘', f'{name} 어떻게 키워?', f'{name} 넣은 파티 짜줘']), [])
    hits = await d.call('search_pokemon', query=name)
    if any(isinstance(h, dict) and h.get('id') for h in hits):
        raise Skip('검색됨')
    d.answer(f"'{name}'을(를) 지금 레귤레이션(M-C) 포켓몬 목록에서 찾지 못했어요. 이번 레귤레이션에서 쓸 수 없거나 "
             "이름이 다르게 적혔을 수 있어요. 데이터에 없는 포켓몬이라 지어서 추천하지는 않을게요.\n"
             "정확한 이름이나 다른 포켓몬을 알려 주면 바로 찾아볼게요.")
    return d


# ---------------------------------------------------------------- 검수용 묶음

async def build_review(n: int, seed: int) -> list[Dialogue]:
    rng = random.Random(seed)
    out: list[Dialogue] = []
    async with back_client() as client:
        def T(fmt):
            return Tools(client, fmt)

        async def add(coro, group):
            try:
                d = await coro
            except Skip as e:
                print('  건너뜀:', e)
                return False
            d.meta['group'] = group
            out.append(d)
            return True

        # 사용자 질문 5개 (그대로)
        fmt, party, ids = user_party('q1')
        await add(fill_one(rng, T(fmt), fmt, party, '현재 파티에 어울리는 샘플 하나 추천해줘', {'sample_ids': ids}), 'user:q1')
        fmt, party, ids = user_party('q2')
        await add(core_team(rng, T(fmt), fmt, party, '{name_rang} 어울리는 파티 짜줘', 'item', {'sample_ids': ids}), 'user:q2')
        fmt, party, ids = user_party('q3')
        await add(fill_moves(rng, T(fmt), fmt, party, 0, '{name} 스킬 뭐 줘야해?', {'sample_ids': ids}), 'user:q3')
        fmt, party, ids = user_party('q4')
        await add(fill_rest(rng, T(fmt), fmt, party, '나머지 대충 어울리게 짜줘', {'sample_ids': ids}), 'user:q4')
        fmt, party, ids = user_party('q5')
        await add(core_team(rng, T(fmt), fmt, party, '{name_rang} 어울리는 파티 짜줘', 'best', {'sample_ids': ids}), 'user:q5')

        plan = [('fill_one', 3), ('core_team', 3), ('fill_moves', 2), ('fill_rest', 2), ('clarify', 2),
                ('full_party', 1), ('not_found', 2)]
        for kind, count in plan:
            made, tries = 0, 0
            while made < count and tries < 30:
                tries += 1
                fmt = rng.choice(list(FORMAT_KO))
                tid, team = rng.choice(DEX.teams[fmt])
                group = f'team:{tid}'
                if kind == 'fill_one':
                    i = rng.randrange(6)
                    ok = await add(fill_one(rng, T(fmt), fmt, team[:i] + team[i + 1:], rng.choice(FILL_ONE_Q),
                                            {'team_ids': [tid]}), group)
                elif kind == 'core_team':
                    core = rng.choice(team)
                    ok = await add(core_team(rng, T(fmt), fmt, [core], rng.choice(CORE_Q), rng.choice(['item', 'best']),
                                             {'team_ids': [tid]}), group)
                elif kind == 'fill_moves':
                    megas = [i for i, m in enumerate(team) if (DEX.n['pokemon'].get(m['pokemon'] + 'mega'))]
                    i = rng.choice(megas or list(range(6)))
                    ok = await add(fill_moves(rng, T(fmt), fmt, team, i, rng.choice(MOVES_Q), {'team_ids': [tid]}), group)
                elif kind == 'fill_rest':
                    two = rng.sample(team, 2)
                    ok = await add(fill_rest(rng, T(fmt), fmt, two, rng.choice(REST_Q), {'team_ids': [tid]}), group)
                elif kind == 'clarify':
                    core = min(team, key=lambda m: DEX.rank[fmt].get(m['pokemon'], 999))['pokemon']
                    ok = await add(clarify(rng, T(fmt), fmt, rng.choice(CLARIFY_Q), core, {'team_ids': [tid]}),
                                   f'pokemon:{core}')
                elif kind == 'full_party':
                    ok = await add(full_party(rng, T(fmt), fmt, team, {'team_ids': [tid]}), group)
                else:
                    pool = [x for x in NOT_IN_DEX if not any(x == (p['name_ko'] or '') for p in DEX.n['pokemon'].values())]
                    if not pool:
                        break
                    name = rng.choice(pool)
                    ok = await add(not_found(rng, T(fmt), fmt, name, {'name': name}), f'name:{name}')
                made += ok
    return out[:n]


# ---------------------------------------------------------------- 저장

def data_version() -> dict:
    db = ROOT / 'data/pokemon.db'
    sha = hashlib.sha1(db.read_bytes()).hexdigest()[:12]
    try:
        commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ''
    return {'db_sha1': sha, 'git': commit, 'ruleset': DEX.rid}


def to_row(i: int, d: Dialogue, version: dict) -> dict:
    return {
        'id': f'v2-{i:04d}', **d.meta, 'data_version': version,
        'review': {'status': 'pending', 'notes': ''},
        'auto_checks': auto_checks(d),
        'turns': [{'user': t['user'], 'party': t['party'], 'steps': t['steps'], 'final': t['final'],
                   'proposed': t['proposed']} for t in d.turns],
        'records': d.records(),
    }


def clip(v, n=260) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + ' …'


def to_markdown(rows: list[dict]) -> str:
    out = ['# 파인튜닝 데이터 v2 검수용\n',
           '각 대화의 **코치 답변**이 원하는 행동인지 봐 주세요. 도구 결과는 앞부분만 보입니다 (전체는 review.jsonl).\n']
    for r in rows:
        c = r['auto_checks']
        mark = '✅' if c['ok'] else '⚠'
        out.append(f"\n---\n\n## {r['id']} · {r['scenario']} · {FORMAT_KO[r['format']]} {mark}\n")
        out.append(f"- 행동: {', '.join(r['behaviors'])}\n- 묶음: `{r['group']}`  원본: `{json.dumps(r['sources'], ensure_ascii=False)}`")
        fixed = r['conditions'].get('fixed')
        if fixed:
            out.append('- 고정 멤버: ' + ', '.join(short(m) for m in fixed))
        problems = [k for k in ('fixed_kept', 'no_duplicates', 'excluded_respected', 'mega_stones_le_2') if not c[k]]
        if c['tool_errors'] or c['ungrounded_numbers'] or problems or c['odd_samples']:
            out.append(f"- 자동 검사 문제: {problems} 도구 오류 {c['tool_errors']} 근거 없는 숫자 {c['ungrounded_numbers']}"
                       f" 이상한 샘플 {c['odd_samples']}")
        for k, t in enumerate(r['turns'], 1):
            party = ', '.join(short(m) for m in t['party']) or '비어 있음'
            out.append(f"\n### 턴 {k}\n**사용자**: {t['user']}  \n<sub>화면 파티: {party}</sub>\n")
            for s in t['steps']:
                if s.get('tool_calls'):
                    f = s['tool_calls'][0]['function']
                    out.append(f"- 🔧 `{f['name']}` {clip(f['arguments'], 160)}")
                else:
                    out.append(f"  - ↳ {clip(s['content'])}")
            out.append(f"\n**코치**:\n\n{t['final']}\n")
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--review', type=int, default=20, help='검수용 대화 수')
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    global DEX
    DEX = Dex()
    dialogues = asyncio.run(build_review(args.review, args.seed))
    version = data_version()
    rows = [to_row(i, d, version) for i, d in enumerate(dialogues, 1)]
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / 'review.jsonl', 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    (OUT / 'review.md').write_text(to_markdown(rows), encoding='utf-8')
    print(f"대화 {len(rows)}개 (자동 검사 통과 {sum(r['auto_checks']['ok'] for r in rows)}) → {OUT / 'review.md'}")
    print(Counter(r['scenario'] for r in rows))


if __name__ == '__main__':
    main()
