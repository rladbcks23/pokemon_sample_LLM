# CLAUDE.md

포켓몬 챔피언스(Reg M-C) 싱글/더블 파티 빌더. 사용자와는 **한국어**로 대화한다.
설치·실행·API·데이터 출처는 README.md에 있다. 여기에는 작업 규칙과 README에 없는 결정만 적는다.

## 구조
- `back/` Django + DRF (`apps/dex` 게임 데이터, `apps/meta` 사용률·파티·샘플, `apps/api` 화면용 API)
- `front/` Vue 3 + Vite + Element Plus + Pinia. `/api`, `/assets`는 Vite 프록시로 back(8000)에, `/llm`은 llm(8001)에 넘김
- `llm/` 파티 코치 LLM 서버 (FastAPI). `data/` CSV·DB·수집 원본, `assets/` 이미지, `scripts/` 수집·변환
- 찜·내가 만든 파티/샘플은 로그인 없이 브라우저 localStorage에만 저장

## 작업 규칙
- 커밋 메시지: `타입: 내용` (내용은 한글). 타입 = feat / fix / build / chore / ci / docs / style / refactor / test / perf
- 큰 단위로 모으지 말고 작은 수정이 끝날 때마다 바로 커밋한다 (팀 합의, SSAFY 서울 7반)
- **push는 사용자가 요청할 때만** 한다
- 커밋할 때 테스트(`back`에서 `..\.venv\Scripts\python manage.py test`, `llm`을 바꿨으면 `llm` 테스트도)와 `front`의 `npx vite build`가 통과하는지 먼저 확인
- DB를 다시 적재(`load_dex`/`load_meta`)하면 API 서버를 재시작한다 (`names()` 등이 캐시됨)
- 화면을 바꾸면 브라우저에서 실제로 눌러 확인한다

## git에 없는 것
- `data/raw/` (수집 원본, 62MB), `data/pokemon.db` (DB): 데이터는 git에 넣지 않기로 함
  - `data/raw/opgg/tier/`(매일 저장한 픽률 순위 스냅샷)는 다시 받을 수 없으니 지우지 말 것
  - 새 환경에서는 `scripts/collect_samples.py`로 수집 → `migrate` → `load_dex` → `load_meta`
- `assets/`(이미지)는 git에 포함한다. `assets/types/icons-color/`는 사용자가 직접 편집한 타입 아이콘

## 데이터 규칙 (load_meta / API)
- 리플레이에는 SP가 공개되지 않는다. 6마리 육성이 모두 같은 VGCPastes 팀이 있고 SP가 한 가지일 때만 채운다
  (`sp_from`). 확실하지 않으면 추측해서 채우지 않는다
- 배울 수 없는 기술이 있는 파티는 `is_legal=False`로 숨김. 비어 있는 칸이 있는 OP.GG 팀은 적재하지 않음
- 성능이 같은 폼(파밀리쥐·비비용·포트데스·그우린차·시비꼬)은 하나로, 무보정 성격은 성실 하나로
- 사용률은 항목마다 10위까지. 메가는 "메가 전 폼 + 메가스톤"으로 저장하고 화면에서 메가 폼으로 보여 줌
- 기술·특성·도구 한글 설명은 나무위키 기준(`scripts/collect_namuwiki.py`), 기술 이름은 최신 게임 이름

## LLM (다음 단계)
- **유료 API는 쓰지 않는다** (쓴 만큼 요금이 나가는 Claude API 등). 학습 데이터는 DB로 만들고, 코치 채팅도 로컬 Qwen으로 옮길 예정
- 사실(종족값·기술·사용률 등)은 외우지 않고 back API를 도구로 조회
- 서버는 Django와 분리 (`llm/`, FastAPI + SSE, 포트 8001). 파티 빌딩의 CoachChat이 `/llm/chat`에 붙어 있다
  - 지금 provider는 Claude API(`llm/providers/claude.py`, 키가 있어야 동작). 로컬 Qwen provider로 바꿀 것. 도구는 `llm/agent/tools.py`
  - 도구 결과는 짧게 유지한다 (로컬 4B 모델의 문맥 길이·학습 길이 때문). 샘플 검색 3개, SP는 0 생략, 상성은 약점 있는 타입만
  - 테스트는 `llm`에서 `..\.venv\Scripts\python -m unittest` (모델·back은 가짜라 API 키·DB 없이 돈다)
- LoRA 파인튜닝: **`Qwen/Qwen3.5-4B`** (Apache 2.0). 이미지도 받는 모델이라 Unsloth `FastModel`로 불러온다
  - 학습 데이터: `llm/training/make_data.py` (back을 프로세스 안에서 직접 불러 실제 도구 결과로 대화 생성, 서버 불필요)
    - 1순위는 파티 빌딩·샘플 제작. 정답은 OP.GG 상위 파티·VGCPastes 대회 팀·OP.GG/대회 샘플
    - Showdown 리플레이는 쓰지 않는다 (평균 레이팅 약 1100~1200, 인게임 메타와 다름)
    - 답변 숫자는 도구 결과에 있는 것만 (없으면 버림). `train.jsonl`/`eval.jsonl`은 git 제외
  - 길이: 시스템 프롬프트+도구 설명만 약 2,400토큰, 샘플 대화 약 3,100~4,500, 파티 빌딩 대화 약 5,500토큰
  - 노트북은 GPU별로 따로: `llm/training/finetune_laptop`(4050)·`finetune_home`(3060)·`finetune_colab`(T4). 설정 셀만 다름
    - 집 PC(RTX 3060 12GB)·Colab(T4): 4bit QLoRA, 길이 8192 → 전부 학습
    - 노트북(RTX 4050 6GB): 4bit QLoRA, 길이 4096 → 샘플 대화만 들어감
  - `Qwen3.5-9B`는 학습에 VRAM 약 22GB가 필요해 집 PC·무료 Colab(T4)에서 불가
  - 모델은 Apache 2.0만 쓴다. 비교용 후보: `kakaocorp/kanana-2-3b-instruct`(라이선스 확인 필요), `skt/A.X-4.0-Light`
  - EXAONE 제외: 라이선스가 연구 목적 전용이라 무료 공개 서비스·외부 배포도 막힘
  - 파인튜닝은 사실 암기가 아니라 도구 호출 방식과 파티 판단을 가르치는 용도
- API 키·설정은 `llm/.env`에 두고 git에 올리지 않는다
