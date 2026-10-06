"""파인튜닝 학습 데이터 생성 (유료 API 없음): DB의 실제 파티·샘플로 파티 빌딩·샘플 제작 대화를 만든다.

- 도구 결과: llm/agent/tools.py를 back(Django)에 직접 붙여 실행한 실제 값 (서버를 띄울 필요 없음)
- 정답: OP.GG 상위 파티·VGCPastes 대회 팀에 실제로 있던 포켓몬, OP.GG·대회 샘플의 육성형
- 답변: 도구 결과로만 채우는 틀. 답변 속 숫자가 도구 결과에 없으면 버린다
- Showdown 리플레이는 쓰지 않는다 (레이팅이 낮고 인게임 메타와 다름)

    cd llm
    ..\\.venv\\Scripts\\python training\\make_data.py --n 1000      # → training/train.jsonl, eval.jsonl

대화 종류 (비율)
    sample_top   "○○ 샘플 짜줘"                → 샘플 검색 → 화면에 카드
    sample_item  "○○ 구애스카프 샘플"           → 샘플 검색 → 그 도구를 든 샘플
    sample_usage "○○ 사용률 기준으로 짜줘"      → 사용률 조회 → 직접 조합 → 검사(틀리면 고침) → 카드
    fill         실제 파티에서 1~2마리 빼고 "채워줘" → 상성 → 뺀 포켓몬 샘플 → 상성 비교 → 카드
    fix_weak     실제 파티에서 약점 3마리 이상 타입 → 한 마리 교체 → 상성 비교 → 카드
"""
import argparse
import asyncio
import json
import random
import re
from collections import Counter
from pathlib import Path

LLM = Path(__file__).resolve().parents[1]

from inproc_back import back_client  # noqa: E402  (Django 설정도 여기서)

from agent.prompt import screen_context  # noqa: E402
from agent.tools import ToolError, Tools  # noqa: E402
from apps.api.common import names  # noqa: E402
from apps.api.views import norm_nature, rank_board, shown_key  # noqa: E402
from apps.dex.models import Ruleset  # noqa: E402
from apps.dex.typechart import TYPE_KO, TYPES, defense_profile  # noqa: E402
from apps.meta.models import SP_STATS, PokemonSet, Team  # noqa: E402

FMT_KO = {'singles': '싱글', 'doubles': '더블'}
KINDS = {'sample_top': 15, 'sample_item': 10, 'sample_usage': 15, 'fill': 40, 'fix_weak': 20}


# ---------- DB에서 재료 ----------

class Dex:
    def __init__(self):
        self.rs = Ruleset.objects.order_by('-start_date').first()
        self.n = names(self.rs.id)
        self.teams = {f: [] for f in FMT_KO}
        qs = Team.objects.filter(ruleset=self.rs, source__in=['opgg_replica', 'vgcpastes'], is_legal=True) \
            .prefetch_related('members')
        for t in qs:
            ms = list(t.members.all())
            if len(ms) == 6:
                self.teams[t.format_key.rsplit('_', 1)[-1]].append([self.sample(m) for m in ms])
        # 샘플이 있는 포켓몬 (OP.GG 샘플 기준) × 픽률 순위
        self.with_samples = {f: sorted(set(PokemonSet.objects.filter(
            ruleset=self.rs, format_key=f'{self.rs.id}_{f}', source='opgg_sample').values_list('pokemon_key', flat=True)))
            for f in FMT_KO}
        self.rank = {f: {k: r['rank'] for k, r in rank_board(self.rs, f)['rows'].items()} for f in FMT_KO}

    @staticmethod
    def sample(m) -> dict:
        return {'pokemon': m.pokemon_key, 'item': m.item_key, 'ability': m.ability_key,
                'nature': norm_nature(m.nature_key), 'sp': {s: getattr(m, f'sp_{s}') for s in SP_STATS if getattr(m, f'sp_{s}')},
                'moves': ([*m.moves, '', '', '', ''])[:4]}

    def ko(self, kind: str, key: str) -> str:
        row = self.n[kind].get(key) or {}
        return row.get('name_ko') or row.get('name') or key

    def types(self, s: dict) -> list[str]:
        """화면 기준 타입 (메가스톤을 들면 메가 폼)."""
        p = self.n['pokemon'][shown_key(self.rs.id, s['pokemon'], s['item'])]
        return [t for t in (p['type1'], p['type2']) if t]

    def is_mega_stone(self, item: str) -> bool:
        return bool((self.n['item'].get(item) or {}).get('mega_to'))

    def pick_pokemon(self, rng: random.Random, fmt: str) -> str:
        """샘플이 있는 포켓몬을 픽률 상위 위주로 고른다."""
        keys = self.with_samples[fmt]
        w = [1 / (self.rank[fmt].get(k, 150) ** 0.5) for k in keys]
        return rng.choices(keys, w)[0]

    def weak_counts(self, party: list[dict]) -> dict[str, int]:
        profs = [defense_profile(self.types(s)) for s in party]
        return {a: sum(p[a] > 1 for p in profs) for a in TYPES}


# ---------- 대화 기록 ----------

class Skip(Exception):
    """이 대화는 만들지 않음 (재료가 안 맞음)."""


class Conv:
    def __init__(self, tools: Tools, fmt: str, party: list, question: str):
        self.tools = tools
        self.msgs = [{'role': 'user', 'content': screen_context(fmt, party + [None] * (6 - len(party))) + '\n\n' + question}]

    async def call(self, name: str, **args):
        try:
            out = await self.tools.run(name, args)
        except ToolError as e:
            out = str(e)
        self.msgs.append({'role': 'assistant', 'content': '',
                          'tool_calls': [{'type': 'function', 'function': {'name': name, 'arguments': args}}]})
        self.msgs.append({'role': 'tool', 'content': out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)})
        return out

    def answer(self, text: str) -> list[dict]:
        self.msgs.append({'role': 'assistant', 'content': text.strip()})
        return self.msgs


def numbers_grounded(msgs: list[dict]) -> bool:
    """마지막 답변의 숫자가 모두 사용자 메시지·도구 결과에 있는지 (외워서 말한 수치 방지)."""
    seen = ' '.join(m['content'] for m in msgs if m['role'] in ('user', 'tool'))
    have = set(re.findall(r'\d+(?:\.\d+)?', seen))
    return all(n in have for n in re.findall(r'\d+(?:\.\d+)?', msgs[-1]['content']))


def matching(results, pokemon: str, avoid_items=(), avoid_mega=False) -> list[dict]:
    """search_samples 결과 중 그 포켓몬 자신의 샘플 (도구 겹침·메가 둘 피함)."""
    if not isinstance(results, list):
        return []
    return [r for r in results if 'sample' in r and r['sample']['pokemon'] == pokemon
            and r['sample']['item'] not in avoid_items and not (avoid_mega and DEX.is_mega_stone(r['sample']['item']))]


def weak_line(before: dict, after: dict) -> list[str]:
    """analyze_party 결과 두 개로 약점 마리 수 변화 문장 (도구 결과 숫자만)."""
    b, a = before['by_attack_type'], after['by_attack_type']
    lines = []
    for t in TYPE_KO.values():
        x, y = (b.get(t) or {}).get('weak', 0), (a.get(t) or {}).get('weak', 0)
        if y < x:
            lines.append(f'{t} 약점 {x}마리 → {y}마리')
    return lines


def worst(after: dict, n: int = 3) -> list[str]:
    return [f'{t} {c["weak"]}마리' for t, c in after['by_attack_type'].items() if c['weak'] >= n]


async def proposed(conv: Conv, members: list[dict]) -> None:
    out = await conv.call('propose_party', members=members)
    if not (isinstance(out, dict) and out.get('shown')):
        errs = [e for p in out.get('problems', []) for e in p['errors']] if isinstance(out, dict) else [str(out)]
        raise Skip('propose_party 실패: ' + re.sub(r'[:은].*', '', errs[0] if errs else '?'))


# ---------- 대화 종류 ----------

async def sample_top(rng, tools, fmt):
    key = DEX.pick_pokemon(rng, fmt)
    name = DEX.ko('pokemon', key)
    q = rng.choice([f'{name} 샘플 짜줘', f'{name} 육성 어떻게 해?', f'{name} 쓰고 싶은데 샘플 하나 추천해줘',
                    f'{FMT_KO[fmt]}용 {name} 샘플 보여줘', f'{name} 어떻게 키워?'])
    c = Conv(tools, fmt, [], q)
    res = matching(await c.call('search_samples', pokemon=name), key)
    if not res:
        raise Skip('샘플 없음')
    top = res[0]
    await proposed(c, [top['sample']])
    others = [r for r in res[1:] if r['sample']['item'] != top['sample']['item']]
    text = f'{top["source"]}에 있는 육성형으로 띄웠어요.\n- {top["readable"]}'
    if others:
        o = others[0]
        text += f'\n\n다른 선택지로 {DEX.ko("item", o["sample"]["item"])}형도 있어요 ({o["source"]}).\n- {o["readable"]}'
    return c.answer(text)


async def sample_item(rng, tools, fmt):
    key = DEX.pick_pokemon(rng, fmt)
    name = DEX.ko('pokemon', key)
    pre = matching(await tools.run('search_samples', {'pokemon': name}), key)
    items = list(dict.fromkeys(r['sample']['item'] for r in pre if r['sample']['item']))
    if len(items) < 2:
        raise Skip('도구가 한 가지')
    item = rng.choice(items[1:])
    item_ko = DEX.ko('item', item)
    q = rng.choice([f'{name} {item_ko} 들린 샘플 있어?', f'{item_ko} {name} 육성형 짜줘', f'{name}한테 {item_ko} 주면 어떻게 키워?'])
    c = Conv(tools, fmt, [], q)
    res = [r for r in matching(await c.call('search_samples', pokemon=name), key) if r['sample']['item'] == item]
    if not res:
        raise Skip('결과가 바뀜')
    await proposed(c, [res[0]['sample']])
    return c.answer(f'{item_ko}를 든 {res[0]["source"]} 육성형이에요.\n- {res[0]["readable"]}')


def parse_sp(text: str) -> dict:
    return {s: int(v) for s, v in re.findall(r'(hp|atk|def|spa|spd|spe)(\d+)', text)}


async def sample_usage(rng, tools, fmt):
    key = DEX.pick_pokemon(rng, fmt)
    name = DEX.ko('pokemon', key)
    q = rng.choice([f'{name} 사용률 기준으로 육성형 직접 짜줘', f'{name} 제일 많이 쓰는 조합으로 만들어줘',
                    f'요즘 {name} 많이 쓰는 기술이랑 도구로 샘플 만들어줘'])
    c = Conv(tools, fmt, [], q)
    hits = await c.call('search_pokemon', query=name)
    if not any(h.get('id') == key for h in hits):
        raise Skip('검색 결과에 없음')
    d = await c.call('get_pokemon', id=key)
    u = d.get('usage')
    if not u or len(u['move']) < 4 or not (u['item'] and u['ability'] and u['nature'] and u['spread']):
        raise Skip('사용률 부족')
    pick = {k: 0 for k in ('item', 'ability', 'nature')}
    moves = [m['id'] for m in u['move'][:4]]
    spare = [m['id'] for m in u['move'][4:]]
    s = {'pokemon': key, 'item': u['item'][0]['id'], 'ability': u['ability'][0]['id'], 'nature': u['nature'][0]['id'],
         'sp': parse_sp(u['spread'][0]['sp']), 'moves': moves}
    fixes = []
    for _ in range(3):
        v = await c.call('validate_set', **s)
        errs = [x['message'] for x in v['checks'] if x['level'] == 'error']
        if not errs:
            break
        changed = False
        for e in errs:
            if e.startswith('배울 수 없는 기술') and spare:
                bad = [m for m in s['moves'] if DEX.ko('move', m) in e]
                for m in bad:
                    if spare:
                        new = spare.pop(0)
                        s['moves'] = [new if x == m else x for x in s['moves']]
                        fixes.append(f'{DEX.ko("move", m)} 대신 {DEX.ko("move", new)}')
                        changed = True
            elif '특성' in e and pick['ability'] + 1 < len(u['ability']):
                pick['ability'] += 1
                s['ability'] = u['ability'][pick['ability']]['id']
                fixes.append(f'특성을 {DEX.ko("ability", s["ability"])}로')
                changed = True
            elif ('도구' in e or '메가스톤' in e) and pick['item'] + 1 < len(u['item']):
                pick['item'] += 1
                s['item'] = u['item'][pick['item']]['id']
                fixes.append(f'도구를 {DEX.ko("item", s["item"])}로')
                changed = True
        if not changed:
            raise Skip('고칠 수 없음')
    else:
        raise Skip('검사 통과 못 함')
    await proposed(c, [s])
    mv = u['move']
    pct = {m['id']: m['pct'] for m in mv}
    it = next(x for x in u['item'] if x['id'] == s['item'])
    ab = next(x for x in u['ability'] if x['id'] == s['ability'])
    na = u['nature'][0]
    rank = f' ({FMT_KO[fmt]} 픽률 {u["rank"]}위)' if u['rank'] else ''
    text = (f'{FMT_KO[fmt]} 사용률 1위 조합으로 짰어요{rank}.\n'
            f'- 도구: {it["name_ko"]} ({it["pct"]}%)\n- 특성: {ab["name_ko"]} ({ab["pct"]}%)\n'
            f'- 성격: {na["name_ko"]} ({na["pct"]}%) / SP {u["spread"][0]["sp"]} ({u["spread"][0]["pct"]}%)\n'
            f'- 기술: ' + ', '.join(f'{DEX.ko("move", m)} {pct[m]}%' for m in s['moves']))
    if fixes:
        text += '\n\n검사에서 걸린 부분은 고쳤어요: ' + ', '.join(fixes) + '.'
    return c.answer(text)


async def fill(rng, tools, fmt):
    team = rng.choice(DEX.teams[fmt])
    k = rng.choices([1, 2], [3, 2])[0]
    hidden_idx = sorted(rng.sample(range(6), k))
    keep = [s for i, s in enumerate(team) if i not in hidden_idx]
    hidden = [team[i] for i in hidden_idx]
    q = rng.choice([f'나머지 {k}마리 채워줘', f'{k}자리 비었는데 뭐 넣으면 좋을까?', '파티 완성해줘',
                    f'이 파티에 {k}마리 더 추천해줘', '남은 자리 채워서 파티 만들어줘'])
    c = Conv(tools, fmt, keep, q)
    before = await c.call('analyze_party', members=[{'pokemon': s['pokemon'], 'item': s['item']} for s in keep])
    used_items = {s['item'] for s in keep if s['item']}
    has_mega = any(DEX.is_mega_stone(s['item']) for s in keep)
    added = []
    for h in hidden:
        res = matching(await c.call('search_samples', pokemon=DEX.ko('pokemon', h['pokemon'])), h['pokemon'],
                       used_items, has_mega)
        if not res:
            raise Skip('맞는 샘플 없음')
        r = next((x for x in res if x['sample']['item'] == h['item']), res[0])     # 실제 파티와 같은 도구 우선
        added.append(r)
        used_items.add(r['sample']['item'])
        has_mega = has_mega or DEX.is_mega_stone(r['sample']['item'])
    full = keep + [r['sample'] for r in added]
    after = await c.call('analyze_party', members=[{'pokemon': s['pokemon'], 'item': s['item']} for s in full])
    await proposed(c, full)
    who = '·'.join(DEX.ko('pokemon', r['sample']['pokemon']) for r in added)
    text = f'{who}{"을" if has_batchim(who) else "를"} 넣은 파티를 띄웠어요.\n' + '\n'.join(f'- {r["readable"]}' for r in added)
    better = weak_line(before, after)
    if better:
        text += '\n\n상성: ' + ', '.join(better) + '로 줄어요.'
    left = worst(after)
    if left:
        text += f'\n아직 {", ".join(left)}가 약점이라 선출할 때 신경 써 주세요.'
    return c.answer(text)


async def fix_weak(rng, tools, fmt):
    team = rng.choice(DEX.teams[fmt])
    wc = DEX.weak_counts(team)
    bad = [t for t in TYPES if wc[t] >= 3]
    if not bad:
        raise Skip('약점 3마리 이상 없음')
    t = max(bad, key=lambda x: wc[x])
    t_ko = TYPE_KO[t]
    q = rng.choice(['이 파티 약점 보완해줘', f'{t_ko} 약점이 너무 많은 것 같은데 바꿀 만한 거 있어?',
                    '한 마리만 바꿔서 약점 줄이고 싶어', '파티 상성 봐주고 고쳐줘'])
    c = Conv(tools, fmt, team, q)
    before = await c.call('analyze_party', members=[{'pokemon': s['pokemon'], 'item': s['item']} for s in team])
    # 바꿀 멤버: 그 타입에 약한 멤버 중 메가가 아닌 쪽. 넣을 포켓몬: 그 타입을 받고 다른 약점을 3마리 이상 만들지 않는 픽률 상위
    outs = [i for i, s in enumerate(team) if defense_profile(DEX.types(s))[t] > 1 and not DEX.is_mega_stone(s['item'])]
    if not outs:
        raise Skip('바꿀 멤버 없음')
    i = rng.choice(outs)
    rest = team[:i] + team[i + 1:]
    species = {s['pokemon'] for s in team}
    cands = sorted((k for k in DEX.with_samples[fmt] if k not in species), key=lambda k: DEX.rank[fmt].get(k, 999))[:60]
    rng.shuffle(cands)
    for k in cands:
        pk = DEX.n['pokemon'][k]
        if defense_profile([x for x in (pk['type1'], pk['type2']) if x])[t] >= 1:
            continue
        trial = DEX.weak_counts(rest + [{'pokemon': k, 'item': ''}])
        if trial[t] < wc[t] and max(trial.values()) <= max(wc.values()):
            break
    else:
        raise Skip('후보 없음')
    used_items = {s['item'] for s in rest if s['item']}
    has_mega = any(DEX.is_mega_stone(s['item']) for s in rest)
    res = matching(await c.call('search_samples', pokemon=DEX.ko('pokemon', k)), k, used_items, has_mega)
    if not res:
        raise Skip('맞는 샘플 없음')
    new = rest[:i] + [res[0]['sample']] + rest[i:]
    after = await c.call('analyze_party', members=[{'pokemon': s['pokemon'], 'item': s['item']} for s in new])
    better = weak_line(before, after)
    if not any(x.startswith(t_ko + ' ') for x in better):
        raise Skip('약점이 안 줄었음')
    await proposed(c, new)
    out_ko, in_ko = DEX.ko('pokemon', team[i]['pokemon']), DEX.ko('pokemon', k)
    text = (f'{out_ko} 대신 {in_ko}{"을" if has_batchim(in_ko) else "를"} 넣는 걸 추천해요. 나머지는 그대로예요.\n'
            f'- 상성: {", ".join(better)}\n- {res[0]["readable"]}')
    left = worst(after)
    if left:
        text += f'\n\n남은 약점: {", ".join(left)}'
    return c.answer(text)


def has_batchim(word: str) -> bool:
    ch = word[-1]
    return '가' <= ch <= '힣' and (ord(ch) - 0xAC00) % 28 != 0


SCENARIOS = {'sample_top': sample_top, 'sample_item': sample_item, 'sample_usage': sample_usage,
             'fill': fill, 'fix_weak': fix_weak}


# ---------- 실행 ----------

async def generate(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    rows, made, skipped = [], Counter(), Counter()
    kinds, weights = list(KINDS), list(KINDS.values())
    async with back_client() as client:
        tries = 0
        while len(rows) < n and tries < n * 10:
            tries += 1
            kind = rng.choices(kinds, weights)[0]
            fmt = rng.choice(list(FMT_KO))
            try:
                msgs = await SCENARIOS[kind](rng, Tools(client, fmt), fmt)
            except Skip as e:
                skipped[f'{kind}: {e}'] += 1
                continue
            if not numbers_grounded(msgs):
                skipped[f'{kind}: 근거 없는 숫자'] += 1
                continue
            rows.append({'kind': kind, 'format': fmt, 'messages': msgs})
            made[kind] += 1
    print('만든 대화:', dict(made), f'(총 {len(rows)})')
    print('건너뜀:', dict(skipped.most_common()))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--n', type=int, default=300, help='만들 대화 수')
    ap.add_argument('--eval', type=float, default=0.1, help='평가용으로 떼는 비율')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--out', default=str(LLM / 'training'))
    args = ap.parse_args()

    global DEX
    DEX = Dex()
    print(f'레귤레이션 {DEX.rs.id} | 파티 싱글 {len(DEX.teams["singles"])} 더블 {len(DEX.teams["doubles"])}')
    rows = asyncio.run(generate(args.n, args.seed))
    random.Random(args.seed).shuffle(rows)
    k = int(len(rows) * args.eval)
    out = Path(args.out)
    for name, part in (('eval.jsonl', rows[:k]), ('train.jsonl', rows[k:])):
        with open(out / name, 'w', encoding='utf-8') as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f'{out / name}: {len(part)}개')


DEX: Dex

if __name__ == '__main__':
    main()
