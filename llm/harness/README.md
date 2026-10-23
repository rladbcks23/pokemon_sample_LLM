# 설명 하네스

파티·샘플 설명을 미리 써서 저장한다. 평가 기준은 `../DESCRIPTION_RUBRIC.md` (점수표 원본은 `rubric.py`).

```
근거 묶음(facts.py) → 작성(Claude) → 1차 자동 검사(rubric.py) → 심사(GPT) → 100점 계산 → 통과면 저장 / 아니면 고쳐 쓰기
```

- 작성·심사는 **구독 CLI**로 부른다: `claude -p`(Claude 구독), `codex exec`(ChatGPT 구독). 종량제 API 키 환경 변수는 자식 프로세스에서 지운다
  - 먼저 로그인: `claude` 실행 후 로그인, `codex login` (`codex login status`가 "Logged in using ChatGPT"인지 확인)
- 고쳐 쓰기 횟수 제한 없음. 같은 규칙 지적이 2번 연속이면 "근거로 이유를 대거나 모르겠다고 쓰기"(이유 규칙) / "다른 문장을 줄여서라도 넣기"(내용 규칙)를 지시한다
- 점수가 떨어지면 가장 좋았던 설명으로 되돌리되 같은 설명으로는 2번까지, 줄이다가 빠진 내용은 "[남겨 두기]"로 알려 준다
- **같은 감점 묶음이 3번 연속이면 멈추고 보류** (가장 좋았던 설명 기록, 서비스에는 안 씀. 근거 묶음이나 기준 버전이 바뀌면 다시 시도, `--retry-held`로 강제). 2026-10-23 긴 설명↔줄인 설명을 21바퀴 돌며 codex 사용량을 크게 쓴 일 때문
- 결과: `data/descriptions/sample.jsonl`, `party.jsonl` (키마다 마지막 줄이 유효). 근거 묶음이 그대로인 통과 설명은 다음 실행에서 건너뛴다
- 실행 기록: `llm/harness/logs/*.jsonl` (git 제외)

## 실행

```
cd llm
..\.venv\Scripts\python -m harness.run --kind sample --format singles --limit 5
..\.venv\Scripts\python -m harness.run --kind party --format doubles --limit 3
..\.venv\Scripts\python -m harness.run --kind sample --pokemon garchomp --writer codex --judge claude
```

| 옵션 | 뜻 |
|---|---|
| `--kind sample\|party` | 샘플 / 파티 |
| `--format singles\|doubles` | 포맷 (생략하면 둘 다) |
| `--pokemon garchomp` | 샘플: 이 포켓몬만 |
| `--limit N` | 이번에 처리할 개수 (0 = 전부) |
| `--writer`, `--judge` | `claude` / `codex` (기본 작성 claude, 심사 codex) |
| `--writer-model`, `--judge-model` | 예: `opus`, `sonnet` / `gpt-5.5` (생략하면 CLI 기본 모델) |
| `--writer-effort`, `--judge-effort` | 생각 깊이. 심사는 기본 `medium` (codex 기본값은 한 번에 2~5분, 사용량이 많음) |
| `--max-rounds N` | 안전장치 (기본 0 = 제한 없음) |
| `--redo` | 이미 통과·보류한 것도 다시 |
| `--retry-held` | 보류한 것만 다시 |
| `--port 8002` | 실시간 보기 포트 (0 = 끔) |
| `--keep-open` | 끝난 뒤에도 실시간 보기 페이지 유지 (Ctrl+C로 종료) |

## 실시간 보기

실행하면 `http://localhost:8002`가 열린다 (터미널에도 한 줄씩 나옴). 디스코드처럼 왼쪽은 채널(샘플·파티 하나씩, 진행 중 노랑·통과 초록·보류 빨강·점수), 오른쪽은 대화.

- 하네스 봇: 새 샘플(근거 묶음 펼치기), 자동 검사 결과, 점수표(항목별 점수·최소점수 미달 빨강·감점 사유), 최종 설명
- 작성자 Claude / 심사자 GPT: 글이 생성되는 대로 흘러나옴 (생각 과정이 오면 회색 기울임으로)
- "새 채널 따라가기"를 끄면 지금 보는 채널에 머문다. 페이지를 늦게 열거나 새로 고쳐도 처음부터 다시 보여 준다

## 테스트

`llm`에서 `..\.venv\Scripts\python -m unittest tests.test_harness` (모델·DB 없이 점수 계산·자동 검사·실시간 서버)
