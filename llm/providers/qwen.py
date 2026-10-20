"""로컬 Qwen3.5-4B + LoRA provider. ClaudeProvider와 같은 모양으로 turn()을 낸다.

생성은 llama.cpp 서버(llama-server, GGUF Q8_0, 기본 8080)가 하고, 여기서는 학습과 같은 입력 표현
(training/scripts/compact_context + 어댑터 폴더의 채팅 템플릿)으로 프롬프트를 만들어 보낸다.
Qwen 도구 호출(<tool_call><function=…>)은 Claude 형식 tool_use 블록으로 돌려준다.
(transformers+bitsandbytes로 직접 돌리면 Windows에서 초당 2토큰 정도라 llama.cpp로 바꿈)
"""
import json
import logging
import time
import re
from itertools import count
from pathlib import Path
from types import SimpleNamespace as NS

import httpx

import config
from training.scripts.compact_context import prepare_messages, system_prompt

TOOL_CALL = re.compile(r'<tool_call>\s*<function=([\w-]+)>(.*?)</function>\s*</tool_call>', re.S)
PARAM = re.compile(r'<parameter=([\w-]+)>\n?(.*?)\n?</parameter>', re.S)
log = logging.getLogger(__name__)
NOISE = (r'<think>.*?</think>', r'<tool_call>.*?</tool_call>', r'<\|im_end\|>.*', r'<\|endoftext\|>')


def parse_calls(text: str) -> list[tuple[str, dict]]:
    """Qwen3.5 도구 호출 → [(이름, 인자)]. 값이 JSON이면 풀어서 (Colab 노트북과 같음)."""
    calls = []
    for name, body in TOOL_CALL.findall(text):
        args = {}
        for k, v in PARAM.findall(body):
            try:
                args[k] = json.loads(v)
            except json.JSONDecodeError:
                args[k] = v
        calls.append((name, args))
    return calls


# 답변 글자 제한 (llama.cpp GBNF). 4B 모델이 프랑스어·그리스어·일본어 등을 섞어서:
# 도구 호출(<tool_call>로 시작)은 그대로, 글 답변은 한글·숫자·기호와 정해진 영문(OP.GG, SP, VGCPastes,
# SP 표기 H2 C32 S32), 작은따옴표 안의 팀 이름만. 영문을 대문자 전체로 열어 두면 "ESPECIAL"처럼 빠져나가서 막음
GRAMMAR = r'''
root   ::= tool | answer
tool   ::= "<tool_call>" .*
answer ::= (char | word | stat | quoted)+
char   ::= [가-힣ㄱ-ㅎㅏ-ㅣ0-9 \n.,!?:;()/@%·…—–→←×~+=*#&_\[\]-]
word   ::= "OP.GG" | "SP" | "VGCPastes"
stat   ::= [HABCDS] [0-9]+
quoted ::= "'" [^'\n]* "'"
'''


def clean(text: str) -> str:
    for pat in NOISE:
        text = re.sub(pat, '', text, flags=re.S)
    # 같은 구절(6자 이상)이 5번 넘게 연달아 나오면 한 번만 남김 (반복에 빠진 출력)
    text = re.sub(r'(.{6,}?)\1{4,}', r'\1', text, flags=re.S)
    return text.strip()


def to_training_format(messages: list) -> list[dict]:
    """에이전트 루프의 Claude 형식 메시지 → 학습 데이터 형식 (assistant tool_calls, role=tool)."""
    out = []
    for m in messages:
        c = m['content']
        if isinstance(c, str):
            out.append({'role': m['role'], 'content': c})
        elif m['role'] == 'assistant':
            text = ''.join(b.text for b in c if b.type == 'text')
            calls = [{'type': 'function', 'function': {'name': b.name, 'arguments': b.input}}
                     for b in c if b.type == 'tool_use']
            out.append({'role': 'assistant', 'content': text, **({'tool_calls': calls} if calls else {})})
        else:                                           # 도구 결과 묶음
            for r in c:
                content = r['content']
                out.append({'role': 'tool', 'content': f'오류: {content}' if r.get('is_error') else content})
    return out


class QwenProvider:
    def __init__(self, adapter: str = config.QWEN_ADAPTER, server: str = config.QWEN_SERVER):
        from transformers import AutoTokenizer          # 토크나이저·채팅 템플릿만 (torch 불필요)

        path = Path(adapter)
        if not (path / 'tokenizer_config.json').exists():
            raise FileNotFoundError(f'어댑터 폴더가 없음: {path} (llm/.env의 QWEN_ADAPTER)')
        self.tok = AutoTokenizer.from_pretrained(path)
        self.client = httpx.AsyncClient(base_url=server, timeout=600)
        self.ids = count(1)
        self._system = None

    async def _generate(self, messages: list[dict]) -> tuple[str, bool]:
        prompt = self.tok.apply_chat_template(messages, tokenize=False, tools=None,
                                              add_generation_prompt=True, enable_thinking=False)
        n = len(self.tok(prompt, add_special_tokens=False).input_ids)
        room = config.QWEN_MAX_SEQ - n
        if room < config.QWEN_MIN_ROOM:         # 도구 호출 하나(샘플 6마리면 약 500토큰)도 못 쓸 만큼 차면 멈춤
            raise ValueError('대화가 길어져 더 이어 갈 수 없어요. 새 대화에서 질문을 나눠서 물어봐 주세요.')
        t = time.time()
        r = await self.client.post('/completion', json={
            'prompt': prompt, 'n_predict': min(config.QWEN_MAX_NEW_TOKENS, room), 'temperature': 0,
            'stop': ['<|im_end|>', '<|endoftext|>'], 'cache_prompt': True,
            **({'grammar': GRAMMAR} if config.QWEN_GRAMMAR else {})})
        r.raise_for_status()
        out = r.json()
        log.info('qwen 입력 %d토큰 → 출력 %d토큰, %.1f초', n, out.get('tokens_predicted', 0), time.time() - t)
        return out['content'], out.get('stop_type') == 'limit'

    async def turn(self, system: str, messages: list, tools: list):
        if self._system is None:                        # 학습과 같은 요약 시스템 프롬프트 + 도구 목록
            self._system = system_prompt(system, tools)
        try:
            raw, cut = await self._generate(prepare_messages(to_training_format(messages), self._system))
        except ValueError as e:
            yield 'text', str(e)
            yield 'final', NS(content=[NS(type='text', text=str(e))], stop_reason='end_turn')
            return
        except httpx.HTTPError as e:
            log.warning('llama-server 오류: %s', e)
            msg = f'로컬 모델 서버(llama-server, {config.QWEN_SERVER})에 연결하지 못했습니다.'
            yield 'text', msg
            yield 'final', NS(content=[NS(type='text', text=msg)], stop_reason='end_turn')
            return
        reply = clean(raw)
        if '<tool_call>' in reply:              # 길이 제한에 걸려 닫히지 않은 도구 호출: 원문을 답으로 보여 주지 않음
            reply = '답변이 길어져 중간에 끊겼어요. 질문을 나눠서 다시 물어봐 주세요.'
        blocks = [NS(type='text', text=reply)] if reply else []
        if reply:
            yield 'text', reply
        blocks += [NS(type='tool_use', id=f'q{next(self.ids)}', name=n, input=a) for n, a in parse_calls(raw)]
        has_calls = any(b.type == 'tool_use' for b in blocks)
        stop = 'max_tokens' if cut else 'tool_use' if has_calls else 'end_turn'
        yield 'final', NS(content=blocks, stop_reason=stop)
