"""현재/v1 ZIP의 DB를 확인하고 새 학습 묶음을 별도 경로에 만든다. 학습하지 않음."""
import argparse
import asyncio
import copy
import hashlib
import json
import random
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

if __package__:
    from .compact_context import action_records, system_prompt
    from .review_combined import length_counter, sample_dialogue, sample_key, schema_errors
else:
    from compact_context import action_records, system_prompt
    from review_combined import length_counter, sample_dialogue, sample_key, schema_errors

ROOT = Path(__file__).resolve().parents[2]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_archive(path, prefix):
    with zipfile.ZipFile(path) as z:
        rows = [json.loads(line) for split in ('train', 'eval')
                for line in z.read(prefix + split + '.jsonl').decode('utf-8').splitlines() if line]
        if digest(z.read('data/pokemon.db')) != digest((ROOT / 'data/pokemon.db').read_bytes()):
            raise ValueError(f'{path}: DB 버전이 현재 DB와 다름. 자동 혼합 중단')
    return rows


def screen_samples(messages):
    import re
    current = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
    return [json.loads(m.group(1)) for line in current.splitlines()
            if (m := re.match(r'^\d+\. (\{.*\})$', line))]


def fixed_kept(sample, party):
    """기존 육성은 유지하되, 비어 있는 기술 칸은 요청대로 채울 수 있다."""
    return any(sample_key({**sample, 'moves': []}) == sample_key({**p, 'moves': []})
               and set(sample.get('moves', [])) - {''} <= set(p.get('moves', [])) for p in party)


def source_keys(row):
    """조회한 원본 팀·실제 추천한 육성형·그룹 변형을 함께 묶는다."""
    keys = {row['group']}
    for m in row['messages']:
        for c in m.get('tool_calls', []):
            f = c['function']
            if f['name'] == 'get_team':
                keys.add('team:' + str(f['arguments']['id']))
            if f['name'] == 'propose_party':
                for s in f['arguments']['members']:
                    keys.add('build:' + digest(repr(sample_key(s)).encode()))
    return keys


def annotate_rows(rows):
    """조건과 원본을 메시지 밖에도 기록. 후속 요청의 해석을 검수 완료로 간주하지 않는다."""
    first_screens = {}
    for r in rows:
        if r.get('turn', 1) == 1:
            first_screens[r['id'].rsplit('-t', 1)[0]] = screen_samples(r['messages'])
    for r in rows:
        user = next(m['content'] for m in reversed(r['messages']) if m['role'] == 'user')
        r['conditions'] = {**r.get('conditions', {}), 'format': r['format'],
                           'initial_screen_members': first_screens.get(r['id'].rsplit('-t', 1)[0], []),
                           'current_screen_members': screen_samples(r['messages']),
                           'user_request': user.split('\n\n')[-1],
                           'duplicate_pokemon_allowed': False, 'duplicate_items_allowed': False,
                           'followup_interpretation_review': 'pending' if r.get('turn', 1) > 1 else 'not_followup'}
        r['source_ids'] = {**r.get('source_ids', {}), 'original_group': r['group'],
                           'source_keys': sorted(source_keys(r))}
        r['version_ref'] = 'report.json:version'
    return rows


def split_sources(rows, seed, ratio=.12):
    """원본 연결 요소 단위 분리. 큰 연결 요소를 쪼개 평가 누수를 만들지 않는다."""
    parents, owners = list(range(len(rows))), {}
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, r in enumerate(rows):
        for key in source_keys(r):
            if key in owners:
                parents[root(i)] = root(owners[key])
            else:
                owners[key] = i
    components = defaultdict(list)
    for i in range(len(rows)):
        components[root(i)].append(i)
    groups = list(components.values())
    random.Random(seed).shuffle(groups)
    target, eval_ids = round(len(rows) * ratio), set()
    # 작은 독립 원본이 있는 유형은 평가에서 빠지지 않도록 먼저 한 묶음 확보한다.
    kinds = sorted({r['kind'] for r in rows})
    for kind in kinds:
        if any(rows[i]['kind'] == kind for i in eval_ids):
            continue
        eligible = [ids for ids in groups if len(ids) <= target
                    and any(rows[i]['kind'] == kind for i in ids)
                    and any(rows[i]['kind'] == kind for i in range(len(rows)) if i not in ids)]
        if eligible:
            eval_ids.update(min(eligible, key=len))
    # 거대한 공유 원본 묶음은 학습에 둔다. 작은 묶음을 골라 목표 평가 비율에 접근한다.
    for ids in groups:
        if not eval_ids.intersection(ids) and len(ids) <= target and abs(target - len(eval_ids) - len(ids)) < abs(target - len(eval_ids)):
            eval_ids.update(ids)
    if not eval_ids:
        raise ValueError('독립 평가 원본을 확보하지 못함')
    split = {'train': [], 'eval': []}
    for ids in groups:
        group_id = 'origin-' + digest('\n'.join(sorted({k for i in ids for k in source_keys(rows[i])})).encode())[:16]
        for i in ids:
            r = {**rows[i], 'origin_component': group_id}
            split['eval' if i in eval_ids else 'train'].append(r)
    a = {k for r in split['train'] for k in source_keys(r)}
    b = {k for r in split['eval'] for k in source_keys(r)}
    assert not a & b, '원본 분리 실패'
    return split, {'components': len(groups), 'largest_component_turns': max(map(len, groups)),
                   'shared_source_keys': len(a & b), 'target_eval_ratio': ratio,
                   'eval_missing_kinds': sorted(set(kinds) - {r['kind'] for r in split['eval']})}


async def reconstruct(current, old, g, extras=True):
    from agent.tools import TOOLS
    rows, rejected = [], []
    async with g.back_client() as client:
        for i, row in enumerate(current):
            r = copy.deepcopy(row)
            r['source_archive'] = 'colab_bundle (2).zip'
            r['review_status'] = 'pending_human_review'
            errors = schema_errors([r['messages']], TOOLS)
            tools, proposed = g.Tools(client, r['format']), []
            changed = 0
            try:
                if errors:
                    raise ValueError('; '.join(errors))
                pending = []
                for m in r['messages']:
                    if m.get('tool_calls'):
                        for c in m['tool_calls']:
                            f = c['function']
                            pending.append(await tools.run(f['name'], f['arguments']))
                            if f['name'] == 'propose_party':
                                proposed.append(f['arguments']['members'])
                    elif m['role'] == 'tool':
                        result = pending.pop(0)
                        fresh = result if isinstance(result, str) else g.json.dumps(result, ensure_ascii=False, separators=(',', ':'))
                        changed += fresh != m['content']
                        m['content'] = fresh
                if pending:
                    raise ValueError('도구 결과 누락')
                # 첫 턴의 화면 멤버는 고정. 후속 턴에서는 변경 요청이 있을 수 있다.
                fixed = screen_samples(r['messages']) if r.get('turn', 1) == 1 else []
                for party in proposed:
                    if any(not fixed_kept(s, party) for s in fixed):
                        raise ValueError('첫 턴 고정 육성형 변경')
                r['checks'] = {'schema': True, 'live_tool_replay': True,
                               'proposal_legal_and_unique': True, 'first_turn_fixed_kept': True,
                               'refreshed_results': changed}
                rows.append(r)
            except Exception as e:
                rejected.append({'id': r['id'], 'kind': r['kind'], 'reason': str(e)})
            if (i + 1) % 50 == 0:
                print(f'현재 데이터 재검증 {i + 1}/{len(current)}', flush=True)
        if not extras:
            return rows, rejected
        seeds = set()
        for row in old:
            if row['kind'] not in ('sample_top', 'sample_item', 'sample_usage'):
                continue
            for m in row['messages']:
                for c in m.get('tool_calls', []):
                    f = c['function']
                    if f['name'] == 'propose_party' and f['arguments'].get('members'):
                        seeds.add((row['kind'], row['format'], f['arguments']['members'][0]['pokemon']))
        # 사용자에게 실제로 문제가 났던 요청도 포함한다.
        seeds.update((kind, 'doubles', 'garchomp') for kind in ('sample_top', 'sample_item', 'sample_usage'))
        for i, (kind, fmt, key) in enumerate(sorted(seeds)):
            try:
                d = await sample_dialogue(g, g.Tools(client, fmt), fmt, key, kind)
                checks = g.auto_checks(d)
                if not checks['ok']:
                    raise ValueError(str(checks))
                errors = schema_errors(d.records(), TOOLS)
                if errors:
                    raise ValueError('; '.join(errors))
                rows.append({'id': f'rebuilt-sample-{i:04d}', 'kind': kind, 'format': fmt,
                             'group': f'pokemon:{key}', 'turn': 1, 'messages': d.records()[0],
                             'source_archive': 'colab_bundle_ver1.zip (유형·포켓몬만 재사용)',
                             'source_ids': d.meta['sources'], 'conditions': d.meta['conditions'],
                             'review_status': 'pending_human_review', 'checks': checks})
            except (g.Skip, ValueError) as e:
                rejected.append({'id': f'{kind}:{fmt}:{key}', 'kind': kind, 'reason': str(e)})
            if (i + 1) % 40 == 0:
                print(f'ver1 샘플 유형 재생성 {i + 1}/{len(seeds)}', flush=True)
        # '더블 파티 하나 짜줘'는 실제 팀 목록을 조회해 완성하는 사례도 제공한다.
        for fmt in ('doubles', 'singles'):
            tools = g.Tools(client, fmt)
            listing = await tools.run('search_teams', {})
            made = 0
            for team in listing.get('teams', []) if isinstance(listing, dict) else []:
                if made == 3:
                    break
                try:
                    detail = await tools.run('get_team', {'id': team['id']})
                    party = [m['sample'] for m in detail['members']]
                    if len(party) != 6 or any(g.DEX.odd(s) for s in party):
                        continue
                    d = g.Dialogue(tools, fmt, 'party_request', ['전체 파티 조회'])
                    d.ask(f'{g.FORMAT_KO[fmt]} 파티 하나 짜줘', [])
                    await d.call('search_teams')
                    await d.call('get_team', id=team['id'])
                    check = await d.call('check_party', members=party)
                    await d.call('propose_party', members=party)
                    d.answer(f"{detail['source']}의 '{detail['title']}'를 바탕으로 파티를 띄웠어요.\n"
                             f"구성: {g.roles_text(check['summary'])}.\n"
                             '공개 파티 예시예요. 원하는 핵심 포켓몬이나 컨셉을 알려 주면 수정할게요.')
                    if not g.auto_checks(d)['ok']:
                        continue
                    rows.append({'id': f'rebuilt-party-{fmt}-{made}', 'kind': 'party_request',
                                 'format': fmt, 'group': f"team:{team['id']}", 'turn': 1,
                                 'messages': d.records()[0], 'source_ids': {'team_id': team['id']},
                                 'source_archive': '동일 DB 실제 도구 조회',
                                 'review_status': 'pending_human_review', 'checks': g.auto_checks(d)})
                    made += 1
                except (g.Skip, g.ToolError) as e:
                    rejected.append({'id': f"party:{fmt}:{team['id']}", 'kind': 'party_request', 'reason': str(e)})
    return rows, rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--v1', type=Path, required=True)
    parser.add_argument('--tokenizer-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('기존 출력 보존을 위해 새 --out 경로 필요')
    current = read_archive(args.current, 'llm/training/finetuning_data_ver2/')
    old = read_archive(args.v1, 'llm/training/')
    import make_data as g
    from agent.prompt import SYSTEM
    from agent.tools import TOOLS
    g.DEX = g.Dex()
    rows, rejected = asyncio.run(reconstruct(current, old, g))
    rows = annotate_rows(rows)
    prompt = system_prompt(SYSTEM, TOOLS)
    count, tokenizer_info = length_counter(args.tokenizer_dir, prompt, [])
    # 전체 행동을 생성한 뒤 길이를 확인. 넘는 자료는 숨겨서 버리지 않고 실패시킨다.
    splits, separation = split_sources(rows, args.seed)
    actions = {split: [a for r in rs for a in action_records(r, prompt)] for split, rs in splits.items()}
    lengths = {}
    for split, rs in actions.items():
        for r in rs:
            n = count(r['messages'][1:])
            if n > 4096:
                raise ValueError(f"4096 초과: {r['id']} {n}; 데이터를 제외하지 말고 표현 개선 필요")
            r['tokens'] = n
        lengths[split] = {'max': max(r['tokens'] for r in rs),
                          'mean': round(sum(r['tokens'] for r in rs) / len(rs)), 'over_4096': 0}
    version = {'db_sha256': digest((ROOT / 'data/pokemon.db').read_bytes()),
               'input_archives': {p.name: digest(p.read_bytes()) for p in (args.current, args.v1)},
               'system_sha256': digest(prompt.encode()), 'tokenizer': tokenizer_info,
               'code_sha256': {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in
                               [ROOT / 'llm/training/compact_context.py', Path(__file__),
                                ROOT / 'llm/training/review_combined.py', ROOT / 'llm/agent/tools.py',
                                ROOT / 'llm/training/make_rebuilt_notebook.py']}}
    report = {'status': 'ready_for_colab_validation_not_trained', 'human_review': 'pending',
              'input_current_turns': len(current), 'input_v1_turns': len(old),
              'retained_current_turns': sum(r['source_archive'] == 'colab_bundle (2).zip' for r in rows),
              'output_source_turns': len(rows), 'rejections': rejected, 'split': separation,
              'seed': args.seed, 'version': version, 'lengths': lengths,
              'counts': {s: {'turns': len(splits[s]), 'actions': len(actions[s]),
                             'turn_kinds': dict(Counter(r['kind'] for r in splits[s])),
                             'action_kinds': dict(Counter(r['kind'] for r in actions[s]))} for s in splits}}
    args.out.mkdir(parents=True)
    for split in splits:
        for filename, rs in [(split + '.jsonl', actions[split]), ('source_' + split + '.jsonl', splits[split])]:
            (args.out / filename).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rs), encoding='utf-8')
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.out / 'system.txt').write_text(prompt, encoding='utf-8')
    from make_rebuilt_notebook import create_notebook
    notebook = create_notebook()
    notebook_path = ROOT / 'llm/training/finetune_colab_rebuilt.ipynb'
    notebook_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    lines = ['# 재구성한 Colab 데이터', '',
             f"현재 {len(current)}턴 중 {report['retained_current_turns']}턴 유지. 총 {len(rows)}턴.",
             'ver1의 샘플 조회·아이템 조건·사용률 조합을 현재 도구로 새로 생성했습니다.',
             '한 턴을 여러 assistant 행동으로 분리합니다. 매번 전체 도구 목록·현재 질문·화면·조회 근거를 제공합니다.',
             '중복 육성형은 원문을 한 번 제공하고 참조합니다. 정답 호출은 API의 전체 필드를 그대로 씁니다.',
             '마지막 assistant 행동만 학습합니다. 도구 결과나 이전 assistant 답변은 정답으로 반복 학습하지 않습니다.', '',
             '| 분할 | 원래 턴 | 학습 행동 | 최대 토큰 |', '|---|---:|---:|---:|']
    for s in splits:
        lines.append(f"| {s} | {len(splits[s])} | {len(actions[s])} | {lengths[s]['max']} |")
    lines += ['', f"원본 연결 묶음 {separation['components']}개. 학습/평가 공통 원본 0개.",
              '공유 샘플이 많은 큰 묶음은 학습에 두었으므로 평가 종류별 개수가 균일하지 않을 수 있습니다.',
              'report.json에 제외 사유·종류별 수·도구/DB/입력 버전 기록. 자연어 설명의 정확성은 사람 검수 대기입니다.',
              '원래 ZIP·데이터·모델은 덮어쓰지 않았습니다. 실제 T4 학습/OOM/추천 성능은 아직 검증하지 않았습니다.', '',
              '## 사용', '', '1. Colab 런타임을 다시 시작합니다.',
              '2. colab_bundle_rebuilt_20261007.zip을 MyDrive/pokemon_coach/ 또는 Colab 파일 탭에 업로드합니다.',
              '3. finetune_colab_rebuilt.ipynb를 열고 순서대로 실행합니다.',
              '4. 처음에는 설정의 SMOKE_TEST=True로 2스텝만 확인합니다.',
              '5. 성공하면 런타임을 다시 시작하고 SMOKE_TEST=False로 바꾼 뒤 전체를 다시 실행합니다.',
              '6. 마지막 채팅에서 “더블 파티 하나 짜줘”, “더블 한카리아스 샘플 짜줘” 등을 비교합니다.', '',
              '이 데이터는 재구성판 전용 입력 표현을 씁니다. 기존 노트북과 섞지 마세요. 서버에 붙일 때도 compact_context를 적용해야 합니다.']
    (args.out / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    output_zip = ROOT / 'llm/training/colab_bundle_rebuilt_20261007.zip'
    if output_zip.exists():
        raise ValueError('ZIP 출력이 이미 있음. 기존 결과를 먼저 다른 이름으로 보존할 것')
    data_prefix = 'llm/training/finetuning_data_ver2/'
    # 현재 사용 중인 묶음의 back/agent/DB를 기본으로 삼고 별도 표현·데이터·노트북만 추가한다.
    with zipfile.ZipFile(args.current) as source, zipfile.ZipFile(output_zip, 'x', zipfile.ZIP_DEFLATED) as dest:
        for name in source.namelist():
            if not name.endswith('/') and not name.startswith(data_prefix):
                dest.writestr(name, source.read(name))
        for file in args.out.iterdir():
            if file.is_file():
                dest.write(file, data_prefix + file.name)
        dest.write(ROOT / 'llm/training/compact_context.py', 'llm/training/compact_context.py')
        dest.write(notebook_path, 'llm/training/finetune_colab_rebuilt.ipynb')
    with zipfile.ZipFile(output_zip) as z:
        assert z.testzip() is None
        assert digest(z.read('data/pokemon.db')) == version['db_sha256']
    print(json.dumps({k: report[k] for k in ('retained_current_turns', 'output_source_turns', 'counts', 'lengths', 'split')}, ensure_ascii=False, indent=2))
    print(output_zip, flush=True)


if __name__ == '__main__':
    main()
