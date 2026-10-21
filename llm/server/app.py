"""파티 코치 채팅 서버 (SSE).

    cd llm && ../.venv/bin/uvicorn server.app:app --port 8001    (Windows: ..\\.venv\\Scripts\\uvicorn)

POST /llm/chat  {"history": [{"role": "user"|"assistant", "text": "..."}], "format": "doubles", "party": [샘플|null ×6]}
→ text/event-stream. event: status / text / party / error / done, data: JSON
"""
import json
import logging

import anthropic
import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from agent import classify, intents
from agent.loop import build_messages, run_agent, subject_of
from agent.tools import Tools
from providers.claude import ClaudeProvider

logging.basicConfig(level=logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger(__name__)

app = FastAPI(title='pokemon party coach')
_provider = None


def get_provider():
    global _provider
    if _provider is None:
        if config.LLM_PROVIDER == 'qwen':
            from providers.qwen import QwenProvider      # transformers는 qwen을 쓸 때만
            _provider = QwenProvider()
        else:
            _provider = ClaudeProvider()
    return _provider


def back_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=config.BACK_URL, timeout=30)


class Turn(BaseModel):
    role: str
    text: str = ''
    party: list[dict] | None = None      # 코치 답변이 띄운 추천 파티 (기록에 한 줄로 붙임)


class ChatRequest(BaseModel):
    history: list[Turn]
    format: str = 'singles'
    party: list[dict | None] = []


def sse(event: str, data) -> str:
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def api_error_text(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return 'LLM API 키를 확인해 주세요 (llm/.env의 ANTHROPIC_API_KEY).'
    if isinstance(e, anthropic.RateLimitError):
        return '요청이 많아 잠시 막혔습니다. 조금 뒤에 다시 물어봐 주세요.'
    if isinstance(e, anthropic.APIConnectionError):
        return 'LLM API에 접속하지 못했습니다.'
    if isinstance(e, anthropic.APIStatusError):
        return f'LLM API 오류 ({e.status_code})'
    return '답변 중 오류가 났습니다.'


@app.get('/llm/health')
async def health():
    return {'ok': True, 'mode': config.COACH_MODE, 'model': 'qwen' if config.LLM_PROVIDER == 'qwen' else config.LLM_MODEL}


@app.on_event('startup')
async def load_local_model():
    if config.LLM_PROVIDER == 'qwen' and config.COACH_MODE == 'agent':     # 어댑터 폴더(토크나이저)가 없으면 켤 때 바로 알림
        get_provider()


async def intent_events(tools: Tools, history: list[dict], party: list[dict]):
    question, previous = history[-1]['text'], history[:-1]
    intent = await intents.parse(question, previous, tools, classify=classify.classify, party_size=len(party))
    log.info('의도 %s', intent)
    if intent.get('format') in ('singles', 'doubles'):
        tools.format = intent['format']                 # "더블 파티"처럼 질문에 포맷이 있으면 그걸로
    async for event in intents.run(intent, tools, party, previous):
        yield event


@app.post('/llm/chat')
async def chat(req: ChatRequest):
    try:
        try:
            async with back_client() as client:
                names = await Tools(client, req.format).party_names(req.party)
        except httpx.HTTPError:
            names = None                                # back이 꺼져 있으면 이름 없이 (도구 호출에서 오류로 알려 줌)
        history = [t.model_dump() for t in req.history]
        messages = build_messages(history, req.format, req.party, names)
        subject = subject_of(history, req.party, names)
    except ValueError as e:
        return StreamingResponse(iter([sse('error', {'message': str(e)}), sse('done', {})]),
                                 media_type='text/event-stream')

    async def stream():
        async with back_client() as client:
            tools = Tools(client, req.format)
            tools.subject = subject                     # 모델이 포켓몬 자리에 도구 이름을 넣으면 이 포켓몬으로 (agent/loop.py)
            try:
                if config.COACH_MODE == 'intent':      # 질문 → 의도 → 서버가 DB로 답 (agent/intents.py)
                    events = intent_events(tools, history, [m for m in req.party if m])
                else:
                    events = run_agent(get_provider(), tools, messages)
                async for kind, value in events:
                    if kind == 'text':
                        yield sse('text', {'delta': value})
                    elif kind == 'status':
                        yield sse('status', {'text': value})
                    elif kind == 'party':
                        yield sse('party', {'members': value})
                    else:
                        yield sse('error', {'message': value})
            except anthropic.APIError as e:
                log.warning('LLM API 오류: %s', e)
                yield sse('error', {'message': api_error_text(e)})
            except Exception:
                log.exception('채팅 처리 실패')
                yield sse('error', {'message': api_error_text(Exception())})
        yield sse('done', {})

    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
