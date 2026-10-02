# Pokémon Champions 파티 빌더

포켓몬 챔피언스(싱글/더블) 기준으로 6마리 파티, 역할, 기믹(메가진화 등) 운용, 선출 가이드를 제안하는 웹 서비스.
사실 정보는 DB와 도구로 조회·계산하고, LLM은 의도 해석·도구 호출·전략 설명을 맡는다.

## 폴더
```
back/      Django + DRF API 서버 (게임 데이터, 메타/파티, 분석 도구) + DB 확인 페이지(ui/)
front/     Vue 3 + Element Plus 화면
llm/       LLM 서버 (에이전트, provider, 파인튜닝)
data/      공용 데이터: champions_*/ (게임 데이터 CSV), raw/ (수집 원본, git 제외), pokemon.db (git 제외)
assets/    포켓몬·도구·타입 아이콘 (scripts/download_assets.py로 받음, types/icons-color는 직접 편집)
scripts/   데이터 수집·변환 스크립트
```

## 화면
| 메뉴 | 내용 |
|---|---|
| 포켓몬 | 사용률 순위 목록(싱글/더블), 상세: 종족값·형태(폼·메가)·특성·타입 상성·사용률 10위·배우는 기술 |
| 샘플 | 포켓몬 샘플(OP.GG 샘플·대회 팀·OP.GG 팀 멤버) / 파티 샘플(OP.GG 레플리카·VGCPastes 대회 팀·리플레이) |
| 파티 빌딩 | 6칸 파티, 포켓몬·내 샘플·공개 샘플에서 추가, 약점표, 파티 코치(LLM 자리) |
| 샘플 제작 | 도구·특성·성격·기술·SP 배분, 실수치, 적합성 검사, 사용률 참고 |
| 스피드표 | Lv50 스피드 실수치 (임시) |
| 마이페이지 | 찜한·내가 만든 파티/샘플 (브라우저 localStorage에만 저장) |

샘플 카드를 누르면 상세보기 창(실수치, 도구·특성·성격·기술 설명)이 뜬다. 랭킹 화면은 메뉴에서 숨김(`/ranking`).

## 데이터 출처
| 출처 | 들어가는 곳 | SP |
|---|---|---|
| Showdown(챔피언스 mod) + PokeAPI | 게임 데이터 CSV (`data/champions_*`) | — |
| 나무위키 (없으면 PokeAPI 공식 설명) | 기술·특성·도구 한글 설명 | — |
| OP.GG 인게임 랭크 | 사용률 순위·기술·도구·특성·성격·SP 배분 % | — |
| OP.GG 샘플 / 레플리카 팀 | 포켓몬 샘플 / 파티 샘플 | 있음 |
| VGCPastes (대회 팀 pokepaste) | 파티 샘플, 멤버는 포켓몬 샘플로도 | 있음 |
| Showdown 리플레이 | 파티 샘플 (출전·선봉·메가·승패) | 비공개 |
| Smogon 월별 통계 | 사용률 (M-B) | — |

적재 규칙 (`load_meta`)
- 배울 수 없는 기술이 있는 파티는 `is_legal=False`로 표시하고 목록에서 숨긴다.
- OP.GG 레플리카 팀은 6마리 모두 SP·도구·성격·기술 4개가 있어야 넣는다.
- 포켓몬 샘플은 다 채워진 육성만: 도구·특성·성격, 서로 다른 기술 4개(챔피언스에 있는 기술), SP 합계 64 이상. 같은 육성은 하나로.
- 성능이 같은 폼(파밀리쥐·비비용·포트데스·그우린차·시비꼬)은 하나로 합치고, 무보정 성격은 성실 하나로 본다.
- 사용률 항목은 10위까지, 성격·SP 배분은 1% 이상, 0.1% 미만은 생략.

## 처음 세팅
```bash
python -m venv .venv
.venv\Scripts\pip install -r back/requirements.txt -r scripts/requirements.txt
```

### 데이터 준비
```bash
# 수집 원본 (Smogon 통계, Showdown 리플레이, OP.GG, VGCPastes 대회 팀)
.venv\Scripts\python scripts/collect_samples.py all
# OP.GG 샘플·레플리카 팀 전부 (기본 10페이지, 최대 100페이지)
.venv\Scripts\python scripts/collect_samples.py opgg --pages 100
# VGCPastes만 (이미 받은 팀은 건너뜀, --regs champions_mb 로 M-B도)
.venv\Scripts\python scripts/collect_samples.py vgcpastes
# 아이콘
.venv\Scripts\python scripts/download_assets.py
```
게임 데이터 CSV(`data/champions_*`)는 저장소에 포함돼 있다. 새 레귤레이션은 `scripts/export_champions.js`로 다시 만든다.

기술·특성·도구 한글 설명(CSV의 `short_desc`)은 나무위키 기준이다. 다시 받으려면:
```bash
.venv\Scripts\python scripts/collect_namuwiki.py all     # data/raw/namuwiki/*.json (15분쯤)
.venv\Scripts\python scripts/collect_namuwiki.py apply   # CSV에 채움 → load_dex
```
나무위키에 설명 칸이 없는 도구는 PokeAPI의 공식 한국어 설명을 쓴다. 나무위키 글은 CC BY-NC-SA 2.0 KR.

Showdown 리플레이에는 SP가 공개되지 않는다(오픈 팀시트도 노력치는 숨김). `load_meta`는 6마리 육성이 모두 같은
VGCPastes 대회 팀이 있고 그 SP가 한 가지일 때만 리플레이 멤버에 SP를 넣고 `sp_from`에 출처를 남긴다.

### DB 만들기
```bash
cd back
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py load_dex    # 게임 데이터
..\.venv\Scripts\python manage.py load_meta   # 사용률, 파티, 육성형
```
API 서버는 이름 등을 캐시하므로 DB를 다시 적재하면 API 서버를 재시작한다.

### 픽률 순위 매일 저장
OP.GG 순위는 하루 안팎으로 갱신된다. 매일 한 번 실행하면 순위를 스냅샷으로 쌓고, 랭킹 화면은 직전 스냅샷 대비 변동을 보여준다.
같은 갱신 시각이면 건너뛰므로 여러 번 실행해도 된다. 원본은 `data/raw/opgg/tier/`에 남는다.
```bash
cd back
..\.venv\Scripts\python manage.py snapshot_ranking
```

## 실행
| 대상 | 위치 | 명령 | 주소 |
|---|---|---|---|
| 화면 (Vue) | `front/` | `npm install` 후 `npm run dev` | http://localhost:5173 |
| API 서버 | `back/` | `..\.venv\Scripts\python manage.py runserver` | http://localhost:8000/api/ |
| Admin | `back/` | (위와 같음, `createsuperuser` 필요) | http://localhost:8000/admin/ |
| DB 확인 페이지 | `back/` | `..\.venv\Scripts\python -m streamlit run ui/db_viewer.py` | http://localhost:8501/check |

화면은 `/api`, `/assets` 요청을 API 서버(8000)로 넘기므로 API 서버를 같이 띄워야 한다.

### API
| 주소 | 내용 |
|---|---|
| `GET /api/ranking/?format=doubles` | 인게임 픽률 순위, 직전 스냅샷 대비 변동 |
| `GET /api/pokemon/?format=` | 포켓몬 목록 (메가 폼은 기본 폼의 `megas`에) |
| `GET /api/pokemon/{id}/` | 폼(기본+메가)·다른 형태, 싱글·더블 사용률 10위, 배우는 기술(설명 포함) |
| `GET /api/teams/?format=&source=&q=&page=` | 파티 샘플 (10개씩, OP.GG 먼저). source: opgg_replica / vgcpastes / showdown_replay |
| `GET /api/teams/{id}/` | 파티 상세 + 약점표 (메가 멤버는 메가 폼으로, `base`에 진화 전 폼) |
| `GET /api/samples/?format=&source=&q=&page=&size=` | 포켓몬 샘플 (30개씩). source: opgg_sample / vgcpastes_team / opgg_team |
| `GET /api/options/` | 도구(설명)·성격·타입·타입 상성표 |
| `POST /api/validate/` | 샘플 적합성 검사 + 실수치 |

## 커밋 규칙
`타입: 내용` — feat / fix / build / chore / ci / docs / style / refactor / test / perf
