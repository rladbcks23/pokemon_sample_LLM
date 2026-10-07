# llm

파티 빌더 LLM 서버 (파티 코치). back(Django)과 **별도 서버**로 돌아간다.

## 역할
- 요청 의도 해석, 도구 호출, 파티 제안, 전략 설명
- 사실 정보(종족값, 기술, 배우는 기술, 사용률, 상성, 스피드)는 외우지 않고 **back의 API로 조회·계산**
- 파티 빌딩 페이지의 채팅 답변을 SSE로 스트리밍

## 모델 학습 (Colab 전용)

모델 학습은 Colab에서만 진행한다. 사용할 파일은 `training/finetune_colab_rebuilt.ipynb`와
`training/colab_bundle_rebuilt_20261007.zip`이다. ZIP을 드라이브 `MyDrive/pokemon_coach/` 또는
Colab 파일 탭에 올리고 전용 노트북을 순서대로 실행한다.

먼저 `SMOKE_TEST=True`로 가장 긴 입력 2개를 2스텝 점검한다. 성공하면 런타임을 다시 시작하고
`SMOKE_TEST=False`로 바꿔 전체 학습을 실행한다. 학습률·loss 그래프와 마지막 채팅방도 이 노트북에 있다.

`training/finetune_colab.ipynb`는 기존 형식과 재구성 노트북 생성에 쓰는 기본 파일이다.
데이터 생성·검증·ZIP 제작 스크립트, back API와 DB, 에이전트 도구는 Colab에서도 사용한다.

## 실행 (Windows 기준, 리눅스는 `../.venv/bin/`)
```bash
..\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # ANTHROPIC_API_KEY 채우기
..\.venv\Scripts\uvicorn server.app:app --port 8001
```
back(8000)과 front(5173)도 같이 띄운다. 화면의 `/llm` 요청은 Vite 프록시가 8001로 넘긴다.

테스트 (모델·back API는 가짜라 API 키·DB 없이 돈다):
```bash
..\.venv\Scripts\python -m unittest
```

## 구조
```
llm/
  config.py    설정 (llm/.env에서 읽음: 모델, effort, back 주소)
  agent/       에이전트 루프(loop.py), 시스템 프롬프트(prompt.py), 도구(tools.py = back API 호출)
  providers/   모델 호출. 지금은 Claude API(claude.py), 나중에 로컬 모델(Qwen3.5-4B LoRA)을 같은 모양으로 추가
  server/      채팅 API 서버 (SSE)
  tests/       루프·도구·서버 테스트
  training/    (3단계) LoRA 파인튜닝 데이터 생성·학습
```

## API
`POST /llm/chat`
```json
{"history": [{"role": "user", "text": "이 파티 약점 알려줘"}], "format": "doubles", "party": [샘플 또는 null × 6]}
```
응답은 `text/event-stream`. 이벤트:

| event | data | 화면 |
|---|---|---|
| `status` | `{"text": "포켓몬 찾는 중"}` | 진행 상태 줄 |
| `text` | `{"delta": "..."}` | 답변에 이어 붙임 |
| `party` | `{"members": [샘플…]}` | 추천 파티 카드 ("모두 추가하기") |
| `error` | `{"message": "..."}` | 답변 끝에 ⚠ 문구 |
| `done` | `{}` | 끝 |

화면 상황(싱글/더블, 현재 파티)은 마지막 사용자 메시지 앞에 붙인다. 시스템 프롬프트는 고정이라 프롬프트 캐시가 유지된다.

## 도구
| 도구 | back API | 내용 |
|---|---|---|
| `search_pokemon` | `GET /api/pokemon/` | 이름으로 ID·타입·종족값·순위·메가 폼 찾기 |
| `get_pokemon` | `GET /api/pokemon/{id}/` | 폼별 특성, 사용률 상위, (요청 시) 배우는 기술 |
| `get_ranking` | `GET /api/ranking/` | 픽률 순위·변동 |
| `search_samples` | `GET /api/samples/` | 공개 포켓몬 샘플 |
| `search_teams` / `get_team` | `GET /api/teams/` | 파티 샘플 목록·상세 |
| `analyze_party` | `GET /api/options/` | 파티 방어 상성 (메가스톤이면 메가 폼 타입) |
| `get_speed_tiers` | `GET /api/speed/` | 스피드 실수치표 |
| `validate_set` | `POST /api/validate/` | 육성형 검사 + 실수치 |
| `propose_party` | `POST /api/validate/` | 모두 합법이면 화면에 추천 파티 카드 |

## 분리한 이유
- 파인튜닝·로컬 모델용 무거운 라이브러리(torch 등)가 Django에 섞이지 않음
- GPU 서버에 따로 배포 가능
