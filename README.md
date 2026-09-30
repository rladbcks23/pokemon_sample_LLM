# Pokémon Champions 파티 빌더

포켓몬 챔피언스(싱글/더블) 기준으로 6마리 파티, 역할, 기믹(메가진화 등) 운용, 선출 가이드를 제안하는 웹 서비스.
사실 정보는 DB와 도구로 조회·계산하고, LLM은 의도 해석·도구 호출·전략 설명을 맡는다.

## 폴더
```
back/      Django + DRF API 서버 (게임 데이터, 메타/파티, 분석 도구) + DB 확인 페이지(ui/)
front/     Vue 3 + Element Plus 화면
llm/       LLM 서버 (에이전트, provider, 파인튜닝)
data/      공용 데이터: champions_*/ (게임 데이터 CSV), raw/ (수집 원본, git 제외), pokemon.db (git 제외)
assets/    포켓몬·도구·타입 아이콘 (git 제외)
scripts/   데이터 수집·변환 스크립트
```

## 처음 세팅
```bash
python -m venv .venv
.venv\Scripts\pip install -r back/requirements.txt -r scripts/requirements.txt
```

### 데이터 준비
```bash
# 수집 원본 (Smogon 통계, Showdown 리플레이, OP.GG)
.venv\Scripts\python scripts/collect_samples.py all
# 아이콘
.venv\Scripts\python scripts/download_assets.py
```
게임 데이터 CSV(`data/champions_*`)는 저장소에 포함돼 있다. 새 레귤레이션은 `scripts/export_champions.js`로 다시 만든다.

### DB 만들기
```bash
cd back
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py load_dex    # 게임 데이터
..\.venv\Scripts\python manage.py load_meta   # 사용률, 파티, 육성형
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
| `GET /api/ranking/?format=doubles` | 인게임 픽률 순위, 직전 시즌 대비 변동 |
| `GET /api/pokemon/?format=` | 포켓몬 목록 (메가 폼 제외) |
| `GET /api/pokemon/{id}/` | 폼별 정보, 싱글·더블 사용률, 배우는 기술 |
| `GET /api/teams/?format=&source=&q=&page=` | 파티 목록 (8개씩) |
| `GET /api/teams/{id}/` | 파티 상세 + 약점표 |
| `GET /api/options/` | 도구·성격·타입·타입 상성표 |
| `POST /api/validate/` | 샘플 적합성 검사 + 실수치 |

## 커밋 규칙
`타입: 내용` — feat / fix / build / chore / ci / docs / style / refactor / test / perf
