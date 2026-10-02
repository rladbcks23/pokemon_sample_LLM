"""에이전트 루프·도구·SSE 서버 테스트. 모델과 back API는 가짜로 (API 키·DB 없이 돈다).

    cd llm && ../.venv/bin/python -m unittest
"""
import asyncio
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from agent.loop import build_messages, run_agent
from agent.tools import Tools
from server import app as server

POKEMON = {'ruleset': 'champions_mc', 'format': 'singles', 'items': [
    {'id': 'garchomp', 'name': 'Garchomp', 'name_ko': '한카리아스', 'types': ['Dragon', 'Ground'],
     'stats': {'hp': 108, 'atk': 130, 'def': 95, 'spa': 80, 'spd': 85, 'spe': 102}, 'rank': 3,
     'megas': [{'id': 'garchompmega', 'name_ko': '메가한카리아스', 'types': ['Dragon', 'Ground'],
                'stats': {}, 'item': 'garchompite'}]},
    {'id': 'gyarados', 'name': 'Gyarados', 'name_ko': '갸라도스', 'types': ['Water', 'Flying'],
     'stats': {}, 'rank': 10,
     'megas': [{'id': 'gyaradosmega', 'name_ko': '메가갸라도스', 'types': ['Water', 'Dark'],
                'stats': {}, 'item': 'gyaradosite'}]},
]}
CHART = {  # 공격 → 방어 → 배율 (테스트에 필요한 것만)
    'Ice': {'Dragon': 2, 'Ground': 2, 'Flying': 2},
    'Electric': {'Ground': 0, 'Water': 2, 'Flying': 2},
    'Fighting': {'Dark': 2},
}
OPTIONS = {'typechart': CHART, 'types': [{'id': 'Ice', 'name_ko': '얼음'}, {'id': 'Electric', 'name_ko': '전기'},
                                         {'id': 'Fighting', 'name_ko': '격투'}]}


def back(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == '/api/pokemon/':
        return httpx.Response(200, json=POKEMON)
    if path == '/api/options/':
        return httpx.Response(200, json=OPTIONS)
    if path == '/api/pokemon/nope/':
        return httpx.Response(404, json={'detail': 'nope: 이 레귤레이션에 없는 포켓몬'})
    if path == '/api/validate/':
        body = json.loads(request.content)
        bad = 'splash' in body.get('moves', [])
        return httpx.Response(200, json={'valid': not bad, 'stats': {}, 'checks': [
            {'level': 'error', 'message': '배울 수 없는 기술: 튀어오르기'} if bad else {'level': 'ok', 'message': 'ok'}]})
    return httpx.Response(500)


def client():
    return httpx.AsyncClient(transport=httpx.MockTransport(back), base_url='http://back/api/')


def msg(*blocks, stop='end_turn'):
    return NS(content=list(blocks), stop_reason=stop)


def text(t):
    return NS(type='text', text=t)


def use(id, name, input):
    return NS(type='tool_use', id=id, name=name, input=input)


class FakeProvider:
    """정해 둔 응답을 차례로 돌려주고, 받은 메시지를 기록한다."""

    def __init__(self, *finals):
        self.finals = list(finals)
        self.calls = []

    async def turn(self, system, messages, tools):
        self.calls.append(json.loads(json.dumps(messages, default=lambda o: o.__dict__)))
        final = self.finals.pop(0)
        for b in final.content:
            if b.type == 'text':
                yield 'text', b.text
        yield 'final', final


SAMPLE = {'pokemon': 'garchomp', 'item': 'garchompite', 'ability': 'roughskin', 'nature': 'jolly',
          'sp': {'atk': 32, 'spe': 32, 'hp': 2}, 'moves': ['earthquake', 'dragonclaw', 'swordsdance', 'protect']}


def collect(provider, messages, format='singles'):
    async def go():
        async with client() as c:
            return [e async for e in run_agent(provider, Tools(c, format), messages)]
    return asyncio.run(go())


class BuildMessagesTest(unittest.TestCase):
    def test_drops_greeting_and_adds_screen(self):
        msgs = build_messages([{'role': 'assistant', 'text': '안녕하세요'}, {'role': 'user', 'text': '약점 알려줘'}],
                              'doubles', [SAMPLE, None])
        self.assertEqual(len(msgs), 1)
        self.assertIn('더블', msgs[0]['content'])
        self.assertIn('garchompite', msgs[0]['content'])
        self.assertTrue(msgs[0]['content'].endswith('약점 알려줘'))

    def test_last_must_be_user(self):
        with self.assertRaises(ValueError):
            build_messages([{'role': 'user', 'text': 'a'}, {'role': 'assistant', 'text': 'b'}], 'singles', [])


class LoopTest(unittest.TestCase):
    def test_tool_round_trip(self):
        p = FakeProvider(msg(use('t1', 'search_pokemon', {'query': '갸라'}), stop='tool_use'), msg(text('갸라도스는 10위')))
        events = collect(p, [{'role': 'user', 'content': '갸라도스 순위'}])
        self.assertEqual(events, [('status', '포켓몬 찾는 중'), ('text', '갸라도스는 10위')])
        result = p.calls[1][-1]['content'][0]
        self.assertEqual(result['tool_use_id'], 't1')
        self.assertIn('gyaradosmega', result['content'])

    def test_tool_error_goes_back_to_model(self):
        p = FakeProvider(msg(use('t1', 'get_pokemon', {'id': 'nope'}), stop='tool_use'), msg(text('없음')))
        collect(p, [{'role': 'user', 'content': '?'}])
        result = p.calls[1][-1]['content'][0]
        self.assertTrue(result['is_error'])
        self.assertIn('없는 포켓몬', result['content'])

    def test_back_down(self):
        async def go():
            down = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError('x'))),
                                     base_url='http://back/api/')
            p = FakeProvider(msg(use('t1', 'get_ranking', {}), stop='tool_use'), msg(text('죄송')))
            async with down:
                [e async for e in run_agent(p, Tools(down), [{'role': 'user', 'content': '?'}])]
            return p.calls[1][-1]['content'][0]
        result = asyncio.run(go())
        self.assertTrue(result['is_error'])
        self.assertIn('back API', result['content'])

    def test_analyze_party_uses_mega_types(self):
        async def go():
            async with client() as c:
                return await Tools(c).run('analyze_party', {'members': [
                    {'pokemon': 'garchomp', 'item': 'lifeorb'}, {'pokemon': 'gyarados', 'item': 'gyaradosite'}]})
        out = asyncio.run(go())
        self.assertEqual(out['members'][1]['name_ko'], '메가갸라도스')
        self.assertEqual(out['by_attack_type']['얼음']['weak'], 1)       # 한카리아스 ×4, 메가갸라도스는 비행이 빠짐
        self.assertEqual(out['by_attack_type']['전기'], {'weak': 1, 'resist': 0, 'immune': 1})
        self.assertIn('얼음×4', out['members'][0]['weak_to'])

    def test_propose_party_only_when_legal(self):
        bad = {**SAMPLE, 'moves': ['splash', 'earthquake', 'protect', 'roar']}
        p = FakeProvider(
            msg(use('t1', 'propose_party', {'members': [bad]}), stop='tool_use'),
            msg(use('t2', 'propose_party', {'members': [SAMPLE]}), stop='tool_use'),
            msg(text('이 파티 어때요')),
        )
        events = collect(p, [{'role': 'user', 'content': '추천해줘'}])
        first = json.loads(p.calls[1][-1]['content'][0]['content'])
        self.assertFalse(first['shown'])
        parties = [v for k, v in events if k == 'party']
        self.assertEqual(len(parties), 1)
        self.assertEqual(parties[0][0]['moves'], SAMPLE['moves'])
        self.assertEqual(parties[0][0]['sp'], {'hp': 2, 'atk': 32, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 32})

    def test_refusal(self):
        events = collect(FakeProvider(msg(stop='refusal')), [{'role': 'user', 'content': '?'}])
        self.assertEqual(events[-1][0], 'error')

    def test_round_limit(self):
        loops = [msg(use(f't{i}', 'get_ranking', {}), stop='tool_use') for i in range(20)]
        with patch('config.MAX_TOOL_ROUNDS', 3):
            events = collect(FakeProvider(*loops), [{'role': 'user', 'content': '?'}])
        self.assertEqual(events[-1][0], 'error')
        self.assertEqual(sum(k == 'status' for k, _ in events), 3)


class ServerTest(unittest.TestCase):
    def test_chat_streams_sse(self):
        p = FakeProvider(msg(use('t1', 'search_pokemon', {'query': '한카'}), stop='tool_use'), msg(text('한카리아스!')))
        with patch.object(server, 'get_provider', lambda: p), patch.object(server, 'back_client', client):
            r = TestClient(server.app).post('/llm/chat', json={
                'history': [{'role': 'user', 'text': '한카 어때'}], 'format': 'doubles', 'party': []})
        self.assertEqual(r.status_code, 200)
        events = [b.split('\n') for b in r.text.strip().split('\n\n')]
        kinds = [e[0].removeprefix('event: ') for e in events]
        self.assertEqual(kinds, ['status', 'text', 'done'])
        self.assertEqual(json.loads(events[1][1].removeprefix('data: ')), {'delta': '한카리아스!'})
        self.assertIn('더블', p.calls[0][0]['content'])

    def test_bad_history(self):
        r = TestClient(server.app).post('/llm/chat', json={'history': []})
        self.assertIn('event: error', r.text)


if __name__ == '__main__':
    unittest.main()
