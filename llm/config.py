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

# 한 번 답할 때 도구 호출을 주고받는 최대 횟수 (무한 루프 방지)
MAX_TOOL_ROUNDS = int(os.getenv('MAX_TOOL_ROUNDS', '8'))
