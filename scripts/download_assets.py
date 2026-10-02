"""포켓몬 / 도구 / 타입 아이콘을 받아서 assets/ 에 DB ID 이름으로 저장한다.

사용법: python scripts/download_assets.py [--ruleset champions_mc]

출처 (Smogon / Pokémon Showdown)
- 포켓몬: github.com/smogon/sprites src/champions (챔피언스 전용, 128x128)
         파일명 규칙: s{기본종}-o{폼}.png → 기호를 지우면 DB ID (sgarchomp-omega_z → garchompmegaz)
         여기 없는 폼은 play.pokemonshowdown.com/sprites/home-centered (192x192)
- 도구:   play.pokemonshowdown.com/sprites/itemicons (24x24)
         없으면 smogon/sprites src/minisprites/items (16x16, 신규 메가스톤 등)
- 타입:   나무위키 스타일 배지를 직접 생성 (배경색 + 흰색 심볼 + 한글 이름, 120x40)
         심볼은 PokeAPI 스칼렛바이올렛 타입 배지에서 잘라내고, 색은 나무위키 타입 표 기준

이미 받은 파일은 건너뛴다. 이미지 저작권은 원작자에게 있으므로 assets/는 git에 올리지 않는다.
"""
import argparse
import csv
import io
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
# 타입: (PokeAPI 타입 번호, 한글, 나무위키 배경색)
TYPES = {
    "Normal": (1, "노말", "#949495"), "Fire": (10, "불꽃", "#CC734A"), "Water": (11, "물", "#6785C0"),
    "Grass": (12, "풀", "#7AA653"), "Electric": (13, "전기", "#E9BB46"), "Ice": (15, "얼음", "#91C6E7"),
    "Fighting": (2, "격투", "#CE9E48"), "Poison": (4, "독", "#6D5493"), "Ground": (5, "땅", "#92784B"),
    "Flying": (3, "비행", "#AEC2E3"), "Psychic": (14, "에스퍼", "#C6727C"), "Bug": (7, "벌레", "#9EA153"),
    "Rock": (6, "바위", "#BCB88E"), "Ghost": (8, "고스트", "#624A6D"), "Dragon": (16, "드래곤", "#5A5DA3"),
    "Dark": (17, "악", "#4B4948"), "Steel": (9, "강철", "#81A8C4"), "Fairy": (18, "페어리", "#D1B6D2"),
}
SV_TYPE_BADGE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/types/generation-ix/scarlet-violet/{}.png"
KO_FONTS = ["C:/Windows/Fonts/malgunbd.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]


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


def type_symbol(badge_png: bytes, size: int):
    """스칼렛바이올렛 배지(200x40, 왼쪽에 흰 심볼)에서 심볼만 흰색+투명 배경으로 추출."""
    from PIL import Image

    im = Image.open(io.BytesIO(badge_png)).convert("RGBA")
    left = im.crop((0, 0, im.height + 8, im.height))
    bg = min(im.getpixel((left.width + 4, 3))[:3])  # 심볼 옆 배경의 가장 어두운 채널
    alpha = Image.new("L", left.size)
    for x in range(left.width):
        for y in range(left.height):
            r, g, b, a = left.getpixel((x, y))
            # 흰색에 가까울수록 불투명 (배경색과의 거리로 안티앨리어싱 유지)
            v = max(0, min(255, int((min(r, g, b) - bg) * 255 / max(1, 255 - bg)))) if a else 0
            alpha.putpixel((x, y), v)
    glyph = Image.new("RGBA", left.size, (255, 255, 255, 0))
    glyph.putalpha(alpha)
    box = glyph.getbbox() or (0, 0, *glyph.size)
    glyph = glyph.crop(box)
    glyph.thumbnail((size, size), Image.LANCZOS)
    return glyph


def build_types(force: bool = False) -> None:
    """나무위키 스타일 타입 배지 생성: 배경색 + 흰색 심볼 + 한글 이름."""
    from PIL import Image, ImageDraw, ImageFont

    out = ASSETS / "types"
    font_path = next((f for f in KO_FONTS if Path(f).exists()), None)
    if not font_path:
        print("[types] 한글 폰트를 찾지 못해 기본 폰트 사용 (글자가 깨질 수 있음)")
    W, H = 120, 40
    font = ImageFont.truetype(font_path, 21) if font_path else ImageFont.load_default()
    ok = 0
    for name, (num, ko, color) in TYPES.items():
        path = out / f"{name}.png"
        if path.exists() and not force:
            ok += 1
            continue
        badge = get(SV_TYPE_BADGE.format(num))
        if not badge:
            print(f"[types] 심볼 없음: {name}")
            continue
        img = Image.new("RGBA", (W, H), color)
        glyph = type_symbol(badge, 28)
        img.alpha_composite(glyph, (8 + (28 - glyph.width) // 2, (H - glyph.height) // 2))
        draw = ImageDraw.Draw(img)
        # 글자는 심볼 오른쪽 영역 가운데
        l, t, r, b = draw.textbbox((0, 0), ko, font=font)
        x = 42 + (W - 42 - 6 - (r - l)) // 2 - l
        y = (H - (b - t)) // 2 - t
        draw.text((x + 1, y + 1), ko, font=font, fill=(0, 0, 0, 70))  # 살짝 그림자
        draw.text((x, y), ko, font=font, fill="white")
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        ok += 1
    print(f"[types] {ok}/{len(TYPES)}")


def build_type_icons(force: bool = False) -> None:
    """타입 심볼만 (흰색, 투명 배경, 가운데 정렬 48x48): assets/types/icons/{Type}.png. 동그란 필터 버튼용."""
    from PIL import Image

    out = ASSETS / "types" / "icons"
    S = 48
    ok = 0
    for name, (num, _, _) in TYPES.items():
        path = out / f"{name}.png"
        if path.exists() and not force:
            ok += 1
            continue
        badge = get(SV_TYPE_BADGE.format(num))
        if not badge:
            continue
        glyph = type_symbol(badge, S)
        img = Image.new("RGBA", (S, S), (255, 255, 255, 0))
        img.alpha_composite(glyph, ((S - glyph.width) // 2, (S - glyph.height) // 2))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        ok += 1
    print(f"[type icons] {ok}/{len(TYPES)}")


def build_type_icons_color(force: bool = False) -> None:
    """배지(assets/types/{Type}.png) 왼쪽 심볼을 배경색 포함 43x43 정사각형 가운데로: assets/types/icons-color/{Type}.png."""
    from PIL import Image

    out = ASSETS / "types" / "icons-color"
    S = 43
    ok = 0
    for name in TYPES:
        src, path = ASSETS / "types" / f"{name}.png", out / f"{name}.png"
        if path.exists() and not force:
            ok += 1
            continue
        if not src.exists():
            continue
        im = Image.open(src).convert("RGBA")
        bg = im.getpixel((0, 0))
        left = im.crop((0, 0, im.height + 2, im.height))
        lo = min(bg[:3])
        # 반 이상 흰색인 픽셀로 심볼 범위를 잡음 (흐린 안티앨리어싱 가장자리는 제외)
        mask = Image.new("L", left.size)
        mask.putdata([255 if (min(p[:3]) - lo) * 2 > 255 - lo else 0 for p in left.getdata()])
        l, t, r, b = mask.getbbox() or (0, 0, *left.size)
        img = Image.new("RGBA", (S, S), bg)
        img.alpha_composite(left, ((S - (r - l)) // 2 - l, (S - (b - t)) // 2 - t))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        ok += 1
    print(f"[type icons color] {ok}/{len(TYPES)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ruleset", default="champions_mc", help="data/ 아래 CSV 폴더")
    ap.add_argument("--rebuild-types", action="store_true", help="타입 배지를 다시 생성")
    args = ap.parse_args()
    data = ROOT / "data" / args.ruleset
    download_pokemon(read_csv(data / "pokemon.csv"))
    download_items(read_csv(data / "items.csv"))
    build_types(force=args.rebuild_types)
    build_type_icons(force=args.rebuild_types)
    build_type_icons_color(force=args.rebuild_types)


if __name__ == "__main__":
    main()
