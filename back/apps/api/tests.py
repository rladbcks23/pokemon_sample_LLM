from datetime import date

from rest_framework.test import APITestCase

from apps.api.common import names
from apps.dex.models import Ability, Item, Learnset, Move, Nature, Pokemon, PokemonAbility, Ruleset, TypeChart
from apps.dex.typechart import chart
from datetime import datetime, timezone

from apps.meta.models import RankSnapshot, Team, TeamMember, UsageDetail, UsageStat


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
        gz = mon(rs, 'garchompmegaz', 'Garchomp-Mega-Z', '한카리아스-메가Z', ['Dragon'], (108, 130, 85, 141, 85, 151),
                 base='Garchomp', forme='Mega-Z', is_mega=True, required_item='Garchompite Z')
        rough = Ability.objects.create(ruleset=rs, showdown_id='roughskin', name='Rough Skin', name_ko='까칠한피부')
        PokemonAbility.objects.create(pokemon=g, ability=rough, slot='H')
        lev = Ability.objects.create(ruleset=rs, showdown_id='levitate', name='Levitate', name_ko='부유')
        PokemonAbility.objects.create(pokemon=gz, ability=lev, slot='0')
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
        # 순위 스냅샷 2벌: 9/29 2위 → 10/1 9위, 10/1에만 있는 신규 포켓몬
        snap = dict(ruleset=rs, format_key='champions_mc_doubles', source='opgg', season='m-6')
        t1, t2 = datetime(2026, 9, 29, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
        RankSnapshot.objects.create(captured_at=t1, pokemon_key='garchomp', rank=2, **snap)
        RankSnapshot.objects.create(captured_at=t2, pokemon_key='garchomp', rank=9, season_change=-7, **snap)
        RankSnapshot.objects.create(captured_at=t2, pokemon_key='garchompmegaz', rank=10, **snap)
        cls.team = Team.objects.create(ruleset=rs, format_key='champions_mc_doubles', source='showdown_replay',
                                       player='Alice', result='win', played_on=date(2026, 9, 29))
        TeamMember.objects.create(team=cls.team, slot=1, pokemon_key='garchomp', item_key='garchompitez',
                                  ability_key='roughskin', nature_key='jolly', move1='earthquake', sp_atk=32)

    def test_ranking_daily_change(self):
        d = self.client.get('/api/ranking/?format=doubles').json()
        self.assertTrue(d['captured_at'].startswith('2026-10-01'))
        self.assertTrue(d['compared_to'].startswith('2026-09-29'))
        g, new = d['items']
        self.assertEqual((g['rank'], g['prev_rank'], g['change'], g['is_new'], g['season_change']), (9, 2, -7, False, -7))
        self.assertEqual(g['pokemon']['name_ko'], '한카리아스')
        self.assertTrue(new['is_new'])
        self.assertEqual(self.client.get('/api/ranking/?format=xx').status_code, 400)

    def test_pokemon_list_excludes_mega(self):
        d = self.client.get('/api/pokemon/?format=doubles').json()
        self.assertEqual([p['id'] for p in d['items']], ['garchomp'])
        self.assertTrue(d['items'][0]['has_mega'])
        mega = d['items'][0]['megas'][0]
        self.assertEqual((mega['id'], mega['item'], mega['types']), ('garchompmegaz', 'garchompitez', ['Dragon']))
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

    def test_validate_mega_ability(self):
        """메가스톤을 들면 메가 폼 특성(OP.GG 샘플 기록 방식)도 합법, 메가스톤이 없으면 오류."""
        s = {'pokemon': 'garchomp', 'item': 'garchompitez', 'ability': 'levitate', 'nature': 'jolly',
             'sp': {'hp': 2, 'atk': 32, 'spe': 32}, 'moves': ['earthquake']}

        def errors(body):
            return [c['message'] for c in self.client.post('/api/validate/', body, format='json').json()['checks']
                    if c['level'] == 'error']
        self.assertEqual(errors(s), ['기술 칸 3개가 비어 있음'])
        self.assertIn('한카리아스은(는) 이 특성을 가질 수 없음', errors({**s, 'item': ''}))
        self.assertIn('한카리아스은(는) 이 특성을 가질 수 없음', errors({**s, 'item': 'gengarite'}))


class PartyApiTests(APITestCase):
    """파티 점검 · 같이 쓰인 포켓몬 · 위협 포켓몬."""

    @classmethod
    def setUpTestData(cls):
        names.cache_clear()
        chart.cache_clear()
        rs = Ruleset.objects.create(id='champions_mc', name='Regulation M-C', showdown_mod='champions',
                                    start_date=date(2026, 9, 9))
        g = mon(rs, 'garchomp', 'Garchomp', '한카리아스', ['Dragon', 'Ground'], (108, 130, 95, 80, 85, 102))
        y = mon(rs, 'gyarados', 'Gyarados', '갸라도스', ['Water', 'Flying'], (95, 125, 79, 60, 100, 81))
        b = mon(rs, 'blissey', 'Blissey', '해피너스', ['Normal'], (255, 10, 10, 75, 135, 55))
        for sid, ko, typ, cat in (('earthquake', '지진', 'Ground', 'Physical'), ('swordsdance', '칼춤', 'Normal', 'Status'),
                                  ('icebeam', '냉동빔', 'Ice', 'Special'), ('stealthrock', '스텔스록', 'Rock', 'Status'),
                                  ('toxic', '맹독', 'Poison', 'Status'), ('waterfall', '폭포오르기', 'Water', 'Physical')):
            mv = Move.objects.create(ruleset=rs, showdown_id=sid, name=sid, name_ko=ko, type=typ, category=cat,
                                     power=0 if cat == 'Status' else 90, accuracy=100, pp=10, target='normal')
            for p in (g, y, b):
                Learnset.objects.create(pokemon=p, move=mv)
        Item.objects.create(ruleset=rs, showdown_id='lifeorb', name='Life Orb', name_ko='생명의구슬')
        Nature.objects.create(id='jolly', name='Jolly', name_ko='명랑', plus_stat='spe', minus_stat='spa')
        for atk, d, m in (('Ice', 'Dragon', 2), ('Ice', 'Ground', 2), ('Ice', 'Flying', 2), ('Ground', 'Flying', 0)):
            TypeChart.objects.create(attacking=atk, defending=d, multiplier=m)
        for i, keys in enumerate((['garchomp', 'gyarados'], ['garchomp', 'gyarados', 'blissey'], ['garchomp', 'blissey'])):
            t = Team.objects.create(ruleset=rs, format_key='champions_mc_singles', source='opgg_replica', is_legal=True)
            for slot, k in enumerate(keys, 1):
                TeamMember.objects.create(team=t, slot=slot, pokemon_key=k)
        # 리플레이 팀은 세지 않음
        t = Team.objects.create(ruleset=rs, format_key='champions_mc_singles', source='showdown_replay')
        TeamMember.objects.create(team=t, slot=1, pokemon_key='garchomp')
        TeamMember.objects.create(team=t, slot=2, pokemon_key='gyarados')
        # 위협: 갸라도스가 냉동빔을 많이 씀 (픽률 1위)
        snap = dict(ruleset=rs, format_key='champions_mc_singles', source='opgg', season='m-6')
        RankSnapshot.objects.create(captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc), pokemon_key='gyarados',
                                    rank=1, **snap)
        u = UsageStat.objects.create(snapshot_date=date(2026, 10, 1), pokemon_key='gyarados', rank=1, **snap)
        UsageDetail.objects.create(usage_stat=u, kind='move', target_key='icebeam', pct=60)
        UsageDetail.objects.create(usage_stat=u, kind='move', target_key='waterfall', pct=90)

    def check(self, members):
        r = self.client.post('/api/party/check/', {'members': members}, format='json')
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_roles(self):
        sweeper = {'pokemon': 'garchomp', 'item': 'lifeorb', 'nature': 'jolly', 'sp': {'atk': 32, 'spe': 32, 'hp': 2},
                   'moves': ['swordsdance', 'earthquake', 'stealthrock']}
        wall = {'pokemon': 'blissey', 'item': 'lifeorb', 'sp': {'hp': 32, 'def': 32, 'spd': 2},
                'moves': ['toxic', 'icebeam']}
        d = self.check([sweeper, wall])
        self.assertEqual(d['members'][0]['roles'], ['기점잡이', '랭크업 딜러 (물리)'])
        self.assertEqual(d['members'][0]['speed'], (102 + 32 + 20) * 110 // 100)
        self.assertEqual(d['members'][1]['roles'], ['막이 (말려 죽이기)'])
        self.assertEqual((d['summary']['physical_attackers'], d['summary']['special_attackers']), (1, 0))
        self.assertIn('같은 도구 중복: 생명의구슬', d['warnings'])
        self.assertEqual(self.client.post('/api/party/check/', {'members': [{'pokemon': 'zzz'}]},
                                          format='json').status_code, 400)

    def test_partners(self):
        d = self.client.get('/api/partners/?pokemon=garchomp&format=singles').json()
        self.assertEqual(d['teams'], 3)          # 리플레이 팀은 빠짐
        self.assertEqual([(p['id'], p['count']) for p in d['partners']], [('gyarados', 2), ('blissey', 2)])
        d = self.client.get('/api/partners/?pokemon=garchomp,gyarados&format=singles').json()
        self.assertEqual((d['teams'], d['partners'][0]['id']), (2, 'blissey'))

    def test_threats(self):
        d = self.client.post('/api/threats/', {'format': 'singles', 'members': [
            {'pokemon': 'garchomp'}, {'pokemon': 'blissey'}, {'pokemon': 'garchomp'}]}, format='json').json()
        self.assertEqual(d['need_hits'], 2)
        self.assertEqual(d['threats'][0]['id'], 'gyarados')
        self.assertIn('한카리아스←냉동빔(얼음 ×4)', d['threats'][0]['targets'])
