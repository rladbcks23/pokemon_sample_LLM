"""샘플 데이터 수집: Smogon 사용률 통계 / Showdown 리플레이 / OP.GG.

원본 그대로 data/raw/ 아래에 저장만 하고, DB 적재는 별도 스크립트에서 한다.

사용법:
    python scripts/collect_samples.py all
    python scripts/collect_samples.py smogon --month 2026-08
    python scripts/collect_samples.py replays --count 200
    python scripts/collect_samples.py opgg --pages 10
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
DELAY = 1.0  # 요청 간격(초). 서버 부담을 줄이기 위해 줄이지 말 것

# 포맷 ID (Showdown 기준). 레귤레이션이 바뀌면 여기만 수정
SMOGON_FORMATS = ["gen9championsvgc2026regmb", "gen9championsvgc2026regmbbo3", "gen9championsbssregmb"]
SMOGON_CUTOFF = 1630  # 레이팅 기준 (0 / 1500 / 1630 / 1760)
REPLAY_FORMATS = ["gen9championsvgc2026regmcbo3", "gen9championsvgc2026regmc", "gen9championsbssregmc"]


def fetch(url: str) -> bytes:
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()


def fetch_json(url: str):
    return json.loads(fetch(url))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Smogon 월별 사용률 통계 (chaos JSON: 사용률, 도구/특성/기술/SP배분/동료 비율)
# ---------------------------------------------------------------------------

def collect_smogon(month: str) -> None:
    out = RAW / "smogon" / month
    for fmt in SMOGON_FORMATS:
        path = out / f"{fmt}-{SMOGON_CUTOFF}.json"
        if path.exists():
            print(f"[smogon] skip {path.name} (이미 있음)")
            continue
        url = f"https://www.smogon.com/stats/{month}/chaos/{fmt}-{SMOGON_CUTOFF}.json"
        try:
            data = fetch(url)
        except urllib.error.HTTPError as e:
            print(f"[smogon] {fmt}: HTTP {e.code} (해당 월 통계 없음)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        info = json.loads(data)["info"]
        print(f"[smogon] {fmt}: {info['number of battles']} battles → {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Showdown 리플레이 (양쪽 6마리, 선출, 선봉, 메가 사용자, 승패. Bo3 포맷은 오픈 팀시트로 육성 정보 포함)
# ---------------------------------------------------------------------------

def collect_replays(count: int) -> None:
    for fmt in REPLAY_FORMATS:
        out = RAW / "showdown" / "replays" / fmt
        out.mkdir(parents=True, exist_ok=True)
        have = {p.stem for p in out.glob("*.json")}
        ids, before = [], None
        # 검색 API는 한 번에 51개(마지막 1개는 다음 페이지 확인용)
        while len(ids) < count:
            url = f"https://replay.pokemonshowdown.com/search.json?format={fmt}"
            if before:
                url += f"&before={before}"
            page = fetch_json(url)
            ids += [r["id"] for r in page[:50]]
            if len(page) <= 50:
                break
            before = page[49]["uploadtime"]
        ids = ids[:count]
        new = [i for i in ids if i not in have]
        for n, rid in enumerate(new, 1):
            try:
                save_json(out / f"{rid}.json", fetch_json(f"https://replay.pokemonshowdown.com/{rid}.json"))
            except urllib.error.HTTPError as e:
                print(f"[replay] {rid}: HTTP {e.code}")
            if n % 50 == 0:
                print(f"[replay] {fmt}: {n}/{len(new)}")
        print(f"[replay] {fmt}: 신규 {len(new)}개, 총 {len(list(out.glob('*.json')))}개")


# ---------------------------------------------------------------------------
# OP.GG (공식 API 없음 → 페이지에 포함된 Next.js 데이터에서 추출)
# ---------------------------------------------------------------------------

OPGG = "https://op.gg/pokemon-champions"


def opgg_payload(path: str) -> str:
    html = fetch(f"{OPGG}/{path}").decode("utf-8")
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    return "".join(json.loads(f'"{c}"') for c in chunks)


def extract_array(text: str, key: str) -> list:
    """payload에서 "key":[...] 배열을 찾아 JSON으로 파싱."""
    start = text.find(f'"{key}":[')
    if start < 0:
        return []
    arr, _ = json.JSONDecoder().raw_decode(text, start + len(key) + 3)
    return arr


def collect_opgg(pages: int) -> None:
    out = RAW / "opgg"
    for fmt in ("SINGLE", "DOUBLE"):
        for kind, key in (("replica-teams", "teamCodes"), ("sample-builds", "samples")):
            rows, seen = [], set()
            for page in range(1, pages + 1):
                text = opgg_payload(f"{kind}?battleFormat={fmt}&page={page}")
                items = extract_array(text, key)
                items = [x for x in items if x["id"] not in seen]
                if not items:
                    break
                seen.update(x["id"] for x in items)
                rows += items
            save_json(out / f"{kind}_{fmt.lower()}.json", rows)
            print(f"[opgg] {kind} {fmt}: {len(rows)}개")

    # 티어(사용률 순위). 퍼센트는 없고 순위와 순위 변동만 제공. 페이지는 싱글만 포함
    # (더블 순위는 collect_opgg_ranked 결과의 overview.ranking에 포켓몬별로 들어 있음)
    text = opgg_payload("tier")
    seasons = extract_array(text, "seasons")
    save_json(out / "tier.json", seasons)
    for s in seasons:
        for f in s["formats"]:
            print(f"[opgg] tier {s['label']} {f['id']}: {len(f['rankings'])}위까지 ({f['createdAt']})")


RANKED_ACTION = "getRankedBattlePokemonOverviewDetailData"


def find_action_id(page_path: str, action_name: str) -> str:
    """Next.js 서버 액션 ID는 사이트 배포마다 바뀌므로 JS 번들에서 매번 찾는다."""
    html = fetch(f"{OPGG}/{page_path}").decode("utf-8")
    for src in dict.fromkeys(re.findall(r'src="(https://[^"]+/_next/static/chunks/[^"]+\.js)"', html)):
        js = fetch(src).decode("utf-8", "ignore")
        m = re.search(r'createServerReference\)\("([0-9a-f]{40,})"[^;]{0,200}?"' + action_name + '"', js)
        if m:
            return m.group(1)
    raise RuntimeError(f"서버 액션 {action_name}을 찾지 못함 (사이트 구조 변경?)")


def call_action(page_path: str, action_id: str, arg: dict):
    time.sleep(DELAY)
    req = urllib.request.Request(
        f"{OPGG}/{page_path}", method="POST", data=json.dumps([arg]).encode(),
        headers={"User-Agent": UA, "Next-Action": action_id, "Accept": "text/x-component",
                 "Content-Type": "text/plain;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=60) as res:
        body = res.read().decode("utf-8")
    # 응답은 "0:{메타}\n1:{데이터}" 형식
    for line in body.split("\n"):
        if line.startswith("1:"):
            return json.loads(line[2:])
    return None


def collect_opgg_ranked(limit: int | None) -> None:
    """인게임 랭크배틀 통계: 포켓몬별 기술/도구/특성/성격/SP배분/동료/상성/메가 사용률."""
    seasons = json.loads((RAW / "opgg" / "tier.json").read_text(encoding="utf-8"))
    season = seasons[0]
    keys = [r["key"] for f in season["formats"] for r in f["rankings"]]
    keys = list(dict.fromkeys(keys))[:limit]
    action_id = find_action_id(f"pokedex/{keys[0]}", RANKED_ACTION)
    print(f"[opgg] ranked: {season['label']} 포켓몬 {len(keys)}마리, action={action_id[:10]}…")

    for fmt in ("single", "double"):
        out = RAW / "opgg" / "ranked" / season["id"] / fmt
        out.mkdir(parents=True, exist_ok=True)
        ok = 0
        for n, key in enumerate(keys, 1):
            path = out / f"{key}.json"
            if path.exists():
                ok += 1
                continue
            try:
                data = call_action(f"pokedex/{key}", action_id, {
                    "format": fmt, "pokemonKey": key, "fallbackPokemonKey": "$undefined", "locale": "en"})
            except urllib.error.HTTPError as e:
                print(f"[opgg] ranked {fmt} {key}: HTTP {e.code}")
                continue
            if not data or not data.get("overview", {}).get("detail"):
                continue  # 해당 포맷 데이터 없음
            save_json(path, data)
            ok += 1
            if n % 50 == 0:
                print(f"[opgg] ranked {fmt}: {n}/{len(keys)}")
        print(f"[opgg] ranked {fmt}: {ok}마리 저장")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["smogon", "replays", "opgg", "opgg-ranked", "all"])
    ap.add_argument("--limit", type=int, default=None, help="opgg-ranked: 포켓몬 수 제한 (테스트용)")
    ap.add_argument("--month", default="2026-08", help="Smogon 통계 월 (YYYY-MM)")
    ap.add_argument("--count", type=int, default=200, help="포맷별 리플레이 수")
    ap.add_argument("--pages", type=int, default=10, help="OP.GG 목록 페이지 수 (페이지당 10개)")
    args = ap.parse_args()

    if args.source in ("smogon", "all"):
        collect_smogon(args.month)
    if args.source in ("replays", "all"):
        collect_replays(args.count)
    if args.source in ("opgg", "all"):
        collect_opgg(args.pages)
    if args.source in ("opgg-ranked", "all"):
        collect_opgg_ranked(args.limit)


if __name__ == "__main__":
    main()
