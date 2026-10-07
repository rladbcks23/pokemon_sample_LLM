"""v1 샘플 유형 + v2 파티 대화를 현재 도구로 재생성하는 검수용 실행기.

기존 데이터에 덧붙이지 않고 새 폴더에 대화 20개만 만든다. 학습/평가 내보내기나
모델 학습은 하지 않는다. 실행: python training/review_combined.py --tokenizer-dir DIR
tokenizer-dir은 Qwen3.5-4B의 tokenizer.json과 chat_template.jinja가 있는 폴더.
추가 의존성: tokenizers, jinja2, jsonschema (GPU·모델 가중치·유료 API 불필요).
"""
import argparse
import asyncio
import hashlib
import itertools
import json
import random
from collections import Counter
from pathlib import Path


def sample_key(sample):
    """SP 0 생략·기술 순서와 무관한 육성형 원본 식별."""
    return (sample['pokemon'], sample.get('item', ''), sample.get('ability', ''),
            sample.get('nature', ''), tuple((sample.get('sp') or {}).get(k, 0)
            for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')),
            tuple(sorted(sample.get('moves') or [])))


def schema_errors(records, definitions):
    from jsonschema import Draft202012Validator
    validators = {t['name']: Draft202012Validator(t['input_schema']) for t in definitions}
    errors = []
    for turn, msgs in enumerate(records, 1):
        for m in msgs:
            for c in m.get('tool_calls', []):
                f = c['function']
                if f['name'] not in validators:
                    errors.append(f"turn {turn}: 없는 도구 {f['name']}")
                else:
                    errors += [f"turn {turn}: {f['name']}: {e.message}"
                               for e in validators[f['name']].iter_errors(f['arguments'])]
    return errors


def length_counter(directory, system, definitions):
    """HF의 텍스트 chat template 규칙으로 길이만 측정. 모델을 다운로드하지 않음."""
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    from tokenizers import Tokenizer
    directory = Path(directory)
    tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True,
                                       extensions=['jinja2.ext.loopcontrols'])
    env.filters['tojson'] = lambda value, **kw: json.dumps(value, ensure_ascii=False, **kw)
    def fail(message):
        raise ValueError(message)
    env.globals['raise_exception'] = fail
    template_file = directory / 'chat_template.jinja'
    template = env.from_string(template_file.read_text(encoding='utf-8'))
    tools = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                                             'parameters': t['input_schema']}} for t in definitions]
    def count(msgs):
        text = template.render(messages=[{'role': 'system', 'content': system}] + msgs,
                               tools=tools, add_generation_prompt=False, enable_thinking=False)
        return len(tokenizer.encode(text, add_special_tokens=False).ids)
    return count, {'template_sha256': hashlib.sha256(template_file.read_bytes()).hexdigest(),
                   'tokenizer_dir': str(directory.resolve()),
                   'method': 'cached Qwen template + tokenizers; Colabでも再確認する'}


async def sample_dialogue(g, tools, fmt, key, kind):
    name = g.DEX.ko('pokemon', key)
    d = g.Dialogue(tools, fmt, kind, ['정확한 도구 인자', '샘플 제작', '조건 준수'])
    # 선택은 실제 검색 결과와 합법성으로만. 사용된 DB 원본도 별도로 기록한다.
    pre = await tools.run('search_samples', {'pokemon': name})
    options = []
    for r in pre.get('samples', []) if isinstance(pre, dict) else []:
        s = r['sample']
        if s['pokemon'] != key or g.DEX.odd(s):
            continue
        shapes = pre.get('shapes') or {}
        role = (r.get('roles') or [''])[0].split(' (')[0]
        if shapes.get('total') and shapes.get(role, 0) / shapes['total'] < .1:
            continue
        if (await tools.run('validate_set', s)).get('valid'):
            options.append(r)
    if not options:
        raise g.Skip(f'{name}: 합법·흔한 형태 샘플 없음')

    if kind == 'sample_usage':
        d.ask(f'{name} {g.FORMAT_KO[fmt]} 사용률을 참고해서 육성형 짜줘', [])
        await d.call('search_pokemon', query=name)
        detail = await d.call('get_pokemon', id=key)
        usage = detail.get('usage')
        if not usage or len(usage.get('move', [])) < 4:
            raise g.Skip('사용률 부족')
        def spread(text):
            import re
            return {k: int(v) for k, v in re.findall(r'(hp|atk|def|spa|spd|spe)(\d+)', text)}
        selected = None
        # 각 항목의 주변 사용률은 공동 조합 사용률이 아님. 합법 후보만 고른다.
        for item, ability, nature, sp in itertools.product(
                usage['item'][:2], usage['ability'][:2], usage['nature'][:2], usage['spread'][:2]):
            s = {'pokemon': key, 'item': item['id'], 'ability': ability['id'], 'nature': nature['id'],
                 'sp': spread(sp['sp']), 'moves': [m['id'] for m in usage['move'][:4]]}
            if not g.DEX.odd(s) and (await tools.run('validate_set', s)).get('valid'):
                selected = s, item, ability, nature
                break
        if selected is None:
            raise g.Skip('상위 사용률 조합 중 합법 후보 없음')
        s, item, ability, nature = selected
        await d.call('validate_set', **s)
        await d.call('propose_party', members=[s])
        d.answer(f"{g.short(s)} 추천 (화면에 띄움).\n"
                 f"도구 {item['pct']}%, 특성 {ability['pct']}%, 성격 {nature['pct']}%인 후보로 구성하고 규칙 검사를 통과했어요.\n"
                 '각 항목 사용률을 참고한 조합이에요. 이 조합 전체의 사용률이나 승률은 확인할 수 없어요.')
        d.meta['sources'] = {'usage_pokemon': key, 'format': fmt}
    else:
        chosen = options[0]
        if kind == 'sample_item':
            chosen = next((r for r in options if r['sample']['item'] != options[0]['sample']['item']), None)
            if chosen is None:
                raise g.Skip('서로 다른 도구 샘플 없음')
            item = chosen['sample']['item']
            d.meta['conditions']['requested_item'] = item
            d.ask(f"{name} {g.DEX.ko('item', item)}형 {g.FORMAT_KO[fmt]} 샘플 짜줘", [])
        else:
            d.ask(f'{g.FORMAT_KO[fmt]} {name} 샘플 짜줘', [])
        await d.call('search_samples', pokemon=name)
        await d.call('propose_party', members=[chosen['sample']])
        role = ' · '.join(chosen.get('roles', []))
        d.answer(f"{g.short(chosen['sample'])} 추천 (화면에 띄움).\n"
                 f"{chosen['source']} 공개 샘플이고, SP·기술 기준 역할은 {role or '확인 필요'}이에요.\n"
                 '공개 샘플이라는 근거는 있지만, 다른 육성형보다 강하다고 단정할 수는 없어요.')
        ids = [s.pk for s in g.DEX.sets.get((fmt, key), [])
               if sample_key(g.DEX.sample(s)) == sample_key(chosen['sample'])]
        d.meta['sources'] = {'sample_ids': ids,
                             'build_sha256': hashlib.sha256(repr(sample_key(chosen['sample'])).encode()).hexdigest()}
    # 같은 포켓몬의 샘플·사용률 변형을 함께 묶음. 확대 때는 팀 원본과의 연결도 확인해야 함.
    d.meta['group'] = f'pokemon:{key}'
    return d


async def generate(g, seed):
    rng = random.Random(seed)
    dialogues = []
    async with g.back_client() as client:
        for kind in ('sample_top', 'sample_item', 'sample_usage'):
            made = 0
            # 실제 실패 질문은 반드시 검수에 포함하되, 데이터 부족이면 다른 실제 후보로.
            pool = [('doubles', 'garchomp'), ('singles', 'garchomp'), ('doubles', 'rillaboom')]
            keys = sorted(g.DEX.sets)
            rng.shuffle(keys)
            pool += keys
            for fmt, key in pool:
                if made >= 3:
                    break
                try:
                    d = await sample_dialogue(g, g.Tools(client, fmt), fmt, key, kind)
                    if not g.auto_checks(d)['ok']:
                        continue
                    dialogues.append(d)
                    made += 1
                    print(f'샘플 {kind} {fmt} {key}', flush=True)
                except g.Skip as e:
                    print(f'건너뜀: {e}', flush=True)
            if made != 3:
                raise RuntimeError(f'{kind}: 검수용 3개를 만들지 못함')
    plan = {'fill_one': 3, 'core_team': 3, 'fill_moves': 1, 'fill_rest': 2, 'clarify': 1, 'not_found': 1}
    dialogues += await g.build(plan, seed, user_questions=False)
    if len(dialogues) != 20:
        raise RuntimeError(f'정확히 20개 필요: 현재 {len(dialogues)}개')
    return dialogues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent / 'outputs/review_combined_20261007')
    parser.add_argument('--tokenizer-dir', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('출력 폴더가 이미 있음. 기존 검수물을 보존하려면 다른 --out 사용')
    import make_data as g
    from agent.prompt import SYSTEM
    from agent.tools import TOOLS
    g.DEX = g.Dex()
    count, tokenizer_meta = length_counter(args.tokenizer_dir, SYSTEM, TOOLS)
    version = {**g.data_version(), 'tokenizer': tokenizer_meta,
               'code_sha256': {p: hashlib.sha256((g.ROOT / p).read_bytes()).hexdigest()
                               for p in ('llm/agent/tools.py', 'llm/agent/prompt.py',
                                         'llm/training/make_data.py', 'llm/training/review_combined.py')}}
    ds = asyncio.run(generate(g, args.seed))
    rows = [g.to_row(i, d, version) for i, d in enumerate(ds, 1)]
    lengths = []
    for row in rows:
        row['id'] = row['id'].replace('v2-', 'combined-review-')
        row['auto_checks']['schema_errors'] = schema_errors(row['records'], TOOLS)
        row['auto_checks']['requested_item_kept'] = all(
            m['item'] == row['conditions']['requested_item']
            for t in row['turns'] for m in t['proposed'] or []
        ) if row['conditions'].get('requested_item') else True
        row['auto_checks']['ok'] &= not row['auto_checks']['schema_errors'] and row['auto_checks']['requested_item_kept']
        for turn, rec in enumerate(row['records'], 1):
            n = count(rec)
            lengths.append({'id': row['id'], 'turn': turn, 'kind': row['scenario'], 'tokens': n,
                            'fits_4096': n <= 4096, 'fits_8192': n <= 8192})
    args.out.mkdir(parents=True)
    (args.out / 'review.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    (args.out / 'review.md').write_text(g.to_markdown(rows), encoding='utf-8')
    (args.out / 'review_tools.md').write_text(g.to_markdown(rows, tools=True), encoding='utf-8')
    report = {'status': 'review_only_not_training_data', 'dialogues': len(rows),
              'auto_passed': sum(r['auto_checks']['ok'] for r in rows), 'seed': args.seed,
              'lengths': lengths, 'version': version}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 샘플·파티 검수 데이터', '',
             f"대화 {len(rows)}개 / 자동 검사 통과 {report['auto_passed']}개 / 모든 대화는 사람 검수 대기.",
             '학습/평가 파일을 만들거나 기존 데이터에 합치지 않았습니다.', '',
             '| 유형 | 턴 수 | 4096 이하 | 8192 이하 | 최대 토큰 |', '|---|---:|---:|---:|---:|']
    for kind in sorted({r['kind'] for r in lengths}):
        items = [r for r in lengths if r['kind'] == kind]
        lines.append(f"| {kind} | {len(items)} | {sum(r['fits_4096'] for r in items)} | "
                     f"{sum(r['fits_8192'] for r in items)} | {max(r['tokens'] for r in items)} |")
    lines += ['', '길이는 전체 도구 정의·시스템 프롬프트·이전 턴을 포함하며 자르지 않았습니다.',
              '4096을 넘는 파티 사례는 그대로 학습에서 빼지 말고 문맥 구성 개선이 필요합니다.',
              '평가 분할은 아직 없습니다. 확대 시 샘플·팀의 공통 육성형 원본 연결까지 묶어서 분리해야 합니다.']
    (args.out / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines), flush=True)
    print(args.out / 'review.md')


if __name__ == '__main__':
    main()
