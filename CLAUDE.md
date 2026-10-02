# CLAUDE.md

포켓몬 챔피언스(Reg M-C) 싱글/더블 파티 빌더. 사용자와는 **한국어**로 대화한다.
설치·실행·API·데이터 출처는 README.md에 있다. 여기에는 작업 규칙과 README에 없는 결정만 적는다.

## 구조
- `back/` Django + DRF (`apps/dex` 게임 데이터, `apps/meta` 사용률·파티·샘플, `apps/api` 화면용 API)
- `front/` Vue 3 + Vite + Element Plus + Pinia. `/api`, `/assets`는 Vite 프록시로 back(8000)에 넘김
- `llm/` LLM 서버 자리 (아직 README만). `data/` CSV·DB·수집 원본, `assets/` 이미지, `scripts/` 수집·변환
- 찜·내가 만든 파티/샘플은 로그인 없이 브라우저 localStorage에만 저장

## 작업 규칙
- 커밋 메시지: `타입: 내용` (내용은 한글). 타입 = feat / fix / build / chore / ci / docs / style / refactor / test / perf
- 큰 단위로 모으지 말고 작은 수정이 끝날 때마다 바로 커밋한다 (팀 합의, SSAFY 서울 7반)
- **push는 사용자가 요청할 때만** 한다
- 커밋할 때 테스트(`back`에서 `..\.venv\Scripts\python manage.py test`)와 `front`의 `npx vite build`가 통과하는지 먼저 확인
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
- 1단계: API 모델 + 도구 호출. 사실(종족값·기술·사용률 등)은 외우지 않고 back API를 도구로 조회
- 서버는 Django와 분리 (`llm/`, FastAPI + SSE 예정). 파티 빌딩의 CoachChat이 여기에 붙는다
- 3단계 LoRA 파인튜닝: **`Qwen/Qwen3.5-4B`** (Apache 2.0)로 정함
  - 학습은 집 PC(RTX 3060 12GB, RAM 16GB)에서 WSL2 + Unsloth, bf16 LoRA(약 10GB)
  - `Qwen3.5-9B`는 학습에 VRAM 약 22GB가 필요해 집 PC·무료 Colab(T4)에서 불가.
    4B가 부족할 때만 시간제 GPU로 학습하고, 추론(4bit 약 6~7GB)은 집 PC에서 가능
  - 모델은 Apache 2.0만 쓴다. 비교용 후보: `kakaocorp/kanana-2-3b-instruct`(라이선스 확인 필요), `skt/A.X-4.0-Light`
  - EXAONE 제외: 라이선스가 연구 목적 전용이라 무료 공개 서비스·외부 배포도 막힘
  - 파인튜닝은 사실 암기가 아니라 도구 호출 방식과 파티 판단을 가르치는 용도.
    데이터 후보: DB로 만든 합성 도구 호출 문답, 리플레이 선출·선봉, 대회·OP.GG 팀 완성
- API 키는 `llm/.env`에 두고 git에 올리지 않는다
