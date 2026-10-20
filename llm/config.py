"""LLM 서버 설정. 값은 llm/.env (git에 올리지 않음) 또는 환경 변수에서 읽는다."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')

# back(Django) API 주소. 개발 중엔 runserver 기본 포트
BACK_URL = os.getenv('BACK_URL', 'http://localhost:8000/api/')

# 1단계 API 모델 (ANTHROPIC_API_KEY 필요)
LLM_MODEL = os.getenv('LLM_MODEL', 'claude-opus-5-5')
LLM_EFFORT = os.getenv('LLM_EFFORT', 'medium')        # low / medium / high / xhigh / max
LLM_MAX_TOKENS = int(os.getenv('LLM_MAX_TOKENS', '16000'))

# 모델 provider: claude (API 키 필요) / qwen (로컬 llama-server + 파인튜닝 어댑터의 토크나이저)
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'claude')
QWEN_ADAPTER = os.getenv('QWEN_ADAPTER', str(Path(__file__).resolve().parent / 'models/qwen35-4b-coach-lora'))
QWEN_SERVER = os.getenv('QWEN_SERVER', 'http://127.0.0.1:8080')   # llama-server (GGUF)
QWEN_MAX_SEQ = int(os.getenv('QWEN_MAX_SEQ', '4096'))  # 학습 길이와 같게
QWEN_MAX_NEW_TOKENS = int(os.getenv('QWEN_MAX_NEW_TOKENS', '1024'))
# 답변 글자를 한글·숫자·기호·영문 대문자로 제한 (외국어가 섞여서). 0이면 끔
QWEN_GRAMMAR = os.getenv('QWEN_GRAMMAR', '1') != '0'

# 한 번 답할 때 도구 호출을 주고받는 최대 횟수 (무한 루프 방지)
MAX_TOOL_ROUNDS = int(os.getenv('MAX_TOOL_ROUNDS', '8'))
