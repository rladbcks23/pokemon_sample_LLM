"""하네스 대화 실시간 보기: 이벤트를 로그 파일에 쌓고, 브라우저에 SSE로 흘려 보낸다.

http://localhost:8002 를 열면 디스코드처럼 채널(샘플·파티)마다 하네스·작성자·심사자가 주고받는 대화가 보인다.
늦게 열어도 처음부터 다시 보여 준다. 터미널에도 한 줄씩 찍는다.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from pathlib import Path

VIEWER = Path(__file__).with_name('viewer.html')


class Live:
    def __init__(self, log_path: Path, port: int | None = 8002, quiet: bool = False):
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.ids = count(1)
        self.quiet = quiet
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log_path.open('a', encoding='utf-8')
        if port:
            self._serve(port)

    # ------------------------------------------------------------ 이벤트

    def emit(self, type_: str, **data) -> dict:
        ev = {'id': next(self.ids), 'type': type_, 'ts': time.time(), **data}
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()
        if type_ != 'delta':                      # 조각은 너무 많아서 로그에는 완성된 메시지만
            self.log.write(json.dumps(ev, ensure_ascii=False) + '\n')
            self.log.flush()
        self._print(ev)
        return ev

    def channel(self, key: str, title: str, kind: str, packet: dict) -> None:
        self.emit('channel', channel=key, title=title, kind=kind, packet=packet)

    def say(self, channel: str, author: str, text: str, embed: dict | None = None) -> None:
        self.emit('msg', channel=channel, author=author, text=text, embed=embed)

    def stream(self, channel: str, author: str, model: str, label: str = ''):
        """작성자·심사자 메시지: 시작 → 조각(delta) → 끝. on_delta를 CLI에 넘긴다."""
        msg = next(self.ids)
        self.emit('msg_start', channel=channel, msg=msg, author=author, model=model, label=label)

        def on_delta(kind: str, text: str):
            if text:
                self.emit('delta', channel=channel, msg=msg, kind=kind, text=text)

        def end(text: str, error: str | None = None):
            self.emit('msg_end', channel=channel, msg=msg, text=text, error=error)

        return on_delta, end

    def status(self, channel: str, status: str, total: float | None = None, rounds: int = 0) -> None:
        self.emit('status', channel=channel, status=status, total=total, rounds=rounds)

    # ------------------------------------------------------------ 터미널

    def _print(self, ev: dict) -> None:
        if self.quiet or ev['type'] == 'delta':
            return
        t = ev['type']
        if t == 'channel':
            line = f'\n#### {ev["title"]} ({ev["channel"]})'
        elif t == 'msg':
            line = f'[하네스] {ev["text"]}'
        elif t == 'msg_start':
            line = f'[{ev["author"]} · {ev["model"]}] {ev.get("label", "")} …'
        elif t == 'msg_end':
            body = ev['text'] if len(ev['text']) < 400 else ev['text'][:400] + ' …'
            line = f'  └ {body}' + (f'  (오류: {ev["error"]})' if ev.get('error') else '')
        elif t == 'run_start':
            line = f'작성 {ev["writer"]} · 심사 {ev["judge"]} · {ev["kind"]} {ev.get("format", "")}'
        elif t == 'status':
            line = f'==> {ev["status"]} {ev.get("total") or ""} ({ev.get("rounds")}회)'
        else:
            line = f'[{t}] {ev.get("text", "")}'
        print(line, flush=True)

    # ------------------------------------------------------------ 웹

    def _serve(self, port: int) -> None:
        live = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path in ('/', '/index.html'):
                    body = VIEWER.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith('/events'):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    sent = 0
                    try:
                        while True:
                            with live.cond:
                                while sent >= len(live.events):
                                    if not live.cond.wait(timeout=15):
                                        break
                                batch = live.events[sent:]
                            if not batch:
                                self.wfile.write(b': ping\n\n')
                            for ev in batch:
                                self.wfile.write(f'data: {json.dumps(ev, ensure_ascii=False)}\n\n'.encode())
                            sent += len(batch)
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                else:
                    self.send_error(404)

        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f'실시간 보기: http://localhost:{port}', flush=True)
