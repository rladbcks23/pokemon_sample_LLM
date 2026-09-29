from datetime import date

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from apps.dex.models import Ruleset
from apps.meta.models import PokemonSet, Team, TeamMember, UsageDetail, UsageStat
from apps.meta.replay import match_species, parse_replay


class ConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rs = Ruleset.objects.create(id='champions_mc', name='Regulation M-C', showdown_mod='champions')
        cls.team = Team.objects.create(ruleset=cls.rs, format_key='champions_mc_doubles', source='user')

    def assertRejected(self, fn):
        with self.assertRaises(IntegrityError), transaction.atomic():
            fn()

    def test_valid_member(self):
        m = TeamMember.objects.create(team=self.team, slot=1, pokemon_key='garchomp',
                                      sp_hp=2, sp_atk=32, sp_spe=32, move1='earthquake')
        self.assertEqual(m.sp, '2/32/0/0/0/32')
        self.assertEqual(m.moves, ['earthquake'])

    def test_sp_per_stat_max(self):
        self.assertRejected(lambda: TeamMember.objects.create(team=self.team, slot=1, pokemon_key='x', sp_atk=33))

    def test_sp_total_max(self):
        self.assertRejected(lambda: TeamMember.objects.create(
            team=self.team, slot=1, pokemon_key='x', sp_hp=3, sp_atk=32, sp_spe=32))

    def test_slot_range(self):
        self.assertRejected(lambda: TeamMember.objects.create(team=self.team, slot=7, pokemon_key='x'))

    def test_slot_unique(self):
        TeamMember.objects.create(team=self.team, slot=1, pokemon_key='a')
        self.assertRejected(lambda: TeamMember.objects.create(team=self.team, slot=1, pokemon_key='b'))

    def test_pokemon_set_sp_total(self):
        self.assertRejected(lambda: PokemonSet.objects.create(
            ruleset=self.rs, format_key='champions_mc_singles', pokemon_key='x', source='t',
            sp_hp=32, sp_def=32, sp_spd=3))

    def test_usage_snapshot_unique_and_kind(self):
        kw = dict(ruleset=self.rs, format_key='champions_mc_doubles', pokemon_key='garchomp',
                  source='opgg', season='m-6', snapshot_date=date(2026, 9, 29))
        u = UsageStat.objects.create(rank=9, **kw)
        UsageStat.objects.create(**{**kw, 'source': 'smogon'})   # 같은 날 다른 출처는 허용
        self.assertRejected(lambda: UsageStat.objects.create(**kw))
        UsageDetail.objects.create(usage_stat=u, kind='spread', target_key='2/32/0/0/0/32', pct=24.6)
        self.assertRejected(lambda: UsageDetail.objects.create(usage_stat=u, kind='mega', target_key='x', pct=1))


class ReplayParserTests(SimpleTestCase):
    LOG = '\n'.join([
        '|player|p1|Alice|1|1500', '|player|p2|Bob|2|1500',
        '|poke|p1|Garchomp, L50, M|', '|poke|p1|Incineroar, L50, M|', '|poke|p1|Basculegion-F, L50, F|',
        '|poke|p2|Kingambit, L50, M|', '|poke|p2|Rillaboom, L50, M|',
        '|showteam|p1|Garchomp||GarchompiteZ|RoughSkin|Earthquake,Protect|Jolly||M|||50|]'
        'Incineroar||SitrusBerry|Intimidate|FakeOut,Parting Shot|Careful||M|||50|',
        '|switch|p1a: Chomp|Garchomp, L50, M|100/100', '|switch|p2a: King|Kingambit, L50, M|100/100',
        '|turn|1',
        '|detailschange|p1a: Chomp|Garchomp-Mega-Z, L50, M', '|-mega|p1a: Chomp|Garchomp|Garchompite Z',
        '|switch|p1a: Cat|Incineroar, L50, M|100/100',
        '|win|Bob',
    ])

    def test_parse(self):
        p1, p2 = parse_replay(self.LOG)
        self.assertEqual((p1.player, p1.result, p2.result), ('Alice', 'lose', 'win'))
        self.assertEqual(p1.species, ['garchomp', 'incineroar', 'basculegionf'])
        self.assertEqual(p1.sets['garchomp'], {'item': 'garchompitez', 'ability': 'roughskin',
                                               'moves': ['earthquake', 'protect'], 'nature': 'jolly'})
        self.assertEqual(p1.lead, {'garchomp'})                     # 1턴 전 출전
        self.assertEqual(p1.brought, {'garchomp', 'incineroar'})
        self.assertEqual(p1.mega, {'garchomp'})
        self.assertFalse(p2.sets)                                   # 팀시트 없음

    def test_match_species(self):
        self.assertTrue(match_species('garchomp', {'garchompmegaz'}))   # 메가 후 이름
        self.assertFalse(match_species('incineroar', {'garchomp'}))
