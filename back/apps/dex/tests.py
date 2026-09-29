from django.test import SimpleTestCase

from apps.dex.ids import DexIndex, opgg_item_id, opgg_pokemon_id, to_id


def entry(name, base, forme='', is_mega=False):
    return {'showdown_id': to_id(name), 'name': name, 'base_species': base, 'forme': forme, 'is_mega': is_mega}


class IdTests(SimpleTestCase):
    def setUp(self):
        rows = [
            entry('Garchomp', 'Garchomp'), entry('Garchomp-Mega', 'Garchomp', 'Mega', True),
            entry('Garchomp-Mega-Z', 'Garchomp', 'Mega-Z', True),
            entry('Lycanroc', 'Lycanroc'), entry('Lycanroc-Midnight', 'Lycanroc', 'Midnight'),
            entry('Squawkabilly', 'Squawkabilly'), entry('Squawkabilly-Blue', 'Squawkabilly', 'Blue'),
            entry('Indeedee', 'Indeedee'), entry('Indeedee-F', 'Indeedee', 'F'),
            entry('Ninetales-Alola', 'Ninetales', 'Alola'), entry('Vivillon', 'Vivillon'),
        ]
        self.dex = DexIndex(pokemon={r['showdown_id']: r for r in rows})

    def test_to_id(self):
        self.assertEqual(to_id('Garchomp-Mega-Z'), 'garchompmegaz')
        self.assertEqual(to_id("King's Rock"), 'kingsrock')
        self.assertEqual(to_id(None), '')

    def test_opgg_pokemon(self):
        cases = {
            'mega-garchomp-z': 'garchompmegaz',
            'mega-garchomp': 'garchompmega',
            'lycanroc-midday': 'lycanroc',             # 기본 폼 이름이 붙은 경우
            'lycanroc-midnight': 'lycanrocmidnight',
            'squawkabilly-green-plumage': 'squawkabilly',
            'squawkabilly-blue-plumage': 'squawkabillyblue',
            'indeedee-male': 'indeedee',
            'indeedee-female': 'indeedeef',
            'ninetales-alolan': 'ninetalesalola',
            'mega-meowstic': 'meowsticmmega',          # 수동 매핑
        }
        for key, expected in cases.items():
            self.assertEqual(opgg_pokemon_id(key, self.dex), expected, key)

    def test_opgg_item(self):
        self.assertEqual(opgg_item_id('life-orb'), 'lifeorb')
        self.assertEqual(opgg_item_id('garchompite-z'), 'garchompitez')
        self.assertEqual(opgg_item_id('staraptorite'), 'staraptite')   # 메가스톤 이름 차이

    def test_base_and_cosmetic(self):
        self.assertEqual(self.dex.base_id('garchompmegaz'), 'garchomp')
        self.assertEqual(self.dex.base_id('garchomp'), 'garchomp')
        self.assertTrue(self.dex.is_mega('garchompmega'))
        self.assertEqual(self.dex.resolve_cosmetic('vivillonhighplains'), 'vivillon')
