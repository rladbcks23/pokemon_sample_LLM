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
  - 파티 판단 도구 (`back/apps/api/party.py`): `check_party`(역할·밸런스·중복·메가 수), `find_partners`(같이 쓰인 포켓몬:
    OP.GG 상위 파티·VGCPastes만, 리플레이 제외), `find_threats`(픽률 상위가 많이 쓰는 공격기로 약점을 찌르는 포켓몬)
- 역할·파티 기준 (사용자 정의, 시스템 프롬프트에 있음)
  - 기점잡이 = 벽(리플렉터·빛의장막·오로라베일)·스텔스록·순풍·랭크업 배턴터치 등으로 판을 까는 역할 (랭크업 딜러와 같이 씀)
  - 랭크업 딜러(스위퍼) = 용의춤·칼춤·나쁜음모 등 랭크업 메인 딜러. 물리/특수 딜러 = 공격·특공·스피드 위주, 혼합도 있음
  - 막이 = HP·방어·특방 위주, 상태이상·스텔스록 등으로 말려 죽이는 형태도 있음. 물리막이·특수막이로 구분
  - 더블에서는 기점잡이 대신 서포터(속이기·날따름·순풍·트릭룸 등). 한 포켓몬에 기점잡이/서포터와 막이를 같이 붙이지 않음
  - 내구조정 = 딜러인데 HP·방어·특방에도 SP를 나눠 준 형태
  - 역할은 종족값이 아니라 **SP 분배와 기술 배치**로 정한다 (같은 로토무도 CS면 딜러, HBD+깨불이면 막이).
    내구 SP여도 공격기 3개 이상이고 말려 죽이기·판 깔기 기술이 없으면 딜러(내구조정)
  - 샘플 검색은 샘플별 역할과 그 포켓몬 샘플의 형태 분포(shapes)를 준다. 추천은 흔한 형태(샘플의 10% 이상)만
    (샘플별 사용률은 DB에 없어서 공개 샘플 중 그 형태의 개수를 근거로 씀)
  - 공격 SP를 줬는데 그쪽 공격기가 없는 샘플은 학습 데이터에 쓰지 않음 (check_party 경고로도 알림)
  - 답변 스타일: 짧게. 후보는 "장점: 땅, 물 받아 줌 / 단점: 얼음 약점 늘어남"처럼, "남는 약점"은 말하지 않음.
    맞는 후보가 없으면 약점을 늘리는 후보를 억지로 추천하지 않고 한계를 말함
  - 파티 컨셉(막이 사이클·스윕·균형·컨셉 파티 등)마다 다름. 모르면 물어보거나 기본은 균형 파티.
    컨셉 파티(단일 타입, 6메가 등)는 일관성 우선, 대가만 짧게 알림
  - 메가진화는 배틀마다 한 번. 메가스톤 3개 이상이면 선출 제한·메가 2마리 동시 선출 가능성을 경고
  - 테스트는 `llm`에서 `..\.venv\Scripts\python -m unittest` (모델·back은 가짜라 API 키·DB 없이 돈다)
- LoRA 파인튜닝: **`Qwen/Qwen3.5-4B`** (Apache 2.0). 이미지도 받는 모델이라 Unsloth `FastModel`로 불러온다
  - 학습 데이터: `llm/training/make_data.py --export N` → `finetuning_data_ver2/` (back을 프로세스 안에서 직접 불러 실제 도구 결과로 대화 생성, 서버 불필요)
    - 1순위는 파티 빌딩·샘플 제작. 정답은 OP.GG 상위 파티·VGCPastes 대회 팀·OP.GG/대회 샘플
    - Showdown 리플레이는 쓰지 않는다 (평균 레이팅 약 1100~1200, 인게임 메타와 다름)
    - 답변 숫자는 도구 결과에 있는 것만 (없으면 버림). `train.jsonl`/`eval.jsonl`은 git 제외
  - 길이(v2, Qwen3.5 토크나이저): 시스템 프롬프트+도구 설명 약 2,650토큰, 대화 한 턴 평균 약 5,000·최대 약 7,000토큰.
    줄이는 방법: 도구 설명은 짧게, 결과는 필요한 필드만·JSON 공백 없이, 후보 비교는 check_party(candidates=…) 한 번
  - 모델 학습은 **Colab에서만** 진행한다. 로컬 GPU용 학습 노트북·설정은 유지하지 않는다
    - 실행 파일은 `llm/training/finetune_colab.ipynb` + `colab_bundle.zip` 한 쌍이다. 사용법은 `llm/training/README.md`
    - 보조 코드는 `scripts/`, 이전 ZIP·중간 결과는 `archive/`에 둔다. 현재 데이터·보고서는 ZIP에 포함하고 로컬 `outputs/` 복사본은 유지하지 않는다. 예전 실행 노트북과 중복 노트북 생성기는 유지하지 않는다
    - 데이터 생성·검증·묶음 제작 스크립트와 back/DB/도구는 Colab 학습·채팅에 필요하므로 유지한다
    - 묶음 ZIP은 드라이브 `MyDrive/pokemon_coach/` 또는 Colab 파일 탭에 올린다. 재구성판 결과는 `pokemon_coach/outputs_rebuilt_20261007/`에 저장한다
    - 노트북 끝의 채팅방(gradio)은 `inproc_back.py`로 back을 프로세스 안에서 불러 실제 도구를 실행한다
  - Colab 데이터 재구성: `llm/training/scripts/rebuild_colab_data.py`는 현재/v1 ZIP의 동일 DB를 확인하고 v2 대화를 실제 도구로 재검증, v1 샘플 유형은 현재 도구로 재생성한다. 원본 파일을 덮어쓰거나 학습하지 않는다
    - `scripts/compact_context.py`로 중복 육성형 원문을 한 번만 제공하고 각 assistant 행동을 분리해 4096 이내로 만든다. 도구 호출 정답의 필드는 그대로, 마지막 응답만 학습한다
    - 원본 팀·추천 육성형·변형의 연결 묶음으로 train/eval 분리. DB/도구/입력 버전·제외 사유·사람 검수 대기를 기록한다
    - r=8, 최대 길이 4096, T4 float32 경로. 먼저 가장 긴 입력 2개로 2스텝 점검. 실제 GPU 학습·추천 품질은 실행 후 확인
    - 재구성 모델을 서버에 붙일 때도 같은 `compact_context` 입력 표현을 적용해야 한다
  - `Qwen3.5-9B`는 학습에 VRAM 약 22GB가 필요해 무료 Colab(T4)에서 불가
  - 모델은 Apache 2.0만 쓴다. 비교용 후보: `kakaocorp/kanana-2-3b-instruct`(라이선스 확인 필요), `skt/A.X-4.0-Light`
  - EXAONE 제외: 라이선스가 연구 목적 전용이라 무료 공개 서비스·외부 배포도 막힘
  - 파인튜닝은 사실 암기가 아니라 도구 호출 방식과 파티 판단을 가르치는 용도
- API 키·설정은 `llm/.env`에 두고 git에 올리지 않는다
