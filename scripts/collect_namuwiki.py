"""나무위키에서 기술·특성·도구의 한글 설명(최신 게임 설명문)을 가져와 data/raw/namuwiki/*.json 으로 저장.

    python scripts/collect_namuwiki.py all          # 기술 + 특성 + 도구
    python scripts/collect_namuwiki.py moves        # 하나만
    python scripts/collect_namuwiki.py apply        # 받은 설명을 data/champions_*/ CSV의 short_desc에 채움

- 기술: "{기술}(포켓몬스터)" 문서 정보 상자의 설명 (위력·명중·PP 아래 칸)
- 특성: "포켓몬스터/특성/ㄱ" ~ "ㅎ", "A~Z" 목록 문서의 각 항목 "(일본어 / 영어)" 다음 문장
- 도구: "{도구}" 문서(대개 분류 문서의 한 항목으로 넘겨줌)의 "설명" 칸.
  나무위키에 설명 칸이 없는 도구(나무열매 등)는 PokeAPI의 공식 한국어 설명(가장 최근 버전),
  메가스톤은 공식 설명 틀("○○에게 지니게 하면 배틀 중에 메가진화할 수 있는 신기한 메가스톤의 하나.")
- 기술 정보 상자의 "변경점 챔피언스: …"는 설명과 따로 champions 로 저장
저장 모양: {id: {"desc": 설명, "src": namuwiki|pokeapi|template, ("champions": 챔피언스 변경점)}}
나무위키 robots.txt는 /w/ 문서 열람을 허용함. 요청 사이에 1초 넘게 쉼.
이미 받은 항목은 건너뜀(중간에 끊겨도 이어서 받기). 다시 받으려면 json 파일을 지우고 실행.
"""
import argparse
import csv
import html
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "raw" / "namuwiki"
WIKI = "https://namu.wiki"
UA = "Mozilla/5.0 (pokemon-sample-builder personal project)"
DELAY = 1.2
RULESETS = ("champions_mc", "champions_mb")

_last = 0.0


def fetch(title: str) -> tuple[str, str] | None:
    """문서 HTML과 넘겨준 문단 이름(#anchor). 없는 문서면 None."""
    global _last
    url = f"{WIKI}/w/{urllib.parse.quote(title)}"
    anchor = ""
    for _ in range(4):                           # 넘겨주기(302) 따라가며 #문단 기억
        wait = DELAY - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        opener = urllib.request.build_opener(NoRedirect)
        try:
            res = opener.open(req, timeout=30)
            return res.read().decode("utf-8"), anchor
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers["Location"]
                path, _, frag = loc.partition("#")
                anchor = urllib.parse.unquote(frag) or anchor
                url = urllib.parse.urljoin(WIKI, path)
                continue
            if e.code == 404:
                return None
            if e.code == 429:                    # 너무 빠름: 쉬었다가 다시
                time.sleep(30)
                continue
            raise
    return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def to_text(fragment: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", fragment, flags=re.S)
    # 링크·글꼴 같은 글자 안 태그는 그냥 지우고("<a>견디기</a>도" → "견디기도"), 나머지 태그는 띄움
    t = re.sub(r"</?(a|strong|b|i|em|u|del|sup|sub|font)\b[^>]*>", "", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def clean(desc: str) -> str:
    desc = re.sub(r"\[\d+\]", "", desc)          # 각주 번호
    desc = re.sub(r"\s+", " ", desc).strip().lstrip("★ ")
    # 세대마다 설명이 다르면 가장 최근 것만 ("3~8세대: … 9세대: …" → 9세대 설명)
    parts = re.split(r"(?:^|\s)[\d~·,]+세대(?:\s*이후)?\s*:\s*", desc)
    if len(parts) > 1 and not parts[0]:     # 설명이 "N세대:"로 시작할 때만
        desc = parts[-1].strip()
    return desc


def load(kind: str) -> dict:
    p = OUT / f"{kind}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save(kind: str, data: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{kind}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def rows_of(kind: str) -> dict:
    """두 레귤레이션 CSV의 ID → 행 (한글 이름이 있는 것만)."""
    out = {}
    for rs in RULESETS:
        with open(DATA / rs / f"{kind}.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["name_ko"]:
                    out.setdefault(r["id"], r)
    return out


def split_change(desc: str) -> tuple[str, str]:
    """'설명 … 변경점 챔피언스: PP 10 → 5' → (설명, 챔피언스 변경점)."""
    body, _, change = desc.partition(" 변경점 ")
    m = re.search(r"챔피언스\s*:\s*(.+?)(?=\s+\S+\s*:|$)", change)
    return body.strip(), (m.group(1).strip() if m else "")


def entry_text(page: str, ko: str, en: str) -> str:
    """문서에서 그 항목 부분: '{이름} [편집] {이름} 일본어 / 영어 …' 또는 정보 상자 '{이름} 일본어 / 영어 …'.
    영어 이름이 바로 뒤에 나와야 그 항목으로 인정 (동음이의 문서를 잘못 읽지 않게)."""
    text = to_text(page)
    for m in re.finditer(re.escape(ko), text):
        chunk = text[m.start():m.start() + 1500]
        if en.lower() in chunk[:160].lower():
            return chunk
    return ""


# ---------------------------------------------------------------- 기술
def move_desc(page: str, ko: str, en: str) -> str:
    """기술 정보 상자: '{기술} 일본어 / 영어 {타입} | {분류} 위력 명중 PP {설명} #태그'."""
    chunk = entry_text(page, ko, en)
    m = re.search(r"PP \d+ (.+?)(?= #| \d+ \. |$)", chunk)
    return m.group(1) if m else ""


def collect_moves() -> None:
    got = load("moves")
    todo = {i: r for i, r in rows_of("moves").items() if i not in got}
    print(f"[moves] {len(got)}개 있음, {len(todo)}개 받기")
    for n, (mid, r) in enumerate(todo.items(), 1):
        desc = ""
        for title in (f"{r['name_ko']}(포켓몬스터)", r["name_ko"]):
            res = fetch(title)
            if res and (desc := move_desc(res[0], r["name_ko"], r["name"])):
                break
        body, change = split_change(desc)
        body, change = clean(body), clean(change)
        got[mid] = {"desc": body, "champions": change, "src": "namuwiki" if body else ""}
        print(f"  {n}/{len(todo)} {r['name_ko']}: {body[:40] or '(없음)'}{' · 변경 ' + change if change else ''}")
        if n % 20 == 0:
            save("moves", got)
    save("moves", got)


# ---------------------------------------------------------------- 특성
ABILITY_PAGES = ["A~Z", *"ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"]


def collect_abilities() -> None:
    want = rows_of("abilities")
    by_ko = {r["name_ko"].replace(" ", ""): k for k, r in want.items()}
    got = load("abilities")
    for p in ABILITY_PAGES:
        res = fetch(f"포켓몬스터/특성/{p}")
        if not res:
            continue
        text = to_text(res[0])
        # "2.1. 가뭄 [편집] 가뭄 (ひでり / Drought) 등장했을 때 날씨를 맑음으로 만든다. 첫 등장 3세대 ..."
        for m in re.finditer(r"\d+\.\d+\. ([^\[]{1,20}?) \[편집\] [^(]{1,24}\(([^)/]+) / ([^)]+)\) (.{1,300}?) 첫 등장", text):
            ko = re.sub(r"[\s★]", "", m.group(1))     # 나무위키는 띄어 씀 (보이지 않는주먹)
            if ko in by_ko:
                got[by_ko[ko]] = {"desc": clean(m.group(4)), "src": "namuwiki"}
        print(f"[abilities] {p}: 누적 {len(got)}/{len(want)}")
    save("abilities", got)
    missing = [r["name_ko"] for k, r in want.items() if k not in got]
    print(f"[abilities] 못 찾음 {len(missing)}: {', '.join(missing)}")


# ---------------------------------------------------------------- 도구
POKEAPI = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/"
# 나무위키·PokeAPI 둘 다 없는 도구 (9세대 신규 등): 게임 설명문 직접 입력
MANUAL_ITEMS = {
    "fairyfeather": "신비한 힘을 지닌 화사한 깃털. 지니게 하면 페어리타입 기술의 위력이 올라간다.",
}


def pokeapi_item_texts() -> dict:
    """PokeAPI의 공식 한국어 도구 설명 (가장 최근 버전). 한글 이름 → 설명."""
    def get(name):
        with urllib.request.urlopen(POKEAPI + name, timeout=60) as r:
            return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
    ko_name = {r["item_id"]: r["name"] for r in get("item_names.csv") if r["local_language_id"] == "3"}
    best = {}
    for r in get("item_flavor_text.csv"):
        if r["language_id"] == "3" and r["item_id"] in ko_name:
            vg = int(r["version_group_id"])
            if vg >= best.get(r["item_id"], (0, ""))[0]:
                best[r["item_id"]] = (vg, re.sub(r"\s+", " ", r["flavor_text"]).strip())
    return {ko_name[i]: t for i, (_, t) in best.items()}


def item_desc(page: str, ko: str, en: str) -> str:
    """도구 항목: '… 설명 {설명} 가격 …'."""
    chunk = entry_text(page, ko, en)
    m = re.search(r" 설명 (.+?) (?:가격|등장|입수|비고|분류) ", chunk)
    return clean(m.group(1)) if m else ""


def collect_items() -> None:
    got = load("items")
    rows = rows_of("items")
    pokemon_ko = {r["name"]: r["name_ko"] for r in rows_of("pokemon").values()}
    todo = {i: r for i, r in rows.items() if not got.get(i, {}).get("desc")}
    print(f"[items] {len(rows) - len(todo)}개 있음, {len(todo)}개 받기")
    official = pokeapi_item_texts()
    for n, (iid, r) in enumerate(todo.items(), 1):
        ko, desc, src = r["name_ko"], "", ""
        if r["mega_from"]:      # 메가스톤은 설명이 모두 같은 틀
            base = pokemon_ko.get(r["mega_from"], r["mega_from"]).split("-")[0]
            desc, src = f"{base}에게 지니게 하면 배틀 중에 메가진화할 수 있는 신기한 메가스톤의 하나.", "template"
        else:
            for title in (ko, f"{ko}(포켓몬스터)"):
                res = fetch(title)
                if res and (desc := item_desc(res[0], ko, r["name"])):
                    src = "namuwiki"
                    break
            if not desc and official.get(ko):
                desc, src = official[ko], "pokeapi"
            if not desc and iid in MANUAL_ITEMS:
                desc, src = MANUAL_ITEMS[iid], "manual"
        got[iid] = {"desc": desc, "src": src}
        print(f"  {n}/{len(todo)} {ko}: [{src or '없음'}] {desc[:40]}")
        if n % 20 == 0:
            save("items", got)
    save("items", got)


# ---------------------------------------------------------------- CSV에 채우기
def apply() -> None:
    for kind in ("moves", "abilities", "items"):
        desc = load(kind)
        for rs in RULESETS:
            p = DATA / rs / f"{kind}.csv"
            raw = p.read_text(encoding="utf-8-sig")
            nl = "\r\n" if "\r\n" in raw else "\n"
            rows = list(csv.DictReader(io.StringIO(raw)))
            filled = 0
            for r in rows:
                d = desc.get(r["id"], {}).get("desc")
                if d:
                    r["short_desc"] = d
                    filled += 1
            out = io.StringIO()
            w = csv.DictWriter(out, fieldnames=list(rows[0].keys()), lineterminator=nl)
            w.writeheader()
            w.writerows(rows)
            p.write_text(out.getvalue(), encoding="utf-8-sig", newline="")
            print(f"[apply] {rs}/{kind}.csv: {filled}/{len(rows)}개 설명")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["all", "moves", "abilities", "items", "apply"])
    a = ap.parse_args()
    if a.what in ("all", "abilities"):
        collect_abilities()
    if a.what in ("all", "items"):
        collect_items()
    if a.what in ("all", "moves"):
        collect_moves()
    if a.what == "apply":
        apply()


if __name__ == "__main__":
    main()
