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
            'squawkabilly-blue-plumage': 'squawkabilly',   # 블루는 그린과 합침
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


class StatTests(SimpleTestCase):
    def test_reference_values(self):
        # 참고 이미지: 종족 75/150/175/70/120/40, SP 32/32/0/0/2/0, 공격↑ 특공↓ → 182/222/195/81/142/60
        from apps.dex.stats import calc_stats
        base = {'hp': 75, 'atk': 150, 'def': 175, 'spa': 70, 'spd': 120, 'spe': 40}
        sp = dict(hp=32, atk=32, spd=2)
        self.assertEqual(calc_stats(base, sp, plus='atk', minus='spa'),
                         {'hp': 182, 'atk': 222, 'def': 195, 'spa': 81, 'spd': 142, 'spe': 60})

    def test_sp_problems(self):
        from apps.dex.stats import sp_problems
        self.assertEqual(sp_problems({'hp': 32, 'atk': 32, 'spe': 2}), [])
        self.assertEqual(len(sp_problems({'hp': 33})), 1)
        self.assertEqual(len(sp_problems({'hp': 32, 'atk': 32, 'spe': 3})), 1)


class MergedFormTests(SimpleTestCase):
    def test_maushold_merged_into_four(self):
        dex = DexIndex(pokemon={'mausholdfour': entry('Maushold-Four', 'Maushold', 'Four')})
        self.assertEqual(opgg_pokemon_id('maushold-family-of-four', dex), 'mausholdfour')
        self.assertEqual(opgg_pokemon_id('maushold-family-of-three', dex), 'mausholdfour')
        self.assertEqual(dex.resolve_cosmetic('maushold'), 'mausholdfour')   # 리플레이의 세식구 표기
        self.assertEqual(dex.resolve_cosmetic('mausholdfour'), 'mausholdfour')

    def test_same_stat_forms_merged(self):
        dex = DexIndex(pokemon={
            'squawkabilly': entry('Squawkabilly', 'Squawkabilly', ''),
            'squawkabillyyellow': entry('Squawkabilly-Yellow', 'Squawkabilly', 'Yellow'),
            'sinistcha': entry('Sinistcha', 'Sinistcha', ''),
        })
        self.assertEqual(opgg_pokemon_id('squawkabilly-blue-plumage', dex), 'squawkabilly')
        self.assertEqual(opgg_pokemon_id('squawkabilly-white-plumage', dex), 'squawkabillyyellow')
        self.assertEqual(opgg_pokemon_id('sinistcha-masterpiece', dex), 'sinistcha')
        self.assertEqual(dex.resolve_cosmetic('squawkabillywhite'), 'squawkabillyyellow')
        self.assertEqual(dex.resolve_cosmetic('sinistchamasterpiece'), 'sinistcha')


class MegaBaseTests(SimpleTestCase):
    def test_mega_base_form(self):
        dex = DexIndex(pokemon={
            'floetteeternal': entry('Floette-Eternal', 'Floette', 'Eternal'),
            'floettemega': entry('Floette-Mega', 'Floette', 'Mega', True),
            'meowstic': entry('Meowstic', 'Meowstic', ''),
            'meowsticf': entry('Meowstic-F', 'Meowstic', 'F'),
            'meowsticfmega': entry('Meowstic-F-Mega', 'Meowstic', 'F-Mega', True),
            'garchompmega': entry('Garchomp-Mega', 'Garchomp', 'Mega', True),
            'garchomp': entry('Garchomp', 'Garchomp', ''),
        })
        self.assertEqual(dex.base_id('floettemega'), 'floetteeternal')   # 기본 폼이 없는 포켓몬
        self.assertEqual(dex.base_id('meowsticfmega'), 'meowsticf')
        self.assertEqual(dex.base_id('garchompmega'), 'garchomp')
        self.assertEqual(dex.base_id('garchomp'), 'garchomp')

