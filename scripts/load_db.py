"""data/ 의 CSV와 data/raw/ 원본을 DB에 적재한다. 매번 DB를 새로 만든다 (전체 재적재).

사용법: python scripts/load_db.py

적재 순서
1. 게임 데이터 (data/champions_*/*.csv) → ruleset, pokemon, ability, pokemon_ability, move, learnset, item
2. 고정 데이터 → type_chart, nature
3. 사용률 → usage_stat, usage_detail (OP.GG 인게임 통계, Smogon 통계)
4. 파티 / 육성형 → team, team_member (OP.GG 레플리카 팀, Showdown 리플레이), pokemon_set (OP.GG 샘플 빌드)
"""
import csv
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import (  # noqa: E402
    SP_MAX_PER_STAT, SP_MAX_TOTAL, Ability, Base, Item, Learnset, Move, Nature, Pokemon, PokemonAbility,
    PokemonSet, Ruleset, Team, TeamMember, TypeChart, UsageDetail, UsageStat,
)
from app.db.session import SessionLocal, engine  # noqa: E402

DATA = ROOT / "data"
RAW = DATA / "raw"

RULESETS = [
    # id, 이름, Showdown mod, CSV 폴더, 시작일, 종료일
    ("champions_mb", "Regulation M-B", "championsregmb", "champions_mb", date(2026, 6, 17), date(2026, 9, 9)),
    ("champions_mc", "Regulation M-C", "champions", "champions_mc", date(2026, 9, 9), date(2026, 12, 2)),
]

# (영문, 한글, 상승, 하락) - PokeAPI 기준
NATURES = [
    ("Hardy", "노력", None, None), ("Lonely", "외로움", "atk", "def"), ("Brave", "용감", "atk", "spe"),
    ("Adamant", "고집", "atk", "spa"), ("Naughty", "개구쟁이", "atk", "spd"), ("Bold", "대담", "def", "atk"),
    ("Docile", "온순", None, None), ("Relaxed", "무사태평", "def", "spe"), ("Impish", "장난꾸러기", "def", "spa"),
    ("Lax", "촐랑", "def", "spd"), ("Timid", "겁쟁이", "spe", "atk"), ("Hasty", "성급", "spe", "def"),
    ("Serious", "성실", None, None), ("Jolly", "명랑", "spe", "spa"), ("Naive", "천진난만", "spe", "spd"),
    ("Modest", "조심", "spa", "atk"), ("Mild", "의젓", "spa", "def"), ("Quiet", "냉정", "spa", "spe"),
    ("Bashful", "수줍음", None, None), ("Rash", "덜렁", "spa", "spd"), ("Calm", "차분", "spd", "atk"),
    ("Gentle", "얌전", "spd", "def"), ("Sassy", "건방", "spd", "spe"), ("Careful", "신중", "spd", "spa"),
    ("Quirky", "변덕", None, None),
]

SP_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")


def to_id(name: str | None) -> str:
    """Showdown ID 규칙: 소문자 영숫자만."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def int_or_none(v: str):
    return int(v) if v not in ("", None) else None


def sp_valid(sp: dict) -> bool:
    return all(0 <= sp[k] <= SP_MAX_PER_STAT for k in SP_KEYS) and sum(sp.values()) <= SP_MAX_TOTAL


class Report:
    """적재 결과와 매칭 실패 ID 기록."""

    def __init__(self):
        self.counts = Counter()
        self.unmatched = defaultdict(Counter)
        self.skipped = Counter()

    def print(self):
        print("\n=== 적재 결과 ===")
        for k, v in self.counts.items():
            print(f"  {k}: {v}")
        if self.skipped:
            print("=== 건너뜀 ===")
            for k, v in self.skipped.items():
                print(f"  {k}: {v}")
        if self.unmatched:
            print("=== DB에 없는 ID (상위 15개) ===")
            for kind, c in self.unmatched.items():
                print(f"  [{kind}] {sum(c.values())}건: {c.most_common(15)}")


R = Report()


# ---------------------------------------------------------------------------
# 1. 게임 데이터
# ---------------------------------------------------------------------------

class Dex:
    """레귤레이션별 ID 집합 (다른 출처의 ID 검증용)."""

    def __init__(self):
        self.pokemon: dict[str, dict] = {}
        self.moves: set[str] = set()
        self.items: set[str] = set()
        self.abilities: set[str] = set()

    def resolve_cosmetic(self, pokemon_id: str) -> str:
        """외형만 다른 폼(vivillonhighplains 등)은 DB에 없으므로 기본 폼으로."""
        if pokemon_id in self.pokemon:
            return pokemon_id
        bases = [p for p, r in self.pokemon.items() if not r["forme"] and pokemon_id.startswith(p)]
        return max(bases, key=len) if bases else pokemon_id

    def base_id(self, pokemon_id: str) -> str:
        """메가 폼이면 원래 폼 ID (파티에는 메가 전 포켓몬 + 메가스톤으로 저장)."""
        p = self.pokemon.get(pokemon_id)
        return to_id(p["base_species"]) if p and p["is_mega"] == "1" else pokemon_id


def load_game_data(s, ruleset_id: str, folder: str) -> Dex:
    d = DATA / folder
    dex = Dex()

    for r in read_csv(d / "abilities.csv"):
        s.add(Ability(ruleset_id=ruleset_id, id=r["id"], name=r["name"], name_ko=r["name_ko"],
                      short_desc=r["short_desc"]))
        dex.abilities.add(r["id"])
    ability_ids = {r["name"]: r["id"] for r in read_csv(d / "abilities.csv")}

    for r in read_csv(d / "pokemon.csv"):
        s.add(Pokemon(
            ruleset_id=ruleset_id, id=r["id"], name=r["name"], name_ko=r["name_ko"], num=int(r["num"]),
            base_species=r["base_species"], forme=r["forme"], is_mega=r["is_mega"] == "1",
            required_item=r["required_item"], type1=r["type1"], type2=r["type2"],
            hp=int(r["hp"]), atk=int(r["atk"]), def_=int(r["def"]), spa=int(r["spa"]), spd=int(r["spd"]),
            spe=int(r["spe"]), bst=int(r["bst"]), weight_kg=float(r["weight_kg"])))
        for slot, col in (("0", "ability1"), ("1", "ability2"), ("H", "ability_hidden"), ("S", "ability_special")):
            if r[col]:
                s.add(PokemonAbility(ruleset_id=ruleset_id, pokemon_id=r["id"], slot=slot,
                                     ability_id=ability_ids[r[col]]))
        dex.pokemon[r["id"]] = r

    for r in read_csv(d / "moves.csv"):
        s.add(Move(ruleset_id=ruleset_id, id=r["id"], name=r["name"], name_ko=r["name_ko"], type=r["type"],
                   category=r["category"], power=int(r["power"] or 0), accuracy=int_or_none(r["accuracy"]),
                   pp=int(r["pp"]), priority=int(r["priority"]), target=r["target"], flags=r["flags"],
                   secondary_chance=int_or_none(r["secondary_chance"]), short_desc=r["short_desc"]))
        dex.moves.add(r["id"])

    for r in read_csv(d / "items.csv"):
        s.add(Item(ruleset_id=ruleset_id, id=r["id"], name=r["name"], name_ko=r["name_ko"],
                   mega_from=r["mega_from"], mega_to=r["mega_to"], short_desc=r["short_desc"]))
        dex.items.add(r["id"])

    s.flush()  # learnset 외래키 검사 전에 pokemon/move 먼저 반영
    rows = [{"ruleset_id": ruleset_id, "pokemon_id": r["pokemon_id"], "move_id": r["move_id"]}
            for r in read_csv(d / "learnsets.csv")]
    s.execute(Learnset.__table__.insert(), rows)

    R.counts[f"{ruleset_id}: pokemon/move/item/ability/learnset"] = (
        f"{len(dex.pokemon)}/{len(dex.moves)}/{len(dex.items)}/{len(dex.abilities)}/{len(rows)}")
    return dex


def load_static(s) -> None:
    for r in read_csv(DATA / "champions_mc" / "typechart.csv"):
        s.add(TypeChart(attacking=r["attacking"], defending=r["defending"], multiplier=float(r["multiplier"])))
    for name, ko, plus, minus in NATURES:
        s.add(Nature(id=to_id(name), name=name, name_ko=ko, plus_stat=plus, minus_stat=minus))
    R.counts["type_chart / nature"] = "324 / 25"


# ---------------------------------------------------------------------------
# OP.GG ID → Showdown ID
# ---------------------------------------------------------------------------

OPGG_POKEMON_OVERRIDES = {
    "floette-eternal-flower": "floetteeternal",
    "maushold-family-of-three": "maushold",
    "maushold-family-of-four": "mausholdfour",
    "mega-meowstic": "meowsticmmega",
    "mega-meowstic-male": "meowsticmmega",
    "mega-meowstic-female": "meowsticfmega",
}
OPGG_REGION = {"alolan": "alola", "galarian": "galar", "hisuian": "hisui", "paldean": "paldea"}
# 메가스톤 이름이 Showdown과 다른 것
OPGG_ITEM_OVERRIDES = {
    "staraptorite": "staraptite", "barbaraclite": "barbaracite",
    "scolipedite": "scolipite", "scraftite": "scraftinite",
}


def opgg_item_id(key: str | None) -> str:
    iid = to_id(key)
    return OPGG_ITEM_OVERRIDES.get(iid, iid)


def opgg_pokemon_id(key: str, dex: Dex) -> str:
    if key in OPGG_POKEMON_OVERRIDES:
        return OPGG_POKEMON_OVERRIDES[key]
    parts = key.split("-")
    if parts[0] == "mega":                       # mega-garchomp-z → garchomp-mega-z
        parts = [parts[1], "mega", *parts[2:]]
    parts = [OPGG_REGION.get(p, p) for p in parts if p != "plumage"]  # squawkabilly-blue-plumage
    if parts[-1] == "male":                      # basculegion-male → basculegion
        parts = parts[:-1]
    elif parts[-1] == "female":                  # indeedee-female → indeedeef
        parts[-1] = "f"
    pid = to_id("".join(parts))
    if pid not in dex.pokemon:
        # 기본 폼 이름이 붙은 경우 (lycanroc-midday → lycanroc)
        base = to_id(parts[0])
        if base in dex.pokemon and dex.pokemon[base]["base_species"] == dex.pokemon[base]["name"]:
            forme_key = to_id("".join(parts[1:]))
            if not any(to_id(p["forme"]) == forme_key for p in dex.pokemon.values()
                       if to_id(p["base_species"]) == base):
                return base
    return pid


def check(kind: str, value: str, valid: set | dict) -> str:
    if value and value not in valid:
        R.unmatched[kind][value] += 1
    return value


# ---------------------------------------------------------------------------
# 3. 사용률
# ---------------------------------------------------------------------------

def load_opgg_ranked(s, dex: Dex) -> None:
    """OP.GG 인게임 랭크 통계 (M-C). 기술/도구/특성/성격/SP배분 %, 순위."""
    for season_dir in sorted((RAW / "opgg" / "ranked").glob("*")):
        season = season_dir.name
        for fmt_dir in season_dir.glob("*"):
            fmt = {"single": "singles", "double": "doubles"}[fmt_dir.name]
            n, seen = 0, set()
            for f in sorted(fmt_dir.glob("*.json")):
                d = load_json(f)
                det = d["overview"]["detail"]
                body = det["detail"]
                lk = d["lookupData"]
                names = {kind: {x["id"]: x.get("key") or x.get("name") for x in lk.get(kind, [])}
                         for kind in ("moves", "items", "abilities", "natures")}

                pid = check("pokemon(opgg)", opgg_pokemon_id(body["pokemon"]["key"], dex), dex.pokemon)
                if pid in seen:  # 같은 포켓몬의 다른 표기 (aegislash-blade 등) → 먼저 나온 것만
                    R.skipped[f"opgg 인게임 통계 중복 ({body['pokemon']['key']})"] += 1
                    continue
                seen.add(pid)
                u = UsageStat(
                    ruleset_id="champions_mc", format_id=f"champions_mc_{fmt}", pokemon_id=pid, source="opgg",
                    season=season, snapshot_date=datetime.strptime(det["createdAt"][:10], "%Y-%m-%d").date(),
                    rank=d["overview"]["ranking"]["pokemon"]["rank"])
                for kind, src, valid in (("move", "moves", dex.moves), ("item", "items", dex.items),
                                         ("ability", "abilities", dex.abilities)):
                    for x in body.get(src) or []:
                        raw = names[src].get(x["id"])
                        tid = check(f"{kind}(opgg)", opgg_item_id(raw) if kind == "item" else to_id(raw), valid)
                        u.details.append(UsageDetail(kind=kind, target_id=tid, pct=x["usagePercent"]))
                for x in body.get("natures") or []:
                    u.details.append(UsageDetail(kind="nature", target_id=to_id(names["natures"].get(x["id"])),
                                                 pct=x["usagePercent"]))
                for x in body.get("training") or []:
                    sp = "/".join(str(int(h, 16)) for h in x["spread"].split("-"))  # 16진수 → 10진수
                    u.details.append(UsageDetail(kind="spread", target_id=sp, pct=x["usagePercent"]))
                s.add(u)
                n += 1
            R.counts[f"usage_stat opgg {season} {fmt}"] = n


def load_smogon(s, dexes: dict[str, Dex]) -> None:
    """Smogon 월별 통계 (chaos JSON). 가중치 합계 기준으로 %를 계산."""
    fmt_map = {  # Showdown 포맷 → (ruleset, format_id, source)
        "gen9championsvgc2026regmb": ("champions_mb", "champions_mb_doubles", "smogon"),
        "gen9championsvgc2026regmbbo3": ("champions_mb", "champions_mb_doubles", "smogon_bo3"),
        "gen9championsbssregmb": ("champions_mb", "champions_mb_singles", "smogon"),
        "gen9championsvgc2026regmc": ("champions_mc", "champions_mc_doubles", "smogon"),
        "gen9championsvgc2026regmcbo3": ("champions_mc", "champions_mc_doubles", "smogon_bo3"),
        "gen9championsbssregmc": ("champions_mc", "champions_mc_singles", "smogon"),
    }
    for f in sorted((RAW / "smogon").glob("*/*.json")):
        month = f.parent.name
        meta = f.stem.rsplit("-", 1)[0]
        if meta not in fmt_map:
            continue
        ruleset_id, format_id, source = fmt_map[meta]
        dex = dexes[ruleset_id]
        data = load_json(f)["data"]
        y, m = map(int, month.split("-"))
        snapshot = date(y + (m == 12), m % 12 + 1, 1)  # 통계가 집계된 달의 다음 달 1일
        ranked = sorted(data.items(), key=lambda kv: -kv[1]["usage"])
        for rank, (name, v) in enumerate(ranked, 1):
            total = sum(v["Abilities"].values()) or 1
            u = UsageStat(ruleset_id=ruleset_id, format_id=format_id,
                          pokemon_id=check("pokemon(smogon)", to_id(name), dex.pokemon), source=source,
                          season=month, snapshot_date=snapshot, rank=rank, usage_pct=round(v["usage"] * 100, 3))

            def top(counter: dict, n: int = 15):
                return sorted(counter.items(), key=lambda kv: -kv[1])[:n]

            for kind, key, valid in (("move", "Moves", dex.moves), ("item", "Items", dex.items),
                                     ("ability", "Abilities", dex.abilities)):
                for tid, w in top(v[key]):
                    if tid in ("", "nothing"):
                        continue
                    u.details.append(UsageDetail(kind=kind, target_id=check(f"{kind}(smogon)", tid, valid),
                                                 pct=round(w / total * 100, 3)))
            # Spreads는 "성격:SP" 형식 → 성격과 SP 배분으로 나눠 집계
            natures, spreads = Counter(), Counter()
            for k, w in v["Spreads"].items():
                nat, sp = k.split(":")
                natures[to_id(nat)] += w
                spreads[sp] += w
            for kind, c in (("nature", natures), ("spread", spreads)):
                for tid, w in top(c):
                    u.details.append(UsageDetail(kind=kind, target_id=tid, pct=round(w / total * 100, 3)))
            for mate, w in top(v["Teammates"], 12):
                u.details.append(UsageDetail(kind="teammate", target_id=to_id(mate), pct=round(w / total * 100, 3)))
            s.add(u)
        R.counts[f"usage_stat {source} {month} {format_id}"] = len(ranked)


# ---------------------------------------------------------------------------
# 4. 파티 / 육성형
# ---------------------------------------------------------------------------

def opgg_build(slot: dict, dex: Dex) -> dict | None:
    """OP.GG 슬롯 → BuildMixin 필드. SP 규칙 위반이면 None."""
    if not slot.get("pokemon"):
        return None
    pid = check("pokemon(opgg)", opgg_pokemon_id(slot["pokemon"], dex), dex.pokemon)
    cs = slot.get("customStats") or {}
    sp = {k: int(cs.get(src) or 0) for k, src in zip(SP_KEYS, ("hp", "attack", "defense", "spAtk", "spDef", "speed"))}
    if not sp_valid(sp):
        return None
    moves = [check("move(opgg)", to_id(m), dex.moves) for m in (slot.get("moves") or [])] + [""] * 4
    return {
        "pokemon_id": dex.base_id(pid),
        "item_id": check("item(opgg)", opgg_item_id(slot.get("item")), dex.items),
        "ability_id": check("ability(opgg)", to_id(slot.get("ability")), dex.abilities),
        "nature_id": to_id(slot.get("nature")),
        **{f"sp_{k}": v for k, v in sp.items()},
        "move1": moves[0], "move2": moves[1], "move3": moves[2], "move4": moves[3],
        "_is_mega": dex.pokemon.get(pid, {}).get("is_mega") == "1",
    }


def load_opgg_teams(s, dex: Dex) -> None:
    for fmt in ("single", "double"):
        path = RAW / "opgg" / f"replica-teams_{fmt}.json"
        if not path.exists():
            continue
        n = 0
        for t in load_json(path):
            builds = [opgg_build(sl, dex) for sl in t["slots"]]
            if any(b is None and sl.get("pokemon") for b, sl in zip(builds, t["slots"])):
                R.skipped["opgg 레플리카 팀 (SP 규칙 위반)"] += 1
                continue
            builds = [b for b in builds if b]
            if not builds:
                R.skipped["opgg 레플리카 팀 (빈 팀)"] += 1
                continue
            team = Team(ruleset_id="champions_mc", format_id=f"champions_mc_{fmt}s", source="opgg_replica",
                        external_id=str(t["id"]), name=t.get("title") or "",
                        player=(t.get("author") or {}).get("nickname") or "",
                        played_on=datetime.fromisoformat(t["createdAt"].replace("Z", "+00:00")).date(),
                        raw_paste=json.dumps(t["slots"], ensure_ascii=False))
            for i, b in enumerate(builds, 1):
                is_mega = b.pop("_is_mega")
                team.members.append(TeamMember(slot=i, is_gimmick_user=is_mega, **b))
            s.add(team)
            n += 1
        R.counts[f"team opgg_replica {fmt}"] = n


def load_opgg_samples(s, dex: Dex) -> None:
    for fmt in ("single", "double"):
        path = RAW / "opgg" / f"sample-builds_{fmt}.json"
        if not path.exists():
            continue
        n = 0
        for x in load_json(path):
            b = opgg_build(x["slot"], dex)
            if not b:
                R.skipped["opgg 샘플 빌드 (SP 규칙 위반/빈 슬롯)"] += 1
                continue
            b.pop("_is_mega")
            s.add(PokemonSet(ruleset_id="champions_mc", format_id=f"champions_mc_{fmt}s",
                             name=x.get("title") or "", source="opgg_sample", **b))
            n += 1
        R.counts[f"pokemon_set opgg_sample {fmt}"] = n


def parse_replay(rep: dict) -> list[dict]:
    """리플레이 로그 → 양쪽 파티 정보."""
    sides = {s: {"species": [], "sets": {}, "brought": set(), "lead": set(), "mega": set()} for s in ("p1", "p2")}
    names, winner, turn_started = {}, None, False
    for line in rep["log"].split("\n"):
        p = line.split("|")
        if len(p) < 2:
            continue
        tag = p[1]
        if tag == "player" and len(p) > 3 and p[3]:
            names[p[2]] = p[3]
        elif tag == "poke":                         # 팀 프리뷰: |poke|p1|Garchomp, L50, M|
            sides[p[2]]["species"].append(to_id(p[3].split(",")[0]))
        elif tag == "showteam":                     # 오픈 팀시트: 이름|종|도구|특성|기술|성격|...]
            for packed in "|".join(p[3:]).split("]"):
                f = packed.split("|")
                if len(f) < 6:
                    continue
                sid = to_id(f[1] or f[0])
                sides[p[2]]["sets"][sid] = {"item": to_id(f[2]), "ability": to_id(f[3]),
                                            "moves": [to_id(m) for m in f[4].split(",") if m],
                                            "nature": to_id(f[5])}
        elif tag in ("switch", "drag"):             # |switch|p1a: 별명|Garchomp, L50, M|100/100
            side = p[2][:2]
            sid = to_id(p[3].split(",")[0])
            sides[side]["brought"].add(sid)
            if not turn_started:
                sides[side]["lead"].add(sid)
        elif tag == "-mega":                        # |-mega|p1b: 별명|Blastoise|Blastoisinite
            sides[p[2][:2]]["mega"].add(to_id(p[3]))
        elif tag == "turn":
            turn_started = True
        elif tag == "win":
            winner = p[2]
    out = []
    for side, info in sides.items():
        out.append({"side": side, "player": names.get(side, ""),
                    "result": "" if winner is None else ("win" if names.get(side) == winner else "lose"), **info})
    return out


def match_species(sid: str, candidates: set[str]) -> bool:
    """팀 프리뷰 종과 배틀 중 종 이름 매칭 (폼이 바뀌어 보이는 경우 앞부분 일치로 허용)."""
    return sid in candidates or any(c.startswith(sid) or sid.startswith(c) for c in candidates)


def load_replays(s, dex: Dex) -> None:
    fmt_map = {"gen9championsvgc2026regmcbo3": "champions_mc_doubles",
               "gen9championsvgc2026regmc": "champions_mc_doubles",
               "gen9championsbssregmc": "champions_mc_singles"}
    for fmt_dir in sorted((RAW / "showdown" / "replays").glob("*")):
        format_id = fmt_map.get(fmt_dir.name)
        if not format_id:
            continue
        n = 0
        for f in sorted(fmt_dir.glob("*.json")):
            rep = load_json(f)
            played = datetime.fromtimestamp(rep["uploadtime"], tz=timezone.utc).date()
            for side in parse_replay(rep):
                if len(side["species"]) < 6:
                    R.skipped["리플레이 파티 (6마리 미만)"] += 1
                    continue
                team = Team(ruleset_id="champions_mc", format_id=format_id, source="showdown_replay",
                            external_id=f"{rep['id']}:{side['side']}", name=rep["id"], player=side["player"],
                            played_on=played, rating=rep.get("rating") or None, result=side["result"])
                for i, sid in enumerate(side["species"], 1):
                    sid = dex.resolve_cosmetic(sid)
                    check("pokemon(replay)", sid, dex.pokemon)
                    st = side["sets"].get(sid, {})
                    moves = [check("move(replay)", m, dex.moves) for m in st.get("moves", [])] + [""] * 4
                    team.members.append(TeamMember(
                        slot=i, pokemon_id=dex.base_id(sid),
                        item_id=check("item(replay)", st.get("item", ""), dex.items),
                        ability_id=check("ability(replay)", st.get("ability", ""), dex.abilities),
                        nature_id=st.get("nature", ""),
                        move1=moves[0], move2=moves[1], move3=moves[2], move4=moves[3],
                        is_gimmick_user=match_species(sid, side["mega"]),
                        brought=match_species(sid, side["brought"]),
                        lead=match_species(sid, side["lead"])))
                s.add(team)
                n += 1
        R.counts[f"team showdown_replay {fmt_dir.name}"] = n


# ---------------------------------------------------------------------------

def main() -> None:
    db_path = engine.url.database
    print(f"DB: {db_path}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with SessionLocal() as s:
        dexes = {}
        for rid, name, mod, folder, start, end in RULESETS:
            s.add(Ruleset(id=rid, name=name, showdown_mod=mod, start_date=start, end_date=end))
            s.flush()
            dexes[rid] = load_game_data(s, rid, folder)
        load_static(s)
        s.commit()

        mc = dexes["champions_mc"]
        load_opgg_ranked(s, mc)
        load_smogon(s, dexes)
        s.commit()

        load_opgg_teams(s, mc)
        load_opgg_samples(s, mc)
        load_replays(s, mc)
        s.commit()

    R.print()


if __name__ == "__main__":
    main()
