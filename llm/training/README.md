# Colab 학습

실행할 파일은 아래 두 개다.

- `finetune_colab.ipynb`: 현재 학습·loss/학습률 그래프·평가·채팅 노트북
- `colab_bundle.zip`: 현재 학습 데이터·back 코드·DB·도구 묶음

ZIP을 `MyDrive/pokemon_coach/` 또는 Colab 파일 탭에 올린다. 노트북을 Colab에서 열고
GPU 런타임으로 순서대로 실행한다. 먼저 `SMOKE_TEST=True`로 2스텝 점검한 뒤,
성공하면 런타임을 다시 시작하고 `False`로 전체 학습을 실행한다.

## 폴더

```text
training/
  finetune_colab.ipynb       # 실행
  colab_bundle.zip          # 업로드
  README.md
  make_data.py              # 실제 DB로 파티 대화 생성
  inproc_back.py            # Colab 채팅·데이터 생성에서 back 호출
  scripts/                  # 데이터 재구성·검수·짧은 입력 표현
  archive/                  # 이전 ZIP·원본 데이터·중간 결과 보관
```

현재 데이터와 보고서는 ZIP 안의 `llm/training/finetuning_data_ver2/`에 있다.
`report.json`은 데이터 수·길이·원본 분할·버전, `source_train.jsonl`과 `source_eval.jsonl`은
행동별 분리 전의 원본 대화다. ZIP에서 바로 확인할 수 있어 로컬에 중복 `outputs/`를 두지 않는다.
데이터와 ZIP은 Git에 넣지 않는다. `archive/`의 파일은 현재 실행에 사용하지 않는다.

## 데이터를 다시 만들 때

저장소 루트에서 실행한다. 기존 결과를 보존하도록 `--out`에는 새 폴더를 지정한다.

```powershell
.venv\Scripts\python llm/training/scripts/rebuild_colab_data.py `
  --current "현재 원본 ZIP 경로" `
  --v1 "ver1 원본 ZIP 경로" `
  --tokenizer-dir "Qwen3.5-4B 토크나이저 폴더" `
  --out "llm/training/build/새_데이터"
```

새 폴더에 데이터·보고서·`colab_bundle.zip`을 만든다. 생성된 ZIP을 Colab에 올리고
현재 `finetune_colab.ipynb`를 사용한다. 묶음 제작이 끝나면 임시 `build/` 복사본은 정리해도 된다.
이 명령은 모델을 학습하지 않는다.
데이터 생성에는 `tokenizers`, `jinja2`, `jsonschema`와 기존 back 의존성이 필요하다.
