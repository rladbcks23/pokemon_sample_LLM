"""질문 → 의도 JSON (agent/intents.parse, 규칙). 도구는 이름 찾기만 흉내 낸다."""
import asyncio
import unittest

from agent import intents

POKEMON = {'한카리아스': ('garchomp', None), '메가한카리아스Z': ('garchomp', 'garchompitez'), '깜까미': ('sableye', None),
           '포푸니크': ('sneasler', None)}
ITEMS = {'울퉁불퉁멧': 'rockyhelmet', '생명의구슬': 'lifeorb'}
MOVES = {'빛의장막': 'lightscreen', '리플렉터': 'reflect', '인파이트': 'closecombat'}


class FakeTools:
    format = 'singles'

    async def find_pokemon(self, text):
        hits = [n for n in POKEMON if n in (text or '').replace(' ', '')]
        if not hits:
            return None
        n = max(hits, key=len)
        return {'id': POKEMON[n][0], 'stone': POKEMON[n][1], 'name_ko': n}

    async def item_in(self, q):
        if '말고' in q:
            return None
        return next((v for k, v in ITEMS.items() if k in q), None)

    async def moves_without(self, q):
        return [k for k in MOVES if k in q] if ('없는' in q or '빼고' in q) else []

    async def move_id(self, text):
        return MOVES.get(text, text)

    async def _get(self, path, params=None, cache=False):
        return {'items': [{'id': 'garchomp', 'megas': [{'item': 'garchompitez'}]}]}


def parse(q, history=()):
    return asyncio.run(intents.parse(q, list(history), FakeTools()))


class ParseTest(unittest.TestCase):
    def test_sample_and_mega(self):
        self.assertEqual(parse('메가한카리아스Z 샘플 짜줘'),
                         {'intent': 'sample', 'pokemon': 'garchomp', 'stone': 'garchompitez'})

    def test_pointer_uses_previous_conversation(self):
        prev = [{'role': 'user', 'text': '포푸니크 샘플 짜줘'},
                {'role': 'assistant', 'text': '…', 'party': [{'pokemon': 'sneasler', 'item': 'focussash'}]}]
        self.assertEqual(parse('걔 울퉁불퉁멧으로', prev),
                         {'intent': 'sample', 'pokemon': 'sneasler', 'stone': None, 'item': 'rockyhelmet'})
        self.assertEqual(parse('인파이트 없는 건?', prev)['without'], ['closecombat'])

    def test_pointer_without_previous_asks(self):
        self.assertEqual(parse('얘 샘플 보여줘'), {'intent': 'unknown', 'reason': 'who'})

    def test_item_with_mega_target_uses_base_form(self):
        prev = [{'role': 'assistant', 'text': '…', 'party': [{'pokemon': 'garchomp', 'item': 'garchompitez'}]}]
        out = parse('울퉁불퉁멧 형태', prev)
        self.assertEqual((out['pokemon'], out['stone'], out['item']), ('garchomp', None, 'rockyhelmet'))

    def test_other_sample(self):
        prev = [{'role': 'user', 'text': '깜까미 샘플'}]
        self.assertTrue(parse('걔 다른 형태는?', prev)['other'])

    def test_screen_intents(self):
        self.assertEqual(parse('이 파티 약점 알려줘')['intent'], 'weakness')
        self.assertEqual(parse('이거 약점 찌르는 포켓몬 누가 있어?')['intent'], 'threats')
        self.assertEqual(parse('메가 누구한테 써?')['intent'], 'mega')
        self.assertEqual(parse('나머지 채워줘'), {'intent': 'fill', 'count': 'all'})
        self.assertEqual(parse('한 마리 더 추천해줘'), {'intent': 'fill', 'count': 1})

    def test_weather(self):
        self.assertEqual(parse('비파티인데'), {'intent': 'weakness', 'weather': 'rain'})
        self.assertEqual(parse('비를 뿌리면 불꽃이 반감이잖아'), {'intent': 'weakness', 'weather': 'rain'})
        self.assertEqual(parse('쾌청 파티야'), {'intent': 'weakness', 'weather': 'sun'})
        self.assertEqual(intents.party_weather([{'pokemon': 'sableye', 'moves': ['raindance', 'taunt']}]), 'rain')
        self.assertIsNone(intents.party_weather([{'pokemon': 'sableye', 'moves': ['taunt']}]))

    def test_threat_words(self):
        self.assertEqual(parse('이 파티 약점 포켓몬을 알려줘'), {'intent': 'threats'})
        self.assertEqual(parse('아니 내가 조심해야할 포켓몬이나 파티'), {'intent': 'threats', 'teams': True})
        self.assertEqual(parse('이 파티가 불리한 상대는?'), {'intent': 'threats'})

    def test_improve(self):
        self.assertEqual(parse('현재파티에서 빼고 넣을만한 포켓몬이 있나'), {'intent': 'improve'})
        self.assertEqual(parse('현재 파티에서 수정할만한거 있어?'), {'intent': 'improve'})
        self.assertEqual(parse('현재파티에서 수정이 필요한 포켓몬이 있어?'), {'intent': 'improve'})

    def test_model_only_when_rules_miss(self):
        calls = []

        async def classify(q, history, party_size):
            calls.append(q)
            return {'남은 두 자리 뭐 넣지': 'fill', '걔한테 뭐 들려': 'item_usage', '배고프다': 'off_topic'}.get(q, 'sample')

        def run(q, history=()):
            return asyncio.run(intents.parse(q, list(history), FakeTools(), classify=classify))

        self.assertEqual(run('이 파티 약점 알려줘'), {'intent': 'weakness'})     # 규칙이 알아들으면 모델 안 부름
        self.assertEqual(calls, [])
        self.assertEqual(run('남은 두 자리 뭐 넣지'), {'intent': 'fill', 'count': 'all', 'by': 'model'})
        prev = [{'role': 'user', 'text': '깜까미 샘플'}]
        self.assertEqual(run('걔한테 뭐 들려', prev), {'intent': 'item_usage', 'pokemon': 'sableye', 'by': 'model'})
        self.assertEqual(run('배고프다'), {'intent': 'unknown', 'reason': 'off_topic'})

    def test_weather_drops_halved_threats(self):
        from agent import answers
        th = {'checked_top': 40, 'need_hits': 3, 'threats': [
            {'name_ko': '어흥염', 'rank': 1, 'hits': 3, 'targets': ['고릴타←플레어드라이브 80%(불꽃 ×2)',
                                                                  '대도각참←플레어드라이브 80%(불꽃 ×2)', '깜까미←인파이트 20%(격투 ×2)']}]}
        self.assertEqual(answers.weather_threats(th, 'rain')['threats'], [])
        self.assertEqual(len(answers.weather_threats(th, None)['threats']), 1)

    def test_weather_halves_weakness(self):
        from agent import answers
        check = {'summary': {'weak_types_2plus': {'불꽃': ['고릴타', '대도각참', '메가갑주무사'], '얼음': ['고릴타', '메가망나뇽']},
                             'weak_cover': {'불꽃': ['메가망나뇽'], '얼음': ['대도각참']}}, 'warnings': []}
        self.assertEqual(answers.top_weak(check['summary'], 'rain')[0], '얼음')
        text = answers.weakness_answer(check, 'rain')
        self.assertIn('불꽃 기술 대미지가 반감', text)
        self.assertNotIn('불꽃 약점이 3마리로 가장 많아요', text)

    def test_party_and_format(self):
        self.assertEqual(parse('더블 파티 하나 짜줘'), {'format': 'doubles', 'intent': 'party'})
        self.assertEqual(parse('한카리아스랑 어울리는 파티 짜줘'), {'intent': 'party', 'pokemon': 'garchomp'})

    def test_item_usage(self):
        self.assertEqual(parse('깜까미 아이템 다른거 주고 싶은데'), {'intent': 'item_usage', 'pokemon': 'sableye'})

    def test_unknown(self):
        self.assertEqual(parse('이 파티 승률 몇 퍼야?'), {'intent': 'unknown', 'reason': 'cant'})
        self.assertEqual(parse('ㅁㄴㅇㄹ'), {'intent': 'unknown', 'reason': 'unclear'})
        self.assertEqual(parse('오늘 점심 뭐 먹지'), {'intent': 'unknown', 'reason': 'off_topic'})


if __name__ == '__main__':
    unittest.main()
