"""메타/파티 데이터: 사용률, 파티, 흔한 육성형.

포켓몬·도구·기술 등은 외래키 없이 Showdown ID 문자열(*_key)로 저장한다.
일부러 망가뜨린 파티나 잘못 입력된 파티도 저장해야 하므로 입구에서 막지 않고, 합법성은 도구로 검사한다.
포맷(format_key)은 data/formats/*.yaml 의 id.
"""
from django.db import models
from django.db.models import F, Q
from django.db.models.lookups import LessThanOrEqual

from apps.dex.models import Ruleset

SP_STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
SP_MAX_PER_STAT = 32
SP_MAX_TOTAL = 66


def sp_constraints(prefix: str) -> list:
    """SP 제약: 스탯당 0~32, 합계 66 이하."""
    per_stat = [models.CheckConstraint(condition=Q(**{f'sp_{s}__gte': 0, f'sp_{s}__lte': SP_MAX_PER_STAT}),
                                       name=f'{prefix}_sp_{s}_range') for s in SP_STATS]
    total = sum((F(f'sp_{s}') for s in SP_STATS[1:]), F('sp_hp'))
    return [*per_stat, models.CheckConstraint(condition=LessThanOrEqual(total, SP_MAX_TOTAL),
                                              name=f'{prefix}_sp_total')]


class Build(models.Model):
    """육성 정보 (파티 멤버와 흔한 육성형이 공유)."""
    pokemon_key = models.CharField(max_length=48, db_index=True)
    item_key = models.CharField(max_length=48, blank=True)
    ability_key = models.CharField(max_length=48, blank=True)
    nature_key = models.CharField(max_length=16, blank=True)
    sp_hp = models.PositiveSmallIntegerField(default=0)
    sp_atk = models.PositiveSmallIntegerField(default=0)
    sp_def = models.PositiveSmallIntegerField(default=0)
    sp_spa = models.PositiveSmallIntegerField(default=0)
    sp_spd = models.PositiveSmallIntegerField(default=0)
    sp_spe = models.PositiveSmallIntegerField(default=0)
    move1 = models.CharField(max_length=48, blank=True)
    move2 = models.CharField(max_length=48, blank=True)
    move3 = models.CharField(max_length=48, blank=True)
    move4 = models.CharField(max_length=48, blank=True)

    class Meta:
        abstract = True

    @property
    def sp(self) -> str:
        return '/'.join(str(getattr(self, f'sp_{s}')) for s in SP_STATS)

    @property
    def moves(self) -> list[str]:
        return [m for m in (self.move1, self.move2, self.move3, self.move4) if m]


class Team(models.Model):
    """파티 (대회 / 사용자 / 합성 / 수집). RAG와 학습 데이터의 원본."""
    SOURCES = [
        ('tournament', '대회'), ('user', '사용자'), ('synthetic', '합성'),
        ('opgg_replica', 'OP.GG 레플리카 팀'), ('showdown_replay', 'Showdown 리플레이'),
        ('vgcpastes', 'VGCPastes 대회 팀'),
    ]
    RESULTS = [('', '-'), ('win', '승'), ('lose', '패')]

    ruleset = models.ForeignKey(Ruleset, on_delete=models.PROTECT)
    format_key = models.CharField(max_length=48, db_index=True)
    source = models.CharField(max_length=24, choices=SOURCES)
    external_id = models.CharField(max_length=64, blank=True, db_index=True)  # 리플레이 ID, OP.GG 팀 ID
    name = models.CharField(max_length=128, blank=True)
    event = models.CharField(max_length=128, blank=True)
    player = models.CharField(max_length=64, blank=True)
    placement = models.IntegerField(null=True, blank=True)
    rating = models.IntegerField(null=True, blank=True)                       # 리플레이 레이팅
    result = models.CharField(max_length=8, choices=RESULTS, blank=True)      # 리플레이 승패
    played_on = models.DateField(null=True, blank=True)
    raw_paste = models.TextField(blank=True)                                  # 원본 팀 텍스트/JSON
    is_legal = models.BooleanField(null=True, blank=True)                     # 합법성 도구 결과 (None=미검증)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'team'
        verbose_name = verbose_name_plural = '파티'

    def __str__(self):
        return self.name or f'{self.get_source_display()} #{self.pk}'


class TeamMember(Build):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='members')
    slot = models.PositiveSmallIntegerField()
    is_gimmick_user = models.BooleanField(default=False)            # 이 멤버에게 기믹(메가 등)을 쓰는지
    brought = models.BooleanField(null=True, blank=True)            # 리플레이: 배틀에 나왔는지 (None=정보 없음)
    lead = models.BooleanField(null=True, blank=True)               # 리플레이: 선봉이었는지
    # SP를 다른 파티에서 가져왔으면 그 출처 (예: vgcpastes:MC408). 리플레이는 SP가 공개되지 않아서
    # 같은 파티(6마리 육성이 모두 같은)의 공개 팀에서만 채움
    sp_from = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = 'team_member'
        ordering = ['team', 'slot']
        constraints = [
            models.UniqueConstraint(fields=['team', 'slot'], name='team_member_slot_unique'),
            models.CheckConstraint(condition=Q(slot__gte=1, slot__lte=6), name='team_member_slot_range'),
            *sp_constraints('team_member'),
        ]
        verbose_name = verbose_name_plural = '파티 멤버'

    def __str__(self):
        return f'{self.slot}. {self.pokemon_key}'


class PokemonSet(Build):
    """흔한 육성 형태."""
    ruleset = models.ForeignKey(Ruleset, on_delete=models.PROTECT)
    format_key = models.CharField(max_length=48, db_index=True)
    name = models.CharField(max_length=64, blank=True)          # "스카프 선봉형" 같은 이름
    usage_pct = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=24)                    # opgg_sample / champions / legacy_converted

    class Meta:
        db_table = 'pokemon_set'
        constraints = sp_constraints('pokemon_set')
        verbose_name = verbose_name_plural = '육성형'

    def __str__(self):
        return self.name or self.pokemon_key


class UsageStat(models.Model):
    """사용률 스냅샷 (출처 × 시즌 × 날짜별로 쌓음)."""
    ruleset = models.ForeignKey(Ruleset, on_delete=models.PROTECT)
    format_key = models.CharField(max_length=48)
    pokemon_key = models.CharField(max_length=48, db_index=True)
    source = models.CharField(max_length=32)                    # opgg(인게임) / smogon / smogon_bo3
    season = models.CharField(max_length=16, blank=True)        # 인게임 랭크 시즌(m-6), Smogon은 월(2026-08)
    snapshot_date = models.DateField()
    rank = models.IntegerField(null=True, blank=True)
    prev_rank = models.IntegerField(null=True, blank=True)      # 직전 시즌 순위 (None = 신규 또는 정보 없음)
    usage_pct = models.FloatField(null=True, blank=True)        # OP.GG는 순위만 있고 %는 없음

    class Meta:
        db_table = 'usage_stat'
        ordering = ['rank']
        constraints = [models.UniqueConstraint(
            fields=['ruleset', 'format_key', 'pokemon_key', 'source', 'season', 'snapshot_date'],
            name='usage_stat_snapshot')]
        verbose_name = verbose_name_plural = '사용률'

    def __str__(self):
        return f'{self.source} {self.format_key} {self.rank}위 {self.pokemon_key}'

    @property
    def rank_change(self) -> int | None:
        """순위 변동 (양수 = 상승). 직전 시즌 순위가 없으면 None."""
        if self.rank is None or self.prev_rank is None:
            return None
        return self.prev_rank - self.rank


class UsageDetail(models.Model):
    """자주 쓰는 기술 / 도구 / 특성 / 성격 / SP 배분 / 동료 포켓몬."""
    KINDS = [('move', '기술'), ('item', '도구'), ('ability', '특성'), ('nature', '성격'),
             ('spread', 'SP 배분'), ('teammate', '동료')]

    usage_stat = models.ForeignKey(UsageStat, on_delete=models.CASCADE, related_name='details')
    kind = models.CharField(max_length=16, choices=KINDS)
    target_key = models.CharField(max_length=48)    # spread는 "2/32/0/0/0/32" (HP/공/방/특공/특방/스피드)
    pct = models.FloatField()

    class Meta:
        db_table = 'usage_detail'
        ordering = ['-pct']
        constraints = [models.CheckConstraint(condition=Q(kind__in=['move', 'item', 'ability', 'nature', 'spread',
                                                                     'teammate']), name='usage_detail_kind')]
        verbose_name = verbose_name_plural = '사용률 상세'


class RankSnapshot(models.Model):
    """픽률 순위 스냅샷. OP.GG 순위가 갱신될 때마다 한 벌씩 쌓아 직전 스냅샷과 비교 (일별 변동)."""
    ruleset = models.ForeignKey(Ruleset, on_delete=models.PROTECT)
    format_key = models.CharField(max_length=48)
    source = models.CharField(max_length=32, default='opgg')
    season = models.CharField(max_length=16, blank=True)
    captured_at = models.DateTimeField()                 # 출처의 갱신 시각 (OP.GG createdAt)
    pokemon_key = models.CharField(max_length=48, db_index=True)
    rank = models.IntegerField()
    season_change = models.IntegerField(null=True, blank=True)   # 출처가 주는 직전 시즌 대비 변동 (None = 신규)

    class Meta:
        db_table = 'rank_snapshot'
        ordering = ['-captured_at', 'rank']
        constraints = [models.UniqueConstraint(fields=['format_key', 'source', 'captured_at', 'pokemon_key'],
                                               name='rank_snapshot_unique')]
        indexes = [models.Index(fields=['format_key', 'source', 'captured_at'])]
        verbose_name = verbose_name_plural = '순위 스냅샷'

    def __str__(self):
        return f'{self.format_key} {self.captured_at:%m-%d %H:%M} {self.rank}위 {self.pokemon_key}'
