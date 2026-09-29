"""DB 테이블 정의.

구성
- 레귤레이션별 게임 데이터: Ruleset, Pokemon, PokemonAbility, Move, Learnset, Item, Ability
  → 레귤레이션마다 전체 데이터를 한 벌씩 저장 (키에 ruleset_id 포함)
- 고정 데이터: TypeChart, Nature
- 메타/파티 데이터: Team, TeamMember, PokemonSet, UsageStat, UsageDetail

포맷(싱글/더블)과 기믹은 DB가 아니라 data/formats, data/gimmicks의 YAML에 정의하고,
여기서는 format_id 문자열로만 참조한다.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 레귤레이션별 게임 데이터 (Showdown mod → CSV → 적재)
# ---------------------------------------------------------------------------

class Ruleset(Base):
    """레귤레이션 버전 하나 (예: champions_mc = Reg M-C)."""
    __tablename__ = "ruleset"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))              # "Regulation M-C"
    showdown_mod: Mapped[str] = mapped_column(String(32))      # "champions"
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class Pokemon(Base):
    """포켓몬 (폼마다 한 행, 메가 폼 포함)."""
    __tablename__ = "pokemon"

    ruleset_id: Mapped[str] = mapped_column(ForeignKey("ruleset.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(48), primary_key=True)   # Showdown ID: garchompmegaz
    name: Mapped[str] = mapped_column(String(64))
    name_ko: Mapped[str] = mapped_column(String(64))
    num: Mapped[int] = mapped_column(Integer)                        # 도감번호 (Species Clause 기준)
    base_species: Mapped[str] = mapped_column(String(64))
    forme: Mapped[str] = mapped_column(String(32), default="")
    is_mega: Mapped[bool] = mapped_column(Boolean, default=False)
    required_item: Mapped[str] = mapped_column(String(48), default="")  # 메가스톤 이름
    type1: Mapped[str] = mapped_column(String(16))
    type2: Mapped[str] = mapped_column(String(16), default="")
    hp: Mapped[int] = mapped_column(Integer)
    atk: Mapped[int] = mapped_column(Integer)
    def_: Mapped[int] = mapped_column("def", Integer)
    spa: Mapped[int] = mapped_column(Integer)
    spd: Mapped[int] = mapped_column(Integer)
    spe: Mapped[int] = mapped_column(Integer)
    bst: Mapped[int] = mapped_column(Integer)
    weight_kg: Mapped[float] = mapped_column(Float)

    abilities: Mapped[list["PokemonAbility"]] = relationship(back_populates="pokemon")


class Ability(Base):
    __tablename__ = "ability"

    ruleset_id: Mapped[str] = mapped_column(ForeignKey("ruleset.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    name_ko: Mapped[str] = mapped_column(String(64))
    short_desc: Mapped[str] = mapped_column(Text, default="")


class PokemonAbility(Base):
    """포켓몬이 가질 수 있는 특성. slot: 0/1(일반), H(숨겨진), S(특수)."""
    __tablename__ = "pokemon_ability"
    __table_args__ = (
        ForeignKeyConstraint(["ruleset_id", "pokemon_id"], ["pokemon.ruleset_id", "pokemon.id"]),
        ForeignKeyConstraint(["ruleset_id", "ability_id"], ["ability.ruleset_id", "ability.id"]),
    )

    ruleset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pokemon_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    slot: Mapped[str] = mapped_column(String(1), primary_key=True)
    ability_id: Mapped[str] = mapped_column(String(48), index=True)

    pokemon: Mapped[Pokemon] = relationship(back_populates="abilities")
    ability: Mapped[Ability] = relationship(viewonly=True)  # ruleset_id는 pokemon 쪽 관계가 채움


class Move(Base):
    __tablename__ = "move"

    ruleset_id: Mapped[str] = mapped_column(ForeignKey("ruleset.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    name_ko: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16))            # Physical / Special / Status
    power: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[int | None] = mapped_column(Integer)         # None = 반드시 명중
    pp: Mapped[int] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    target: Mapped[str] = mapped_column(String(32))               # normal / allAdjacentFoes ...
    flags: Mapped[str] = mapped_column(String(255), default="")   # "contact|protect|sound" 파이프 구분
    secondary_chance: Mapped[int | None] = mapped_column(Integer)
    short_desc: Mapped[str] = mapped_column(Text, default="")


class Learnset(Base):
    """포켓몬이 배울 수 있는 기술 (진화 전 기술 포함, 메가 폼은 원래 폼 기준)."""
    __tablename__ = "learnset"
    __table_args__ = (
        ForeignKeyConstraint(["ruleset_id", "pokemon_id"], ["pokemon.ruleset_id", "pokemon.id"]),
        ForeignKeyConstraint(["ruleset_id", "move_id"], ["move.ruleset_id", "move.id"]),
    )

    ruleset_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pokemon_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    move_id: Mapped[str] = mapped_column(String(48), primary_key=True, index=True)


class Item(Base):
    __tablename__ = "item"

    ruleset_id: Mapped[str] = mapped_column(ForeignKey("ruleset.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    name_ko: Mapped[str] = mapped_column(String(64))
    mega_from: Mapped[str] = mapped_column(String(64), default="")  # 메가스톤: 진화 전 포켓몬
    mega_to: Mapped[str] = mapped_column(String(64), default="")    # 메가스톤: 메가 폼
    short_desc: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------
# 고정 데이터
# ---------------------------------------------------------------------------

class TypeChart(Base):
    __tablename__ = "type_chart"

    attacking: Mapped[str] = mapped_column(String(16), primary_key=True)
    defending: Mapped[str] = mapped_column(String(16), primary_key=True)
    multiplier: Mapped[float] = mapped_column(Float)   # 0 / 0.5 / 1 / 2


class Nature(Base):
    __tablename__ = "nature"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)   # adamant
    name: Mapped[str] = mapped_column(String(16))
    name_ko: Mapped[str] = mapped_column(String(16))
    plus_stat: Mapped[str | None] = mapped_column(String(3))        # atk (무보정 성격은 None)
    minus_stat: Mapped[str | None] = mapped_column(String(3))


# ---------------------------------------------------------------------------
# 메타/파티 데이터
# ---------------------------------------------------------------------------

SP_STATS = ("hp", "atk", "def", "spa", "spd", "spe")
SP_MAX_PER_STAT = 32
SP_MAX_TOTAL = 66


def _build_checks(prefix: str) -> tuple:
    """SP 제약: 스탯당 0~32, 합계 66 이하."""
    per_stat = [CheckConstraint(f"sp_{s} BETWEEN 0 AND {SP_MAX_PER_STAT}", name=f"{prefix}_sp_{s}_range")
                for s in SP_STATS]
    total = CheckConstraint(" + ".join(f"sp_{s}" for s in SP_STATS) + f" <= {SP_MAX_TOTAL}",
                            name=f"{prefix}_sp_total")
    return (*per_stat, total)


class BuildMixin:
    """육성 정보 (파티 멤버와 흔한 육성형이 공유). ID는 문자열로만 두고 합법성은 도구로 검증한다."""
    pokemon_id: Mapped[str] = mapped_column(String(48), index=True)
    item_id: Mapped[str] = mapped_column(String(48), default="")
    ability_id: Mapped[str] = mapped_column(String(48), default="")
    nature_id: Mapped[str] = mapped_column(String(16), default="")
    sp_hp: Mapped[int] = mapped_column(Integer, default=0)
    sp_atk: Mapped[int] = mapped_column(Integer, default=0)
    sp_def: Mapped[int] = mapped_column(Integer, default=0)
    sp_spa: Mapped[int] = mapped_column(Integer, default=0)
    sp_spd: Mapped[int] = mapped_column(Integer, default=0)
    sp_spe: Mapped[int] = mapped_column(Integer, default=0)
    move1: Mapped[str] = mapped_column(String(48), default="")
    move2: Mapped[str] = mapped_column(String(48), default="")
    move3: Mapped[str] = mapped_column(String(48), default="")
    move4: Mapped[str] = mapped_column(String(48), default="")


class Team(Base):
    """파티 (대회 / 사용자 / 합성). RAG와 학습 데이터의 원본."""
    __tablename__ = "team"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ruleset_id: Mapped[str] = mapped_column(ForeignKey("ruleset.id"), index=True)
    format_id: Mapped[str] = mapped_column(String(48), index=True)   # formats/*.yaml 의 id
    source: Mapped[str] = mapped_column(String(24))   # tournament / user / synthetic / opgg_replica / showdown_replay
    external_id: Mapped[str] = mapped_column(String(64), default="", index=True)  # 원본 ID (리플레이 ID, OP.GG 팀 ID)
    name: Mapped[str] = mapped_column(String(128), default="")
    event: Mapped[str] = mapped_column(String(128), default="")
    player: Mapped[str] = mapped_column(String(64), default="")
    placement: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[int | None] = mapped_column(Integer)             # 리플레이 레이팅
    result: Mapped[str] = mapped_column(String(8), default="")      # 리플레이 승패: win / lose
    played_on: Mapped[date | None] = mapped_column(Date)
    raw_paste: Mapped[str] = mapped_column(Text, default="")          # Showdown 팀 텍스트 원본
    is_legal: Mapped[bool | None] = mapped_column(Boolean)            # 합법성 도구 검증 결과 (None=미검증)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", order_by="TeamMember.slot", cascade="all, delete-orphan")


class TeamMember(BuildMixin, Base):
    __tablename__ = "team_member"
    __table_args__ = (
        UniqueConstraint("team_id", "slot"),
        CheckConstraint("slot BETWEEN 1 AND 6", name="team_member_slot_range"),
        *_build_checks("team_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"))
    slot: Mapped[int] = mapped_column(Integer)
    is_gimmick_user: Mapped[bool] = mapped_column(Boolean, default=False)  # 이 멤버에게 기믹(메가 등)을 쓰는지
    brought: Mapped[bool | None] = mapped_column(Boolean)   # 리플레이: 선출됐는지 (None=정보 없음)
    lead: Mapped[bool | None] = mapped_column(Boolean)      # 리플레이: 선봉이었는지

    team: Mapped[Team] = relationship(back_populates="members")


class PokemonSet(BuildMixin, Base):
    """흔한 육성 형태."""
    __tablename__ = "pokemon_set"
    __table_args__ = _build_checks("pokemon_set")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ruleset_id: Mapped[str] = mapped_column(ForeignKey("ruleset.id"), index=True)
    format_id: Mapped[str] = mapped_column(String(48), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")      # "스카프 선봉형" 같은 이름
    usage_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(24))                # champions / legacy_converted


class UsageStat(Base):
    """사용률 스냅샷 (출처 × 시즌 × 날짜별로 쌓음)."""
    __tablename__ = "usage_stat"
    __table_args__ = (
        UniqueConstraint("ruleset_id", "format_id", "pokemon_id", "source", "season", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ruleset_id: Mapped[str] = mapped_column(ForeignKey("ruleset.id"))
    format_id: Mapped[str] = mapped_column(String(48))
    pokemon_id: Mapped[str] = mapped_column(String(48), index=True)
    source: Mapped[str] = mapped_column(String(32))                # opgg(인게임) / smogon(Showdown)
    season: Mapped[str] = mapped_column(String(16), default="")   # 인게임 랭크 시즌 (m-6), Smogon은 월 (2026-08)
    snapshot_date: Mapped[date] = mapped_column(Date)
    rank: Mapped[int | None] = mapped_column(Integer)
    usage_pct: Mapped[float | None] = mapped_column(Float)         # OP.GG는 순위만 있고 %는 없음

    details: Mapped[list["UsageDetail"]] = relationship(back_populates="usage_stat", cascade="all, delete-orphan")


class UsageDetail(Base):
    """자주 쓰는 기술 / 도구 / 특성 / 성격 / SP 배분 / 동료 포켓몬."""
    __tablename__ = "usage_detail"
    __table_args__ = (
        CheckConstraint("kind IN ('move', 'item', 'ability', 'nature', 'spread', 'teammate')",
                        name="usage_detail_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usage_stat_id: Mapped[int] = mapped_column(ForeignKey("usage_stat.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(String(48))   # spread는 "2/32/0/0/0/32" (HP/공/방/특공/특방/스피드)
    pct: Mapped[float] = mapped_column(Float)

    usage_stat: Mapped[UsageStat] = relationship(back_populates="details")
