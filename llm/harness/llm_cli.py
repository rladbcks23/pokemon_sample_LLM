"""구독 모델을 CLI로 부르기 (종량제 API 키를 쓰지 않음).

- claude: Claude Code CLI (`claude -p`), Claude 구독 로그인
- codex: OpenAI Codex CLI (`codex exec`), ChatGPT 구독 로그인

API 키 환경 변수가 있으면 CLI가 구독 대신 종량제 API로 붙을 수 있어서, 자식 프로세스에서는 지운다.
도구는 끄고(claude) 읽기 전용 샌드박스(codex)로, 빈 임시 폴더에서 실행한다 (글만 쓰게).
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

PAID_KEYS = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY', 'CODEX_API_KEY')
WORK = Path(tempfile.gettempdir()) / 'pokemon_harness'

OnDelta = Callable[[str, str], None]      # (종류 'text'|'thinking', 조각)


class CliError(RuntimeError):
    pass


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in PAID_KEYS}
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def _exe(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise CliError(f'{name} CLI가 없음 (npm i -g 로 설치 후 로그인)')
    return path


def _run(cmd: list[str], stdin: str, on_line: Callable[[dict], None]) -> None:
    WORK.mkdir(exist_ok=True)
    p = subprocess.Popen(cmd, cwd=WORK, env=_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    p.stdin.write(stdin)
    p.stdin.close()
    for line in p.stdout:
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            on_line(json.loads(line))
        except json.JSONDecodeError:
            continue
    err = p.stderr.read()
    if p.wait() != 0:
        raise CliError(f'{Path(cmd[0]).name} 종료 코드 {p.returncode}: {err.strip()[-500:]}')


def ask_claude(system: str, prompt: str, on_delta: OnDelta, model: str | None = None, effort: str | None = None) -> str:
    WORK.mkdir(exist_ok=True)
    sys_file = WORK / 'system_claude.txt'
    sys_file.write_text(system, encoding='utf-8')
    cmd = [_exe('claude'), '-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
           '--tools', '', '--strict-mcp-config', '--no-session-persistence', '--disable-slash-commands',
           '--system-prompt-file', str(sys_file)]
    if model:
        cmd += ['--model', model]
    if effort:
        cmd += ['--effort', effort]
    out = {'text': '', 'result': None, 'error': None}

    def on_line(ev):
        if ev.get('type') == 'stream_event':
            d = (ev.get('event') or {}).get('delta') or {}
            if d.get('type') == 'text_delta':
                out['text'] += d['text']
                on_delta('text', d['text'])
            elif d.get('type') == 'thinking_delta':
                on_delta('thinking', d.get('thinking', ''))
        elif ev.get('type') == 'result':
            out['result'] = ev.get('result')
            if ev.get('is_error'):
                out['error'] = ev.get('result') or ev.get('subtype')

    _run(cmd, prompt, on_line)
    if out['error']:
        raise CliError(f'claude: {out["error"]}')
    return (out['result'] if out['result'] is not None else out['text']).strip()


def ask_codex(system: str, prompt: str, on_delta: OnDelta, model: str | None = None, effort: str | None = None,
              schema: dict | None = None) -> str:
    WORK.mkdir(exist_ok=True)
    cmd = [_exe('codex'), 'exec', '--json', '--ephemeral', '--skip-git-repo-check', '-s', 'read-only',
           '-C', str(WORK)]
    if model:
        cmd += ['-m', model]
    if effort:
        cmd += ['-c', f'model_reasoning_effort="{effort}"']
    if schema:
        f = WORK / 'schema_codex.json'
        f.write_text(json.dumps(schema), encoding='utf-8')
        cmd += ['--output-schema', str(f)]
    cmd.append('-')
    seen = {}          # item id → 지금까지 보낸 글 (item.updated가 전체 글을 다시 보내므로 늘어난 부분만)
    out = {'text': '', 'error': None}

    def on_line(ev):
        t = ev.get('type', '')
        if t in ('item.started', 'item.updated', 'item.completed'):
            item = ev.get('item') or {}
            kind = {'agent_message': 'text', 'reasoning': 'thinking'}.get(item.get('type') or item.get('item_type'))
            text = item.get('text') or ''
            if not kind:
                return
            prev = seen.get(item.get('id'), '')
            if text.startswith(prev) and len(text) > len(prev):
                on_delta(kind, text[len(prev):])
            seen[item.get('id')] = text
            if kind == 'text' and t == 'item.completed':
                out['text'] = text
        elif t in ('error', 'turn.failed'):
            out['error'] = ev.get('message') or (ev.get('error') or {}).get('message') or json.dumps(ev)

    _run(cmd, f'{system}\n\n{prompt}', on_line)
    if out['error'] and not out['text']:
        raise CliError(f'codex: {out["error"]}')
    return out['text'].strip()


def ask(provider: str, system: str, prompt: str, on_delta: OnDelta, model: str | None = None,
        effort: str | None = None, schema: dict | None = None) -> str:
    if provider == 'claude':
        return ask_claude(system, prompt + (f'\n\n출력은 이 JSON 스키마를 따른다:\n{json.dumps(schema, ensure_ascii=False)}'
                                            if schema else ''), on_delta, model, effort)
    if provider == 'codex':
        return ask_codex(system, prompt, on_delta, model, effort, schema)
    raise ValueError(f'모르는 provider: {provider}')


def parse_json(text: str) -> dict:
    """응답에서 JSON 객체 하나 (앞뒤 글·코드 블록이 붙어도)."""
    s, e = text.find('{'), text.rfind('}')
    if s < 0 or e < s:
        raise ValueError('JSON이 없음')
    return json.loads(text[s:e + 1])
