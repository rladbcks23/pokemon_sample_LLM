"""로컬 Qwen3.5-4B + LoRA provider. ClaudeProvider와 같은 모양으로 turn()을 낸다.

학습과 같은 입력 표현(training/scripts/compact_context)으로 바꿔 생성하고,
Qwen 도구 호출(<tool_call><function=…>)을 Claude 형식 tool_use 블록으로 돌려준다.
torch 등은 이 provider를 쓸 때만 불러온다 (requirements-qwen.txt).
"""
import asyncio
import json
import re
import threading
from itertools import count
from pathlib import Path
from types import SimpleNamespace as NS

import config
from training.scripts.compact_context import prepare_messages, system_prompt

TOOL_CALL = re.compile(r'<tool_call>\s*<function=([\w-]+)>(.*?)</function>\s*</tool_call>', re.S)
PARAM = re.compile(r'<parameter=([\w-]+)>\n?(.*?)\n?</parameter>', re.S)
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


def clean(text: str) -> str:
    for pat in NOISE:
        text = re.sub(pat, '', text, flags=re.S)
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
    def __init__(self, adapter: str = config.QWEN_ADAPTER, base: str = config.QWEN_BASE):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

        path = Path(adapter)
        if not (path / 'adapter_config.json').exists():
            raise FileNotFoundError(f'어댑터가 없음: {path} (llm/.env의 QWEN_ADAPTER)')
        base = base or json.loads((path / 'adapter_config.json').read_text(encoding='utf-8'))['base_model_name_or_path']
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        # 기본 모델 설정에는 <|im_end|>가 종료로 없어서, 도구 호출 뒤에도 결과를 지어내며 계속 씀
        self.stop = self.tok.convert_tokens_to_ids(['<|im_end|>', '<|endoftext|>'])
        quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                   bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        model = AutoModelForImageTextToText.from_pretrained(base, quantization_config=quant, device_map='cuda',
                                                            dtype=torch.bfloat16)
        self.model = PeftModel.from_pretrained(model, path).eval()
        self.lock = threading.Lock()                    # GPU는 하나라 요청을 차례로
        self.ids = count(1)
        self._system = None

    def _generate(self, messages: list[dict]) -> tuple[str, bool]:
        text = self.tok.apply_chat_template(messages, tokenize=False, tools=None,
                                            add_generation_prompt=True, enable_thinking=False)
        ids = self.tok(text, add_special_tokens=False, return_tensors='pt').to(self.model.device)
        n = ids['input_ids'].shape[1]
        room = config.QWEN_MAX_SEQ - n
        if room < 80:
            raise ValueError('대화 문맥이 가득 찼습니다. 새 대화에서 질문을 이어 주세요.')
        limit = min(config.QWEN_MAX_NEW_TOKENS, room)
        with self.lock, self.torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=limit, do_sample=False, use_cache=True,
                                      eos_token_id=self.stop, pad_token_id=self.stop[0])
        new = out[0][n:]
        return self.tok.decode(new, skip_special_tokens=False), len(new) >= limit

    async def turn(self, system: str, messages: list, tools: list):
        if self._system is None:                        # 학습과 같은 요약 시스템 프롬프트 + 도구 목록
            self._system = system_prompt(system, tools)
        try:
            raw, cut = await asyncio.to_thread(self._generate, prepare_messages(to_training_format(messages), self._system))
        except ValueError as e:
            yield 'text', str(e)
            yield 'final', NS(content=[NS(type='text', text=str(e))], stop_reason='end_turn')
            return
        reply = clean(raw)
        blocks = [NS(type='text', text=reply)] if reply else []
        if reply:
            yield 'text', reply
        blocks += [NS(type='tool_use', id=f'q{next(self.ids)}', name=n, input=a) for n, a in parse_calls(raw)]
        has_calls = any(b.type == 'tool_use' for b in blocks)
        stop = 'max_tokens' if cut else 'tool_use' if has_calls else 'end_turn'
        yield 'final', NS(content=blocks, stop_reason=stop)
