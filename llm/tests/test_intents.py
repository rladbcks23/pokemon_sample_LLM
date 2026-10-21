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
