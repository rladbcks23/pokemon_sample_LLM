"""도구 결과로 답 문장 만들기 (agent/answers.py). 도구 결과 모양은 agent/tools.py와 같게."""
import asyncio
import unittest
from types import SimpleNamespace as NS

from agent import answers
from agent.loop import run_agent

G = {'pokemon': 'garchomp', 'item': 'choicescarf', 'ability': 'roughskin', 'nature': 'adamant',
     'sp': {'hp': 2, 'atk': 32, 'spe': 32}, 'moves': ['earthquake', 'dragonclaw', 'rockslide', 'stompingtantrum']}
P = {**G, 'pokemon': 'primarina', 'item': 'sitrusberry', 'sp': {'hp': 32, 'spa': 31, 'spe': 3}}
SEARCH = ('search_samples', {'pokemon': '한카리아스'}, {
    'shapes': {'total': 173, '물리 딜러': 57},
    'samples': [{'source': 'OP.GG 샘플', 'roles': ['물리 딜러'], 'sample': G,
                 'readable': '한카리아스 @ 구애스카프 / 까칠한피부 / 고집 / SP hp2 atk32 spe32 / 지진'}]})
CHECK = ('check_party', {'members': [G, P]}, {
    'members': [{'pokemon': 'garchomp', 'name_ko': '한카리아스', 'roles': ['물리 딜러'], 'sp': 'H2 A32 S32'},
                {'pokemon': 'primarina', 'name_ko': '누리레느', 'roles': ['특수 딜러'], 'sp': 'H32 C31 S3'}],
    'summary': {'roles': {'물리 딜러': 1, '특수 딜러': 1}, 'mega_pokemon': 0,
                'weak_types_2plus': {'얼음': ['한카리아스', '누리레느'], '땅': ['한카리아스', '누리레느', '타부자고']},
                'weak_cover': {'얼음': [], '땅': ['고릴타']}},
    'warnings': []})


class RenderTest(unittest.TestCase):
    def test_sample(self):
        text = answers.render('한카리아스 샘플 짜줘', [SEARCH, ('propose_party', {'members': [G]}, {'shown': True})], 'singles')
        self.assertTrue(text.startswith('한카리아스 @ 구애스카프 (H2 A32 S32) 추천 (화면에 띄움).'))
        self.assertIn('OP.GG 공개 샘플이고, SP·기술 기준 역할은 물리 딜러예요.', text)
        self.assertIn('한카리아스 샘플 173개 중 물리 딜러형이 57개예요.', text)

    def test_party_from_team(self):
        team = ('get_team', {'id': 1}, {'id': 1, 'title': 'ふゆばれ', 'members': [
            {'sample': G, 'name': '한카리아스 @ 구애스카프 / 까칠한피부'}, {'sample': P, 'name': '누리레느 @ 자뭉열매 / 촉촉보이스'}]})
        text = answers.render('파티 짜줘', [team, CHECK, ('propose_party', {'members': [G, P]}, {'shown': True})], 'doubles')
        self.assertTrue(text.startswith('상위 파티를 바탕으로 짰어요 (화면에 띄움).'))      # 일본어 팀 이름은 빼고
        self.assertIn('- 누리레느 @ 자뭉열매 (H32 C31 S3)', text)
        self.assertIn('구성: 물리 딜러 1·특수 딜러 1', text)

    def test_party_names_from_check(self):
        """검색 결과에 없는 화면 멤버도 영문 ID가 아니라 check_party의 한글 이름으로."""
        text = answers.render('얘랑 어울리는 포켓몬', [CHECK, ('propose_party', {'members': [G, P]}, {'shown': True})], 'singles')
        self.assertIn('- 한카리아스 (H2 A32 S32)', text)
        self.assertNotIn('garchomp', text)

    def test_weakness(self):
        text = answers.render('이 파티 약점 알려줘', [CHECK], 'singles')
        self.assertIn('- 땅 3마리: 한카리아스·누리레느·타부자고 / 받아 줄 멤버: 고릴타', text)
        self.assertIn('- 얼음 2마리: 한카리아스·누리레느 / 받아 줄 멤버 없음', text)
        self.assertIn('땅 약점이 3마리로 가장 많아요', text)

    def test_item_usage(self):
        info = ('get_pokemon', {'id': 'garchomp'}, {'name_ko': '한카리아스', 'usage': {'item': [
            {'id': 'lifeorb', 'name_ko': '생명의구슬', 'pct': 34.3}, {'id': 'choicescarf', 'name_ko': '구애스카프', 'pct': 17.9}]}})
        text = answers.render('생명의구슬 말고 다른거는 안써?', [info], 'singles')
        self.assertIn('싱글 한카리아스 도구 사용률: 생명의구슬 34.3% · 구애스카프 17.9%', text)

    def test_no_sample(self):
        none = [{'result': '깜까미 울퉁불퉁멧 샘플 없음', 'none': {'pokemon': '깜까미', 'item': '울퉁불퉁멧', 'role': None}}]
        text = answers.render('울퉁불퉁멧 형태', [('search_samples', {'pokemon': 'sableye'}, none)], 'singles')
        self.assertTrue(text.startswith('깜까미는 울퉁불퉁멧 공개 샘플이 없어요.'))

    def test_unknown_flow_keeps_model_text(self):
        self.assertIsNone(answers.render('ㅁㄴㅇㄹ', [], 'singles'))
        self.assertIsNone(answers.render('승률 몇 퍼야?', [('get_ranking', {}, {'items': []})], 'singles'))


class Rendering:
    """도구를 한 번 부르고 엉뚱한 글을 쓰는 가짜 모델."""
    render_answers = True

    def __init__(self, calls):
        self.calls = list(calls)

    async def turn(self, system, messages, tools):
        if self.calls:
            name, args = self.calls.pop(0)
            yield 'final', NS(content=[NS(type='tool_use', id='t1', name=name, input=args)], stop_reason='tool_use')
        else:
            yield 'text', '지어낸 숫자 17/37 ...'
            yield 'final', NS(content=[NS(type='text', text='지어낸 숫자')], stop_reason='end_turn')


class FakeTools:
    format = 'singles'

    async def run(self, name, args):
        return CHECK[2]


class LoopRenderTest(unittest.TestCase):
    def test_model_text_replaced(self):
        async def go():
            msgs = [{'role': 'user', 'content': '[화면] …\n\n이 파티 약점 알려줘'}]
            return [e async for e in run_agent(Rendering([('check_party', {'members': [G, P]})]), FakeTools(), msgs)]
        events = asyncio.run(go())
        text = ''.join(v for k, v in events if k == 'text')
        self.assertNotIn('17/37', text)
        self.assertIn('땅 3마리', text)


class SampleTools:
    """search_samples 인자를 기록하고, propose_party는 띄운 것으로."""
    format = 'singles'

    def __init__(self):
        self.args, self.proposed = [], None

    subject = None

    async def item_in(self, question):
        return 'rockyhelmet' if '울퉁불퉁멧' in question else None

    async def item_id(self, text):
        return 'lightclay' if text == '빛의점토' else None

    async def pokemon_in(self, question):
        return '깜까미' in question

    async def run(self, name, args):
        self.args.append((name, args))
        if name == 'search_samples':
            return {'shapes': {'total': 10, '물리막이': 4}, 'samples': [{
                'source': 'OP.GG 샘플', 'roles': ['물리막이'], 'sample': {**G, 'pokemon': 'sableye', 'item': 'rockyhelmet'},
                'readable': '깜까미 @ 울퉁불퉁멧 / 짓궂은마음'}]}
        self.proposed = args['members']
        return {'shown': True, 'count': 1}


class SubjectTest(unittest.TestCase):
    def test_subject_from_card_or_name(self):
        from agent.loop import subject_of
        party = [G, {**P, 'pokemon': 'sableye'}]
        names = ['한카리아스', '깜까미']
        h = [{'role': 'user', 'text': '깜까미 아이템 바꾸고 싶어'}, {'role': 'assistant', 'text': '…'},
             {'role': 'user', 'text': '울퉁불퉁멧 형태'}]
        self.assertEqual(subject_of(h, party, names), 'sableye')
        h2 = [{'role': 'assistant', 'text': '…', 'party': [P]}, {'role': 'user', 'text': '울퉁불퉁멧 형태'}]
        self.assertEqual(subject_of(h2, party, names), 'primarina')      # 바로 앞 카드가 우선
        self.assertIsNone(subject_of([{'role': 'user', 'text': '파티 짜줘'}], party, names))


class ItemFlowTest(unittest.TestCase):
    def test_item_filled_and_sample_shown(self):
        """모델이 item을 빼먹고 띄우지도 않아도: 질문의 도구로 거르고, 서버가 띄우고, 도구 결과로 답."""
        tools = SampleTools()

        async def go():
            msgs = [{'role': 'user', 'content': '[화면] …\n\n울퉁불퉁멧 형태'}]
            return [e async for e in run_agent(Rendering([('search_samples', {'pokemon': '깜까미'})]), tools, msgs)]
        events = asyncio.run(go())
        self.assertEqual(tools.args[0], ('search_samples', {'pokemon': '깜까미', 'item': 'rockyhelmet'}))
        self.assertEqual(tools.args[1][0], 'propose_party')
        self.assertTrue(any(k == 'party' for k, _ in events))
        text = ''.join(v for k, v in events if k == 'text')
        self.assertTrue(text.startswith('깜까미 @ 울퉁불퉁멧'))
        self.assertNotIn('17/37', text)

    def test_subject_replaces_wrong_pokemon(self):
        """질문에 포켓몬 이름이 없으면 지어낸 이름·도구 이름 대신 지금 이야기 중인 포켓몬으로."""
        for wrong, want in [({'pokemon': 'blinkous', 'item': 'lightclay'}, {'pokemon': 'sableye', 'item': 'lightclay'}),
                            ({'pokemon': '빛의점토'}, {'pokemon': 'sableye', 'item': '빛의점토'})]:
            tools = SampleTools()
            tools.subject = 'sableye'

            async def go():
                msgs = [{'role': 'user', 'content': '[화면] …\n\n빛의점토 형태'}]
                return [e async for e in run_agent(Rendering([('search_samples', wrong)]), tools, msgs)]
            asyncio.run(go())
            self.assertEqual(tools.args[0], ('search_samples', want))


if __name__ == '__main__':
    unittest.main()
