"""OP.GG 티어(픽률 순위) 받기·저장.

티어 페이지는 쿠키 _opbt(sb=싱글, db=더블)로 포맷을 고르고, 순위 262마리 전체를 페이지 안 데이터로 준다.
원본은 data/raw/opgg/tier/{single|double}/{갱신시각}.json 으로 남기고 RankSnapshot에 적재한다.
"""
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.dex.ids import DexIndex, opgg_pokemon_id
from apps.meta.models import RankSnapshot

URL = 'https://op.gg/pokemon-champions/tier'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'
COOKIE = {'single': 'sb', 'double': 'db'}
FORMAT_KEY = {'single': 'singles', 'double': 'doubles'}
RULESET = 'champions_mc'   # OP.GG는 현재 레귤레이션만 제공
RAW = Path(settings.DATA_DIR) / 'raw' / 'opgg' / 'tier'


def fetch(battle: str) -> dict:
    """{'season': 'm-6', 'format': 'double', 'createdAt': '2026-10-01 09:00', 'rankings': [...]}"""
    req = urllib.request.Request(URL, headers={'User-Agent': UA, 'Cookie': f'_opbt={COOKIE[battle]}'})
    with urllib.request.urlopen(req, timeout=60) as res:
        html = res.read().decode('utf-8')
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    text = ''.join(json.loads(f'"{c}"') for c in chunks)
    start = text.find('"seasons":[{"id"')
    if start < 0:
        raise RuntimeError('티어 데이터를 찾지 못함 (OP.GG 구조 변경?)')
    seasons, _ = json.JSONDecoder().raw_decode(text, start + len('"seasons":'))
    season = seasons[0]
    f = next((x for x in season['formats'] if x['id'] == battle), None)
    if not f:
        raise RuntimeError(f'{battle} 순위가 응답에 없음')
    return {'season': season['id'], 'format': battle, 'createdAt': f['createdAt'], 'rankings': f['rankings']}


def raw_path(data: dict) -> Path:
    stamp = data['createdAt'].replace(':', '').replace(' ', '_')    # 2026-10-01_0900 (윈도우 파일명에 ':' 불가)
    return RAW / data['format'] / f'{stamp}.json'


def save_raw(data: dict) -> Path:
    path = raw_path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return path


def captured_at(data: dict) -> datetime:
    return timezone.make_aware(datetime.strptime(data['createdAt'], '%Y-%m-%d %H:%M'))


def store(data: dict, dex: DexIndex | None = None) -> int:
    """스냅샷 한 벌 적재. 같은 갱신 시각이 이미 있으면 0 (건너뜀)."""
    fmt_key = f'{RULESET}_{FORMAT_KEY[data["format"]]}'
    at = captured_at(data)
    if RankSnapshot.objects.filter(format_key=fmt_key, source='opgg', captured_at=at).exists():
        return 0
    dex = dex or DexIndex.from_db(RULESET)
    rows, seen = [], set()
    for r in data['rankings']:
        pid = opgg_pokemon_id(r['key'], dex)
        if pid in seen:          # 같은 포켓몬의 다른 표기 (aegislash-blade 등)
            continue
        seen.add(pid)
        rows.append(RankSnapshot(ruleset_id=RULESET, format_key=fmt_key, source='opgg', season=data['season'],
                                 captured_at=at, pokemon_key=pid, rank=r['rank'],
                                 season_change=r.get('rankChange')))
    RankSnapshot.objects.bulk_create(rows)
    return len(rows)
