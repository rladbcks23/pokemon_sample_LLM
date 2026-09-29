"""게임 데이터.

레귤레이션별 데이터(Pokemon, Move, Learnset, Item, Ability, PokemonAbility)는 레귤레이션마다 전체를 한 벌씩 저장한다.
각 행은 자동 번호 PK + (ruleset, showdown_id) 유니크. showdown_id는 Showdown ID 규칙(소문자 영숫자, 예: garchompmegaz).
타입 상성과 성격은 레귤레이션과 무관한 고정 데이터.
"""
from django.db import models


class Ruleset(models.Model):
    """레귤레이션 버전 하나 (예: champions_mc = Reg M-C)."""
    id = models.CharField(primary_key=True, max_length=32)
    name = models.CharField(max_length=64)                  # "Regulation M-C"
    showdown_mod = models.CharField(max_length=32)          # "champions"
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'ruleset'
        ordering = ['-start_date']
        verbose_name = verbose_name_plural = '레귤레이션'

    def __str__(self):
        return self.name


class RulesetEntity(models.Model):
    """레귤레이션별로 한 벌씩 저장하는 데이터의 공통 필드."""
    ruleset = models.ForeignKey(Ruleset, on_delete=models.CASCADE)
    showdown_id = models.CharField(max_length=48)
    name = models.CharField(max_length=64)
    name_ko = models.CharField(max_length=64, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name_ko or self.name


class Ability(RulesetEntity):
    short_desc = models.TextField(blank=True)

    class Meta:
        db_table = 'ability'
        constraints = [models.UniqueConstraint(fields=['ruleset', 'showdown_id'], name='ability_ruleset_sid')]
        verbose_name = verbose_name_plural = '특성'


class Pokemon(RulesetEntity):
    """포켓몬 (폼마다 한 행, 메가 폼 포함)."""
    num = models.IntegerField()                                   # 도감번호 (Species Clause 기준)
    base_species = models.CharField(max_length=64)
    forme = models.CharField(max_length=32, blank=True)
    is_mega = models.BooleanField(default=False)
    required_item = models.CharField(max_length=48, blank=True)   # 메가스톤 이름
    type1 = models.CharField(max_length=16)
    type2 = models.CharField(max_length=16, blank=True)
    hp = models.IntegerField()
    atk = models.IntegerField()
    defense = models.IntegerField(db_column='def')   # def는 파이썬 예약어라 필드명만 변경
    spa = models.IntegerField()
    spd = models.IntegerField()
    spe = models.IntegerField()
    bst = models.IntegerField()
    weight_kg = models.FloatField()
    abilities = models.ManyToManyField(Ability, through='PokemonAbility', related_name='pokemon')

    class Meta:
        db_table = 'pokemon'
        constraints = [models.UniqueConstraint(fields=['ruleset', 'showdown_id'], name='pokemon_ruleset_sid')]
        ordering = ['num', 'showdown_id']
        verbose_name = verbose_name_plural = '포켓몬'


class PokemonAbility(models.Model):
    """포켓몬이 가질 수 있는 특성. slot: 0/1(일반), H(숨겨진), S(특수)."""
    SLOTS = [('0', '특성1'), ('1', '특성2'), ('H', '숨겨진 특성'), ('S', '특수')]

    pokemon = models.ForeignKey(Pokemon, on_delete=models.CASCADE, related_name='ability_slots')
    ability = models.ForeignKey(Ability, on_delete=models.CASCADE)
    slot = models.CharField(max_length=1, choices=SLOTS)

    class Meta:
        db_table = 'pokemon_ability'
        constraints = [models.UniqueConstraint(fields=['pokemon', 'slot'], name='pokemon_ability_slot')]
        verbose_name = verbose_name_plural = '포켓몬 특성'


class Move(RulesetEntity):
    type = models.CharField(max_length=16)
    category = models.CharField(max_length=16)                   # Physical / Special / Status
    power = models.IntegerField(default=0)
    accuracy = models.IntegerField(null=True, blank=True)       # None = 반드시 명중
    pp = models.IntegerField()
    priority = models.IntegerField(default=0)
    target = models.CharField(max_length=32)                    # normal / allAdjacentFoes ...
    flags = models.CharField(max_length=255, blank=True)        # "contact|protect|sound" 파이프 구분
    secondary_chance = models.IntegerField(null=True, blank=True)
    short_desc = models.TextField(blank=True)

    class Meta:
        db_table = 'move'
        constraints = [models.UniqueConstraint(fields=['ruleset', 'showdown_id'], name='move_ruleset_sid')]
        verbose_name = verbose_name_plural = '기술'


class Learnset(models.Model):
    """포켓몬이 배울 수 있는 기술 (진화 전 기술 포함, 메가 폼은 원래 폼 기준)."""
    pokemon = models.ForeignKey(Pokemon, on_delete=models.CASCADE, related_name='learnset')
    move = models.ForeignKey(Move, on_delete=models.CASCADE, related_name='learners')

    class Meta:
        db_table = 'learnset'
        constraints = [models.UniqueConstraint(fields=['pokemon', 'move'], name='learnset_pokemon_move')]
        verbose_name = verbose_name_plural = '배우는 기술'


class Item(RulesetEntity):
    mega_from = models.CharField(max_length=64, blank=True)     # 메가스톤: 진화 전 포켓몬
    mega_to = models.CharField(max_length=64, blank=True)       # 메가스톤: 메가 폼
    short_desc = models.TextField(blank=True)

    class Meta:
        db_table = 'item'
        constraints = [models.UniqueConstraint(fields=['ruleset', 'showdown_id'], name='item_ruleset_sid')]
        verbose_name = verbose_name_plural = '도구'


# ---------------------------------------------------------------------------
# 고정 데이터
# ---------------------------------------------------------------------------

class TypeChart(models.Model):
    attacking = models.CharField(max_length=16)
    defending = models.CharField(max_length=16)
    multiplier = models.FloatField()    # 0 / 0.5 / 1 / 2

    class Meta:
        db_table = 'type_chart'
        constraints = [models.UniqueConstraint(fields=['attacking', 'defending'], name='type_chart_pair')]
        verbose_name = verbose_name_plural = '타입 상성'


class Nature(models.Model):
    id = models.CharField(primary_key=True, max_length=16)      # adamant
    name = models.CharField(max_length=16)
    name_ko = models.CharField(max_length=16)
    plus_stat = models.CharField(max_length=3, blank=True)       # atk (무보정 성격은 빈 값)
    minus_stat = models.CharField(max_length=3, blank=True)

    class Meta:
        db_table = 'nature'
        verbose_name = verbose_name_plural = '성격'

    def __str__(self):
        return self.name_ko
