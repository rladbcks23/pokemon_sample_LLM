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

## 실행 (back/ 에서)
| 대상 | 명령 | 주소 |
|---|---|---|
| API 서버 | `..\.venv\Scripts\python manage.py runserver` | http://localhost:8000/api/ |
| Admin | (위와 같음, `createsuperuser` 필요) | http://localhost:8000/admin/ |
| DB 확인 페이지 | `..\.venv\Scripts\python -m streamlit run ui/db_viewer.py` | http://localhost:8501/check |

## 커밋 규칙
`타입: 내용` — feat / fix / build / chore / ci / docs / style / refactor / test / perf
