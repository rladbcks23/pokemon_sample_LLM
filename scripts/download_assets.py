"""포켓몬 / 도구 / 타입 아이콘을 받아서 assets/ 에 DB ID 이름으로 저장한다.

사용법: python scripts/download_assets.py [--ruleset champions_mc]

출처 (Smogon / Pokémon Showdown)
- 포켓몬: github.com/smogon/sprites src/champions (챔피언스 전용, 128x128)
         파일명 규칙: s{기본종}-o{폼}.png → 기호를 지우면 DB ID (sgarchomp-omega_z → garchompmegaz)
         여기 없는 폼은 play.pokemonshowdown.com/sprites/home-centered (192x192)
- 도구:   play.pokemonshowdown.com/sprites/itemicons (24x24)
         없으면 smogon/sprites src/minisprites/items (16x16, 신규 메가스톤 등)
- 타입:   play.pokemonshowdown.com/sprites/types (32x14)

이미 받은 파일은 건너뛴다. 이미지 저작권은 원작자에게 있으므로 assets/는 git에 올리지 않는다.
"""
import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
UA = "Mozilla/5.0 (pokemon-sample-builder asset downloader)"
DELAY = 0.2

SPRITES_API = "https://api.github.com/repos/smogon/sprites/contents/src/{}"
SPRITES_RAW = "https://raw.githubusercontent.com/smogon/sprites/master/src/{}/{}"
SHOWDOWN = "https://play.pokemonshowdown.com/sprites"
TYPES = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison", "Ground",
         "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"]


def to_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def get(url: str) -> bytes | None:
    time.sleep(DELAY)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def list_dir(path: str) -> list[str]:
    """GitHub 폴더의 파일 이름 목록 (contents API는 폴더당 최대 1000개)."""
    return [x["name"] for x in json.loads(get(SPRITES_API.format(path)))]


def save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def download_pokemon(rows: list[dict]) -> None:
    out = ASSETS / "pokemon"
    # 이로치(-s.png)는 제외
    files = {}
    for name in list_dir("champions"):
        if name.endswith(".png") and not name.endswith("-s.png"):
            base, _, forme = name[1:-4].partition("-o")
            files[to_id(base + forme)] = name

    ok, fallback, missing = 0, [], []
    for r in rows:
        path = out / f"{r['id']}.png"
        if path.exists():
            ok += 1
            continue
        name = files.get(r["id"])
        data = get(SPRITES_RAW.format("champions", name)) if name else None
        if not data and r["forme"]:
            # 챔피언스 세트에 없는 폼 (포트데스-진작폼 등) → Showdown HOME 스프라이트 (192x192)
            slug = f"{to_id(r['base_species'])}-{to_id(r['forme'])}"
            data = get(f"{SHOWDOWN}/home-centered/{slug}.png")
            if data:
                fallback.append(r["id"])
        if data:
            save(path, data)
            ok += 1
        else:
            missing.append(r["id"])
    print(f"[pokemon] {ok}/{len(rows)}  HOME 스프라이트로 받음: {fallback}  없음: {missing}")


def download_items(rows: list[dict]) -> None:
    out = ASSETS / "items"
    mini = {to_id(n[1:-4]): n for n in list_dir("minisprites/items") if n.endswith(".png")}
    ok, from_mini, missing = 0, [], []
    for r in rows:
        path = out / f"{r['id']}.png"
        if path.exists():
            ok += 1
            continue
        # Showdown 아이콘 파일명: "King's Rock" → "kings-rock"
        slug = re.sub(r"[^a-z0-9 -]", "", r["name"].lower()).replace(" ", "-")
        data = get(f"{SHOWDOWN}/itemicons/{slug}.png")
        if not data and r["id"] in mini:
            data = get(SPRITES_RAW.format("minisprites/items", mini[r["id"]]))
            from_mini.append(r["id"])
        if data:
            save(path, data)
            ok += 1
        else:
            missing.append(r["id"])
    print(f"[items] {ok}/{len(rows)}  작은 아이콘(16x16)으로 받음: {len(from_mini)}개  없음: {missing}")


def download_types() -> None:
    out = ASSETS / "types"
    ok = 0
    for t in TYPES:
        path = out / f"{t}.png"
        if not path.exists():
            data = get(f"{SHOWDOWN}/types/{t}.png")
            if not data:
                print(f"[types] 없음: {t}")
                continue
            save(path, data)
        ok += 1
    print(f"[types] {ok}/{len(TYPES)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ruleset", default="champions_mc", help="data/ 아래 CSV 폴더")
    args = ap.parse_args()
    data = ROOT / "data" / args.ruleset
    download_pokemon(read_csv(data / "pokemon.csv"))
    download_items(read_csv(data / "items.csv"))
    download_types()


if __name__ == "__main__":
    main()
