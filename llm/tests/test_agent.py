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
from agent.tools import ToolError, Tools
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


def back(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == '/api/pokemon/':
        return httpx.Response(200, json=POKEMON)
    if path == '/api/samples/':      # size만큼만 돌려줌
        member = {'pokemon': {'name_ko': '한카리아스'}, 'item': {'name_ko': '생명의구슬'}, 'ability': {'name_ko': '까칠한피부'},
                  'nature': {'name_ko': '명랑'}, 'sp': {'hp': 2, 'atk': 32, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 32},
                  'moves': [{'name_ko': '지진'}, None]}
        sample = {**SAMPLE, 'sp': member['sp']}
        n = int(request.url.params['size'])
        return httpx.Response(200, json={'shapes': {'total': n, '물리 딜러': n}, 'results': [
            {'name': f'샘플{i}', 'source_label': 'OP.GG 샘플', 'sample': sample, 'member': member, 'roles': ['물리 딜러']}
            for i in range(n)]})
    if path == '/api/partners/':
        return httpx.Response(200, json={'teams': 3, 'with': request.url.params['pokemon'].split(','), 'partners': []})
    if path == '/api/party/check/':
        if not json.loads(request.content).get('members'):
            return httpx.Response(400, json={'members': '멤버가 비어 있음'})
        return httpx.Response(200, json={'members': [], 'summary': {}, 'warnings': []})
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

    def test_search_samples_short(self):
        async def go():
            async with client() as c:
                return await Tools(c).run('search_samples', {'pokemon': '한카'})
        out = asyncio.run(go())['samples']
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]['sample']['sp'], {'hp': 2, 'atk': 32, 'spe': 32})     # 0인 SP는 생략
        self.assertEqual(out[0]['readable'], '한카리아스 @ 생명의구슬 / 까칠한피부 / 명랑 / SP hp2 atk32 spe32 / 지진')

    def test_search_samples_guards(self):
        """이름 없이 부르거나 지어낸 이름이면 모델에게 고칠 방법을 알려 주는 오류."""
        async def go():
            async with client() as c:
                t = Tools(c)
                out = []
                for args in ({'role': '서포터'}, {'pokemon': '지코이르'}):
                    try:
                        await t.run('search_samples', args)
                    except ToolError as e:
                        out.append(str(e))
                return out
        missing, fake = asyncio.run(go())
        self.assertIn('get_ranking', missing)
        self.assertIn('목록에 없는 이름', fake)

    def test_search_samples_by_role(self):
        async def go():
            async with client() as c:
                t = Tools(c)
                return (await t.run('search_samples', {'pokemon': '한카', 'role': '물리 딜러'}),
                        await t.run('search_samples', {'pokemon': '한카', 'role': '막이'}))
        hit, miss = asyncio.run(go())
        self.assertEqual(hit['shapes'], {'total': 30, '물리 딜러': 30})      # role을 주면 30개를 받아 거름
        self.assertEqual(len(hit['samples']), 3)
        self.assertIn('막이 샘플 없음', miss[0]['result'])

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

    def test_propose_party_rejects_duplicates(self):
        async def go():
            async with client() as c:
                t = Tools(c)
                return await t.run('propose_party', {'members': [SAMPLE, {**SAMPLE, 'pokemon': 'gyarados'}]}), t.proposed
        out, proposed = asyncio.run(go())
        self.assertFalse(out['shown'])
        self.assertIsNone(proposed)
        self.assertIn('같은 도구 중복: garchompite', out['problems'][0]['errors'])

    def test_new_party_tools(self):
        async def go():
            async with client() as c:
                t = Tools(c, 'doubles')
                partners = await t.run('find_partners', {'pokemon': ['rillaboom', 'incineroar']})
                try:
                    await t.run('check_party', {'members': []})
                except ToolError as e:
                    return partners, str(e)
        partners, err = asyncio.run(go())
        self.assertEqual(partners['with'], ['rillaboom', 'incineroar'])
        self.assertIn('멤버가 비어 있음', err)        # back의 400은 모델에게 돌려줄 오류로

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
