"""back(Django)을 이 프로세스 안에서 부르는 httpx 클라이언트.

서버를 띄우지 않고 코치 도구(llm/agent/tools.py)를 실제 DB로 실행할 때 쓴다 (학습 데이터 생성, 노트북 채팅).
import하면 Django를 설정한다. 도구가 비동기라 Django의 비동기 안전 검사는 끈다 (이 용도 전용).

    from inproc_back import back_client
    async with back_client() as c:
        await Tools(c, 'doubles').run('search_pokemon', {'query': '한카리아스'})
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # 저장소 루트 (back, data, llm)
# back을 맨 앞에: llm/config.py가 back의 config 패키지(Django 설정)를 가리지 않게
for p in (ROOT / 'llm', ROOT / 'back'):
    if str(p) in sys.path:
        sys.path.remove(str(p))
    sys.path.insert(0, str(p))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

import django  # noqa: E402

django.setup()

import httpx  # noqa: E402
from django.test import Client  # noqa: E402

_dj = Client(HTTP_HOST='localhost')


def _handler(req: httpx.Request) -> httpx.Response:
    path = req.url.raw_path.decode()
    r = (_dj.post(path, data=req.content, content_type='application/json') if req.method == 'POST'
         else _dj.get(path))
    return httpx.Response(r.status_code, content=r.content, headers={'content-type': r.get('Content-Type', '')})


def back_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url='http://localhost/api/')
