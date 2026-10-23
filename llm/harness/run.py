"""파티·샘플 설명 하네스: 작성 → 자동 검사 → 심사 → 고쳐 쓰기 (DESCRIPTION_RUBRIC.md v3).

작성·심사는 구독 모델 CLI로 부른다 (기본: 작성 Claude, 심사 GPT). 고쳐 쓰기 횟수 제한은 없다.
통과한 설명은 data/descriptions/<kind>.jsonl에 쌓이고, 근거 묶음이 그대로면 다음 실행에서 건너뛴다.

    cd llm
    ..\\.venv\\Scripts\\python -m harness.run --kind sample --format singles --limit 5
    ..\\.venv\\Scripts\\python -m harness.run --kind party --format doubles --writer codex --judge claude
    → 실시간 보기: http://localhost:8002
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from harness import rubric
from harness.live import Live
from harness.llm_cli import CliError, ask, parse_json
from harness.rubric import grounding_text, packet_hash

LLM = Path(__file__).resolve().parents[1]

OUT = LLM.parent / 'data/descriptions'
LOGS = LLM / 'harness/logs'
UNKNOWN = re.compile(r'모르겠|알 수 없|못 찾았|알기 어려')
CHOICES = 6                     # 샘플: 도구·SP·기술 4개 / 파티: 멤버 6마리. 절반 넘게 "모름"이면 사람 검수
STALL = 3                       # 같은 감점(규칙 묶음)이 이만큼 연속이면 맴도는 것이니 멈추고 사람 검수 (구독 사용량 보호)
REASON_RULES = {'J1-a', 'J1-d', 'J3-b', 'J3-c', 'S1-c'}     # 반복되면 "모르겠다"로 빠져나갈 수 있는 규칙 (이유를 대는 것)

JUDGE_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['deductions', 'na'],
    'properties': {
        'deductions': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['rule', 'quote', 'fix'],
            'properties': {'rule': {'type': 'string'}, 'quote': {'type': 'string'}, 'fix': {'type': 'string'}}}},
        'na': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['item', 'reason'],
            'properties': {'item': {'type': 'string'}, 'reason': {'type': 'string'}}}},
    },
}

WRITER_SYSTEM = """너는 포켓몬 챔피언스(Reg M-C) 파티 빌더 앱의 {what} 설명을 쓴다. 사용자는 이 설명을 보고 {what}을 고른다.

규칙
- 사실은 [근거 묶음]에 있는 것만 쓴다. 외운 지식으로 숫자·사용률·상성·대미지를 채우지 않는다
- 숫자는 근거 묶음에 있는 숫자만 (승률·대미지%·확정타 금지)
- 포켓몬·기술·도구·특성 이름은 근거 묶음에 있는 한글 이름 그대로
- 역할은 근거 묶음의 roles(SP 분배·기술 배치로 판정)를 따른다. 종족값만으로 역할을 말하지 않는다
- {fmt_rule}
- 출처를 말한다면 근거 묶음의 source 그대로 (리플레이는 근거가 아님)
- "최강, 무조건, 필수, 완벽, 절대, 승률" 같은 단정·과장 금지
- 말투: 짧은 "~요" 체. 마크다운·글머리표·이모지 없이 문장만
- 길이: {length}
- 구성: {structure}
- 기술·도구 선택 이유는 근거 묶음에서 이 순서로 찾는다
  ① usage_pct: 이 포켓몬에게 흔히 쓰는 기술·도구인지 (10위 밖이면 드문 선택)
  ② desc: 부가 효과 (스피드 랭크 다운, 상태이상 확률, 선공 등)
  ③ super_effective_on과 자신의 weak_to: 자기 약점 타입을 찌르는 견제기인지
  ④ only_this_hits_top30: 픽률 상위 중 이 기술로만 효과가 굉장한 포켓몬 (견제 대상 이름)
- 위를 다 봐도 이유를 댈 수 없는 선택만 지어내지 말고 정중하게 모르겠다고 쓴다
  (예: "스톤에지를 넣은 이유는 공개된 자료로는 모르겠어요.")

설명 글만 출력한다 (따옴표·제목·머리말 없이)."""

STRUCTURE = {
    'sample': '① 첫 문장에 역할과 핵심(도구·SP로 무엇을 하는지) ② 같은 포켓몬 다른 샘플(others)과 다른 점 '
              '③ 기술·도구 선택 이유 ④ 한계나 운용 주의(막히는 상대, 언제 교체). 드문 형태(shapes.rare)면 드문 형태라고 밝힌다',
    'party': '① 첫 문장에 컨셉(균형·스윕·사이클·트릭룸·순풍 등)과 축(메가·에이스) ② 멤버끼리 받아 주는 관계·판 깔기→딜러 연결 2개 이상 '
             '③ threats·겹치는 약점 중 핵심 1~2개와 누구로 대응하는지 ④ 선봉·운용 순서. 메가스톤이 3개 이상이면 선출 제한을 알린다',
}

JUDGE_SYSTEM = """너는 포켓몬 챔피언스(Reg M-C) {what} 설명의 심사자다. [근거 묶음]과 [설명]을 보고 아래 감점표에서 해당하는 규칙을 고른다.

- 점수는 매기지 않는다. 해당하는 감점 규칙 ID만 고른다 (점수는 하네스가 계산)
- 판단은 근거 묶음 기준. 근거 묶음 밖의 지식으로 "틀렸다"고 하지 않는다. 다만 기술·특성·도구의 효과 자체를 잘못 쓴 것(J1-a)은 게임 지식으로 판단한다
- quote: 설명에서 글자 그대로 옮긴 문구. 빠진 내용을 지적하는 규칙이면 ""
- fix: 고칠 방향 한 줄. 설명을 직접 다시 쓰지 않는다
- "이유를 모르겠다"고 쓴 선택은 J3-b로 감점하지 않는다. 근거 묶음에 이유가 정말 없는지 보고, 있으면 J3-d
  (usage_pct가 높음, desc의 부가 효과, super_effective_on이 자신의 weak_to를 찌름, only_this_hits_top30에 견제 대상이 있음 — 이 중 하나라도 있으면 이유가 있는 것)
- 근거 묶음이 부족해 그 항목을 쓸 수 없으면 na에 항목과 사유 (J1·J2·J3은 na 불가)
- 문제가 없으면 deductions는 빈 배열
- 파일을 읽거나 명령을 실행하지 않는다. 필요한 것은 모두 아래 글에 있다
- 길이 기준: {length} (J6-d는 이 설명이 {soft}자를 넘으면). 이 설명은 {chars}자

감점표
{rubric}

출력: JSON 한 개 {{"deductions": [{{"rule", "quote", "fix"}}], "na": [{{"item", "reason"}}]}}"""


def writer_system(kind: str, packet: dict) -> str:
    lo, hi, slo, shi = rubric.LENGTH[kind]
    doubles = packet['format'] == '더블'
    return WRITER_SYSTEM.format(
        what='샘플(육성형)' if kind == 'sample' else '파티',
        fmt_rule=('더블 설명이다. 판을 까는 역할은 "서포터"라고 부르고 "기점잡이"라고 하지 않는다' if doubles else
                  '싱글 설명이다. 판을 까는 역할은 "기점잡이". 더블 전용 운용(속이기 견제·날따름 등)을 주된 역할로 쓰지 않는다'),
        length=f'{lo}~{hi}자, 문장 {slo}~{shi}개 (상한의 80%를 넘지 않게 짧게)',
        structure=STRUCTURE[kind])


def packet_text(packet: dict) -> str:
    return '[근거 묶음]\n' + json.dumps(packet, ensure_ascii=False, indent=1)


class Store:
    """통과·검수 대기 설명. 키마다 마지막 기록이 유효."""

    def __init__(self, kind: str):
        OUT.mkdir(parents=True, exist_ok=True)
        self.path = OUT / f'{kind}.jsonl'
        self.rows = {}
        if self.path.exists():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.rows[r['key']] = r

    def done(self, key: str, h: str) -> bool:
        r = self.rows.get(key)
        return bool(r and r['packet_hash'] == h and r['status'] == 'passed')

    def others(self, key: str, group: str | None) -> list[str]:
        return [r['text'] for k, r in self.rows.items() if k != key and r['status'] == 'passed'
                and (group is None or r.get('group') == group)]

    def save(self, row: dict) -> None:
        self.rows[row['key']] = row
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


class Harness:
    def __init__(self, args, live: Live):
        self.a = args
        self.live = live
        from harness.facts import Facts     # Django를 여기서 불러옴 (테스트는 DB 없이)
        self.facts = Facts()
        n = self.facts.n
        self.vocab = {k: sorted({r['name_ko'] for r in n[k].values() if r.get('name_ko')} - VOCAB_STOP)
                      for k in ('pokemon', 'move', 'item', 'ability')}

    def model_label(self, provider: str) -> str:
        m = self.a.writer_model if provider == self.a.writer else self.a.judge_model
        return f'{"Claude" if provider == "claude" else "GPT"}{" · " + m if m else ""}'

    # ------------------------------------------------------------ 모델 부르기

    def call(self, ch: str, role: str, system: str, prompt: str, label: str, schema=None) -> str:
        provider = self.a.writer if role == 'writer' else self.a.judge
        model = self.a.writer_model if role == 'writer' else self.a.judge_model
        effort = self.a.writer_effort if role == 'writer' else self.a.judge_effort
        on_delta, end = self.live.stream(ch, role, self.model_label(provider), label)
        try:
            text = ask(provider, system, prompt, on_delta, model, effort, schema)
        except CliError as e:
            end('', str(e))
            raise
        end(text)
        return text

    def write(self, ch, kind, packet, prev: str | None, feedback: list[str], label: str) -> str:
        if prev is None:
            prompt = packet_text(packet) + '\n\n위 근거 묶음으로 설명을 써 줘.'
        else:
            prompt = (packet_text(packet) + f'\n\n[이전 설명]\n{prev}\n\n[고칠 점]\n' + '\n'.join(f'- {x}' for x in feedback) +
                      '\n\n고칠 점에 나온 문장만 고치고, 지적받지 않은 문장은 그대로 둔 설명 전체를 다시 출력해.')
        text = self.call(ch, 'writer', writer_system(kind, packet), prompt, label)
        return text.strip().strip('"').strip()

    def judge(self, ch, kind, packet, text: str) -> tuple[list[dict], dict]:
        lo, hi, slo, shi = rubric.LENGTH[kind]
        system = JUDGE_SYSTEM.format(what='샘플' if kind == 'sample' else '파티', rubric=rubric.rubric_text(kind),
                                     length=f'{lo}~{hi}자, 문장 {slo}~{shi}개', soft=int(hi * 0.8), chars=len(text))
        prompt = packet_text(packet) + f'\n\n[설명]\n{text}'
        for attempt in range(2):
            raw = self.call(ch, 'judge', system, prompt, '심사' if not attempt else '다시 심사', JUDGE_SCHEMA)
            try:
                out = parse_json(raw)
            except (ValueError, json.JSONDecodeError):
                self.live.say(ch, 'harness', '심사 결과가 JSON이 아니에요. 다시 부를게요.')
                continue
            ded = [d for d in out.get('deductions', []) if d.get('rule') in rubric.RULES]
            fake = [d for d in ded if d.get('quote') and d['quote'] not in text]
            na = {x['item']: x['reason'] for x in out.get('na', []) if x.get('item')}
            if fake and not attempt:
                self.live.say(ch, 'harness', '설명에 없는 문구를 인용한 감점이 있어서 한 번 다시 심사할게요.',
                              {'color': 'warn', 'list': [{'code': d['rule'], 'text': d['quote']} for d in fake]})
                prompt += '\n\n(주의: quote는 설명에 실제로 있는 문구를 글자 그대로 옮겨야 한다. 지난 심사에서 없는 문구를 인용했다)'
                continue
            return [d for d in ded if d not in fake], na
        return [], {}

    # ------------------------------------------------------------ 한 건

    def run_one(self, kind: str, key: str, title: str, packet: dict, group: str | None, store: Store) -> dict:
        ch = key
        self.live.channel(ch, title, kind, packet)
        grounding = grounding_text(packet)
        others = store.others(key, group)
        prev, feedback, best = None, [], None
        streak = {}                # 자동 검사 (A항목, 문구) / 심사 규칙 ID → 연속 실패 수
        reverts = {}               # 되돌린 설명의 라운드 → 되돌린 횟수
        keep = {}                  # 되돌릴 때 알려 줄 "빼면 감점되는 내용" (규칙 → fix)
        last_sig, same = None, 0   # 직전 감점 묶음, 연속 횟수
        history = []
        rnd = 0
        mode = 'write'
        while True:
            rnd += 1
            if self.a.max_rounds and rnd > self.a.max_rounds:
                return self.finish(kind, key, title, packet, group, store, best, history, 'needs_review',
                                   f'--max-rounds {self.a.max_rounds} 도달')
            try:
                text = self.write(ch, kind, packet, None if mode == 'write' else prev, feedback,
                                  f'{rnd}번째 ' + ('작성' if mode == 'write' else '고쳐 쓰기'))
            except CliError as e:
                self.live.say(ch, 'harness', f'작성 모델 호출 실패: {e}')
                return self.finish(kind, key, title, packet, group, store, best, history, 'error', str(e))
            prev = text

            # 1차 자동 검사
            fails = rubric.auto_check(kind, text, packet, grounding, self.vocab, others=others)
            if fails:
                feedback = []
                streak = {k: streak.get(k, 0) + 1 for k in {(f['id'], f['msg']) for f in fails}}
                for f in fails:
                    k = (f['id'], f['msg'])
                    hint = ' → 같은 문제가 반복돼요. 그 내용을 빼거나 근거 묶음에 있는 말로만 쓰세요' if streak[k] >= 2 else ''
                    feedback.append(f'[{f["id"]}] {f["msg"]}{hint}')
                history.append({'round': rnd, 'text': text, 'auto_fail': fails})
                self.live.say(ch, 'harness', f'1차 자동 검사에서 {len(fails)}개 걸렸어요. 고쳐 써 주세요.',
                              {'color': 'bad', 'title': '1차 자동 검사 실패',
                               'list': [{'code': f['id'], 'text': f['msg']} for f in fails]})
                mode = 'fix'
                continue
            self.live.say(ch, 'harness', '1차 자동 검사 통과. 심사로 넘길게요.')

            # 2차 심사
            try:
                ded, na = self.judge(ch, kind, packet, text)
            except CliError as e:
                self.live.say(ch, 'harness', f'심사 모델 호출 실패: {e}')
                return self.finish(kind, key, title, packet, group, store, best, history, 'error', str(e))
            sc = rubric.score(kind, ded, na)
            unknown = [s for s in rubric.sentences(text) if UNKNOWN.search(s)]
            history.append({'round': rnd, 'text': text, 'deductions': ded, 'na': na, 'score': sc, 'unknown': unknown})
            self.live.say(ch, 'harness', self.verdict(sc), self.score_embed(kind, sc, ded))
            self.live.status(ch, 'running', sc['total'], rnd)

            if best is None or sc['total'] > best['score']['total'] or (sc['pass'] and not best['score']['pass']):
                best = history[-1]
            if sc['pass']:
                return self.finish(kind, key, title, packet, group, store, history[-1], history, 'passed')
            if sc['too_many_na']:
                return self.finish(kind, key, title, packet, group, store, best, history, 'needs_review',
                                   f'N/A {len(sc["na"])}개: 근거 묶음이 부족해요')
            if len(unknown) > CHOICES // 2:
                return self.finish(kind, key, title, packet, group, store, best, history, 'needs_review',
                                   f'"모르겠다"가 {len(unknown)}개: 근거 묶음이 부족해요')

            # 연속 실패: 매 라운드 규칙 ID로 센다 (심사자가 fix 문구를 매번 다르게 써서 문구로는 못 잡음)
            streak = {r: streak.get(r, 0) + 1 for r in {d['rule'] for d in ded}}
            # 맴돌기: 같은 감점 묶음이 STALL번 연속이면 더 고쳐도 같은 결과라 멈춘다 (가장 좋았던 설명을 저장)
            sig = tuple(sorted(d['rule'] for d in ded))
            same = same + 1 if sig == last_sig else 1
            last_sig = sig
            if same >= STALL:
                return self.finish(kind, key, title, packet, group, store, best, history, 'needs_review',
                                   f'같은 감점({", ".join(sig)})이 {same}번 연속이라 멈췄어요')

            # 점수가 떨어졌으면 가장 좋았던 설명으로 되돌린다. 같은 설명으로는 2번까지만 (그 뒤로는 지금 설명에서 계속)
            # 되돌릴 때는 실패한 시도에서 새로 생긴 감점(줄이다가 뺀 내용)을 "남겨 두기"로 알려 줘서 같은 실수를 막는다
            target = history[-1]
            if best is not target and best['score']['total'] > sc['total'] and reverts.get(best['round'], 0) < 2:
                reverts[best['round']] = reverts.get(best['round'], 0) + 1
                target = best
                prev = best['text']
                best_rules = {d['rule'] for d in best['deductions']}
                for d in ded:
                    if d['rule'] not in best_rules:
                        keep[d['rule']] = d['fix']
                self.live.say(ch, 'harness', f'점수가 {best["score"]["total"]} → {sc["total"]}로 떨어져서 '
                                             f'{best["score"]["total"]}점짜리 설명으로 되돌렸어요 '
                                             f'({reverts[best["round"]]}/2). 줄이다가 빠진 내용은 남겨 두라고 할게요.')
            elif best is not target and best['score']['total'] > sc['total']:
                self.live.say(ch, 'harness', '같은 설명으로 2번 되돌렸는데도 안 돼서, 이번 설명에서 계속 고칠게요.')
            sc_t, ded_t = target['score'], target['deductions']
            # 고쳐 쓰기 준비: 최소점수 미달 항목 먼저, 감점 큰 순서 (감점 크기를 같이 알려 줘서 길이와 내용 중 무엇이 급한지 알게)
            ded_sorted = sorted(ded_t, key=lambda d: (d['rule'].split('-')[0] not in sc_t['below_min'],
                                                      -rubric.rule_points(d['rule'], kind)))
            feedback = []
            for d in ded_sorted:
                r = d['rule']
                line = (f'[{r} -{rubric.rule_points(r, kind)}점 {rubric.RULES[r][0]}] ' +
                        (f'"{d["quote"]}" → ' if d['quote'] else '') + d['fix'])
                if streak.get(r, 0) >= 2:
                    line += (' → 계속 반복되는 지적이에요. 근거 묶음으로 이유를 대거나, 정말 댈 수 없으면 '
                             '"…한 이유는 공개된 자료로는 모르겠어요"처럼 모르겠다고 쓰세요' if r in REASON_RULES else
                             ' → 계속 반복되는 지적이에요. 다른 문장을 줄여서라도 이 내용을 한 구절 꼭 넣으세요')
                feedback.append(line)
            if target is best and keep:
                feedback += [f'[남겨 두기] 지난번에 줄이다가 이 내용이 빠져서 감점됐어요: {fix} ({r} -{rubric.rule_points(r, kind)}점)' +
                             (' → 계속 반복되는 지적이에요. 이 내용은 절대 빼지 마세요' if streak.get(r, 0) >= 2 else '')
                             for r, fix in keep.items() if r not in {d['rule'] for d in ded_t}]
            if any(d['rule'] == 'J6-d' for d in ded_t):
                feedback.append('길이 초과(J6-d)는 -2점뿐이에요. 줄일 때 기술 이유·언제 꺼내는지 같은 내용은 빼지 말고 꾸밈말을 줄이세요')
            for k in sc_t['below_min']:
                feedback.insert(0, f'{k} {rubric.ITEMS[kind][k][0]}이(가) 최소점수 미달이에요 '
                                   f'({sc_t["items"][k]}/{rubric.ITEMS[kind][k][1]}, 최소 {rubric.ITEMS[kind][k][2]})')
            mode = 'write' if sc_t['total'] < rubric.REWRITE_BELOW else 'fix'
            if mode == 'write':
                self.live.say(ch, 'harness', f'{sc_t["total"]}점이라 {rubric.REWRITE_BELOW}점 미만이에요. 새로 써 주세요.')
                feedback = []

    def verdict(self, sc: dict) -> str:
        if sc['pass']:
            return f'{sc["total"]}점, 통과예요.'
        why = []
        if sc['below_min']:
            why.append('최소점수 미달: ' + ', '.join(sc['below_min']))
        if sc['total'] < rubric.PASS_TOTAL:
            why.append(f'합계 {rubric.PASS_TOTAL}점 미만')
        return f'{sc["total"]}점, 아직 통과 못 했어요 ({" / ".join(why) or "N/A 과다"}).'

    @staticmethod
    def score_embed(kind: str, sc: dict, ded: list[dict]) -> dict:
        fields = []
        for k, (name, full, low) in rubric.ITEMS[kind].items():
            if k in sc['na']:
                fields.append({'name': f'{k} {name}', 'value': 'N/A'})
            else:
                fields.append({'name': f'{k} {name}', 'value': f'{sc["items"][k]}/{full} (최소 {low})',
                               'low': k in sc['below_min']})
        return {'title': f'심사 점수 {sc["total"]}/100', 'color': 'ok' if sc['pass'] else 'warn' if sc['total'] >= 70 else 'bad',
                'fields': fields,
                'list': [{'code': f'{d["rule"]} -{rubric.rule_points(d["rule"], kind)}',
                          'text': (f'"{d["quote"]}" → ' if d['quote'] else '') + d['fix']} for d in ded]}

    def finish(self, kind, key, title, packet, group, store, best, history, status, reason=''):
        row = {'key': key, 'kind': kind, 'title': title, 'group': group, 'status': status, 'reason': reason,
               'text': best['text'] if best else (history[-1]['text'] if history else ''),
               'score': best.get('score') if best else None, 'deductions': best.get('deductions') if best else None,
               'unknown': best.get('unknown') if best else None, 'rounds': len(history),
               'rubric_version': rubric.RUBRIC_VERSION, 'writer': self.model_label(self.a.writer),
               'judge': self.model_label(self.a.judge), 'packet_hash': packet_hash(packet),
               'date': datetime.now().isoformat(timespec='seconds')}
        if status != 'error':
            store.save(row)
        total = row['score']['total'] if row['score'] else None
        msg = {'passed': f'통과한 설명을 저장했어요 ({len(history)}회).',
               'needs_review': f'사람 검수로 넘겨요: {reason}',
               'error': f'중단했어요: {reason}'}[status]
        self.live.say(key, 'harness', msg, {'color': 'ok' if status == 'passed' else 'bad', 'title': '최종 설명',
                                            'list': [{'text': row['text']}] if row['text'] else []})
        self.live.status(key, status, total, len(history))
        return row

    # ------------------------------------------------------------ 전체

    def items(self, kind: str):
        f = self.facts
        if kind == 'sample':
            for key, fmt, s in f.samples(self.a.format, self.a.pokemon):
                packet = f.sample_packet(fmt, s)
                title = f'{packet["pokemon"]["name_ko"]} @ {packet["item"]["name_ko"]} ({packet["format"]})'
                yield key, title, packet, f'{fmt}:{s.pokemon_key}'
        else:
            for key, fmt, t, ms in f.parties(self.a.format):
                packet = f.party_packet(fmt, t, ms)
                title = (t.name or ' · '.join(m['name_ko'] for m in packet['members'][:3]) + ' …') + f' ({packet["format"]})'
                yield key, title, packet, None

    def run(self) -> None:
        kind = self.a.kind
        store = Store(kind)
        self.live.emit('run_start', writer=self.a.writer, judge=self.a.judge, kind='샘플' if kind == 'sample' else '파티',
                       format=self.a.format or '')
        done = 0
        for key, title, packet, group in self.items(kind):
            if store.done(key, packet_hash(packet)) and not self.a.redo:
                continue
            self.run_one(kind, key, title, packet, group, store)
            done += 1
            if self.a.limit and done >= self.a.limit:
                break
        self.live.emit('run_end', text=f'끝났어요. {done}건 처리.')


# 기술·특성 이름인데 설명에서 일반 낱말로도 쓰여서 이름 근거 검사에서 빼는 것
VOCAB_STOP = {'방어', '공격', '위협', '압력', '가속', '회복', '교체', '도발', '대타출동', '잠자기', '스피드', '순풍', '보호'}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--kind', choices=['sample', 'party'], default='sample')
    ap.add_argument('--format', choices=['singles', 'doubles'])
    ap.add_argument('--pokemon', help='샘플: 이 포켓몬 ID만 (예: garchomp)')
    ap.add_argument('--limit', type=int, default=0, help='이번에 처리할 개수 (0 = 전부)')
    ap.add_argument('--writer', choices=['claude', 'codex'], default='claude')
    ap.add_argument('--judge', choices=['claude', 'codex'], default='codex')
    ap.add_argument('--writer-model', help='예: opus, sonnet / gpt-5.5')
    ap.add_argument('--judge-model')
    ap.add_argument('--writer-effort', help='claude: low~max / codex: low·medium·high')
    ap.add_argument('--judge-effort', default='medium', help='기본 medium (codex 기본값은 한 번에 2~5분·사용량 많음)')
    ap.add_argument('--max-rounds', type=int, default=0, help='안전장치 (0 = 제한 없음, 기본)')
    ap.add_argument('--redo', action='store_true', help='이미 통과한 것도 다시')
    ap.add_argument('--port', type=int, default=8002, help='실시간 보기 포트 (0 = 끔)')
    ap.add_argument('--keep-open', action='store_true', help='끝난 뒤에도 실시간 보기 페이지를 열어 둠 (Ctrl+C로 종료)')
    a = ap.parse_args()
    live = Live(LOGS / f'{datetime.now():%Y%m%d-%H%M%S}-{a.kind}.jsonl', a.port or None)
    try:
        Harness(a, live).run()
        if a.keep_open and a.port:
            print('끝났어요. 페이지는 열어 둘게요 (Ctrl+C로 종료).', flush=True)
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        print('\n중단했어요. 통과한 설명은 저장돼 있어요.')


if __name__ == '__main__':
    main()
