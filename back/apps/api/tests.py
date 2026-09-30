from datetime import date

from rest_framework.test import APITestCase

from apps.api.common import names
from apps.dex.models import Ability, Item, Learnset, Move, Nature, Pokemon, PokemonAbility, Ruleset, TypeChart
from apps.dex.typechart import chart
from apps.meta.models import Team, TeamMember, UsageDetail, UsageStat


def mon(rs, sid, name, name_ko, types, stats, **kw):
    hp, atk, df, spa, spd, spe = stats
    return Pokemon.objects.create(
        ruleset=rs, showdown_id=sid, name=name, name_ko=name_ko, num=445, base_species=kw.pop('base', name),
        type1=types[0], type2=types[1] if len(types) > 1 else '', hp=hp, atk=atk, defense=df, spa=spa, spd=spd,
        spe=spe, bst=sum(stats), weight_kg=95, **kw)


class ApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        names.cache_clear()
        chart.cache_clear()
        rs = cls.rs = Ruleset.objects.create(id='champions_mc', name='Regulation M-C', showdown_mod='champions',
                                            start_date=date(2026, 9, 9))
        g = mon(rs, 'garchomp', 'Garchomp', '한카리아스', ['Dragon', 'Ground'], (108, 130, 95, 80, 85, 102))
        mon(rs, 'garchompmegaz', 'Garchomp-Mega-Z', '한카리아스-메가Z', ['Dragon'], (108, 130, 85, 141, 85, 151),
            base='Garchomp', forme='Mega-Z', is_mega=True, required_item='Garchompite Z')
        rough = Ability.objects.create(ruleset=rs, showdown_id='roughskin', name='Rough Skin', name_ko='까칠한피부')
        PokemonAbility.objects.create(pokemon=g, ability=rough, slot='H')
        eq = Move.objects.create(ruleset=rs, showdown_id='earthquake', name='Earthquake', name_ko='지진',
                                 type='Ground', category='Physical', power=100, accuracy=100, pp=10,
                                 target='allAdjacent')
        Learnset.objects.create(pokemon=g, move=eq)
        Item.objects.create(ruleset=rs, showdown_id='garchompitez', name='Garchompite Z', name_ko='한카리아스나이트Z',
                            mega_from='Garchomp', mega_to='Garchomp-Mega-Z')
        Item.objects.create(ruleset=rs, showdown_id='gengarite', name='Gengarite', name_ko='팬텀나이트',
                            mega_from='Gengar', mega_to='Gengar-Mega')
        Nature.objects.create(id='jolly', name='Jolly', name_ko='명랑', plus_stat='spe', minus_stat='spa')
        for atk, m in (('Ice', 2), ('Electric', 0), ('Dragon', 2), ('Ground', 2)):
            TypeChart.objects.create(attacking=atk, defending='Dragon' if atk != 'Electric' else 'Ground',
                                     multiplier=m)
        u = UsageStat.objects.create(ruleset=rs, format_key='champions_mc_doubles', pokemon_key='garchomp',
                                     source='opgg', season='m-6', snapshot_date=date(2026, 9, 29), rank=9, prev_rank=2)
        UsageDetail.objects.create(usage_stat=u, kind='item', target_key='garchompitez', pct=46.3)
        UsageDetail.objects.create(usage_stat=u, kind='spread', target_key='2/32/0/0/0/32', pct=24.6)
        cls.team = Team.objects.create(ruleset=rs, format_key='champions_mc_doubles', source='showdown_replay',
                                       player='Alice', result='win', played_on=date(2026, 9, 29))
        TeamMember.objects.create(team=cls.team, slot=1, pokemon_key='garchomp', item_key='garchompitez',
                                  ability_key='roughskin', nature_key='jolly', move1='earthquake', sp_atk=32)

    def test_ranking(self):
        d = self.client.get('/api/ranking/?format=doubles').json()
        item = d['items'][0]
        self.assertEqual((item['rank'], item['change'], item['is_new']), (9, -7, False))
        self.assertEqual(item['pokemon']['name_ko'], '한카리아스')
        self.assertEqual(self.client.get('/api/ranking/?format=xx').status_code, 400)

    def test_pokemon_list_excludes_mega(self):
        d = self.client.get('/api/pokemon/?format=doubles').json()
        self.assertEqual([p['id'] for p in d['items']], ['garchomp'])
        self.assertTrue(d['items'][0]['has_mega'])
        self.assertEqual(d['items'][0]['rank'], 9)

    def test_pokemon_detail(self):
        d = self.client.get('/api/pokemon/garchompmegaz/').json()   # 메가 ID → 기본 폼 기준
        self.assertEqual(d['id'], 'garchomp')
        self.assertEqual([f['id'] for f in d['forms']], ['garchomp', 'garchompmegaz'])
        self.assertEqual(d['forms'][0]['abilities'][0]['name_ko'], '까칠한피부')
        self.assertIn('Electric', [x['type'] for x in d['forms'][0]['matchups']['immune']])
        self.assertEqual(d['usage']['doubles']['item'][0]['name_ko'], '한카리아스나이트Z')
        self.assertEqual(d['usage']['doubles']['spread'][0]['sp']['atk'], 32)
        self.assertIsNone(d['usage']['singles'])
        self.assertEqual(d['learnset'][0]['name_ko'], '지진')
        self.assertEqual(self.client.get('/api/pokemon/zzz/').status_code, 404)

    def test_teams(self):
        d = self.client.get('/api/teams/?q=한카').json()
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['results'][0]['title'], 'Alice의 리플레이 파티')
        self.assertEqual(self.client.get('/api/teams/?q=없는포켓몬').json()['count'], 0)
        t = self.client.get(f'/api/teams/{self.team.pk}/').json()
        m = t['members'][0]
        self.assertEqual((m['item']['name_ko'], m['nature']['plus'], m['moves'][0]['type']),
                         ('한카리아스나이트Z', 'spe', 'Ground'))
        self.assertEqual(t['weakness']['rows'][0]['cells']['Ice'], 2)

    def test_validate(self):
        ok = {'pokemon': 'garchomp', 'item': 'garchompitez', 'ability': 'roughskin', 'nature': 'jolly',
              'sp': {'hp': 2, 'atk': 32, 'spe': 32}, 'moves': ['earthquake']}
        d = self.client.post('/api/validate/', ok, format='json').json()
        self.assertEqual(d['stats']['spe'], (102 + 32 + 20) * 110 // 100)
        # 기술이 1개뿐이라 빈 칸 오류만 있어야 함
        self.assertEqual([c['message'] for c in d['checks'] if c['level'] == 'error'], ['기술 칸 3개가 비어 있음'])
        bad = {**ok, 'item': 'gengarite', 'sp': {'atk': 33}}
        errors = [c['message'] for c in self.client.post('/api/validate/', bad, format='json').json()['checks']
                  if c['level'] == 'error']
        self.assertIn('팬텀나이트은(는) 한카리아스의 메가스톤이 아님', errors)
        self.assertIn('공격 SP 33: 스탯당 0~32', errors)
