"""원래 노트북을 보존하고 재구성판과 일치하는 Colab 노트북을 만든다."""
import json
from pathlib import Path


def create_notebook():
    notebook = json.loads(Path(__file__).with_name('finetune_colab.ipynb').read_text(encoding='utf-8'))
    def setcell(index, text):
        c = notebook['cells'][index]
        c['source'] = text.strip() + '\n'
        if c['cell_type'] == 'code':
            c['outputs'], c['execution_count'] = [], None
    setcell(0, '''# 파티 코치 — 재구성 데이터 전용 Colab
Qwen3.5-4B, 4bit QLoRA, 길이 4096, r=8. T4에서는 Qwen3.5의 float32 경로를 사용합니다.
샘플·파티 대화를 assistant 행동별로 학습하며 마지막 응답만 loss에 포함합니다.
학습과 채팅 모두 같은 compact_context 입력 표현을 사용합니다.
**처음에는 SMOKE_TEST=True로 가장 긴 데이터 2개만 확인합니다. 성공하면 런타임을 다시 시작하고 False로 바꿔 전체 실행하세요.**
기존 ZIP이나 기존 노트북과 혼용하지 마세요. 실제 T4 학습과 추천 품질은 실행 후 확인해야 합니다.''')
    setcell(2, '''import os, sys, json, re, shutil, subprocess, zipfile, hashlib
from pathlib import Path
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
USE_DRIVE = True
DRIVE_DIR = Path('/content/drive/MyDrive/pokemon_coach')
if USE_DRIVE:
    from google.colab import drive
    drive.mount('/content/drive')
    DRIVE_DIR.mkdir(parents=True, exist_ok=True)
subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv'], check=True)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'unsloth', 'gradio',
                'django>=5.2,<6', 'djangorestframework', 'jsonschema'], check=True)
BUNDLE_NAME = 'colab_bundle_rebuilt_20261007.zip'
paths = [Path('/content') / BUNDLE_NAME, DRIVE_DIR / BUNDLE_NAME]
bundle = next((p for p in paths if p.exists()), None)
if bundle is None:
    raise FileNotFoundError(f'{BUNDLE_NAME}을 Colab 파일 탭 또는 {DRIVE_DIR}에 올리세요.')
REPO = Path('/content/pokemon_rebuilt_20261007')
if REPO.exists():
    shutil.rmtree(REPO)
with zipfile.ZipFile(bundle) as z:
    z.extractall(REPO)
print('사용 묶음:', bundle)
''')
    setcell(3, '''## 2. 설정
SMOKE_TEST=True는 가장 긴 입력 2개로 메모리·정답 마스킹을 점검합니다.
성공하면 런타임을 다시 시작하고 False로 바꿔 전체를 실행하세요.
학습률·총 스텝·유형별 개수·길이를 출력합니다. 기존 결과나 체크포인트는 읽지 않습니다.''')
    setcell(4, '''import torch
SMOKE_TEST = True
MODEL_NAME = 'unsloth/Qwen3.5-4B'
LOAD_IN_4BIT, MAX_SEQ_LEN = True, 4096
LR, LR_SCHEDULER, WARMUP_RATIO = 1e-4, 'cosine', .05
EPOCHS, TRAIN_LIMIT = 1, None
BATCH, GRAD_ACC = 1, (1 if SMOKE_TEST else 8)
LORA_R, LORA_ALPHA = 8, 16
WEIGHT_DECAY, LOG_EVERY, EVAL_N, SEED = .01, 1, 12, 3407
if not torch.cuda.is_available():
    raise RuntimeError('Colab 런타임을 GPU로 변경하세요.')
BF16 = torch.cuda.get_device_capability()[0] >= 8
# Qwen3.5는 T4의 float16 경로를 사용할 수 없어 Unsloth가 float32로 전환한다.
FP16 = False
gpu = torch.cuda.get_device_properties(0)
VRAM_GB = gpu.total_memory / 2**30
DATA_DIR = REPO / 'llm/training/finetuning_data_ver2'
report = json.loads((DATA_DIR / 'report.json').read_text())
actual_hash = hashlib.sha256((REPO / 'data/pokemon.db').read_bytes()).hexdigest()
assert actual_hash == report['version']['db_sha256'], 'DB 버전 불일치'
OUT_DIR = (DRIVE_DIR if USE_DRIVE else Path('/content')) / 'outputs_rebuilt_20261007' / ('smoke' if SMOKE_TEST else 'full')
RESUME = False
def show_settings(**extra):
    settings = {'GPU': f'{gpu.name} ({VRAM_GB:.1f}GB)', '모델': MODEL_NAME,
                '정밀도': 'bf16' if BF16 else 'float32 (Qwen3.5/T4)', '길이': MAX_SEQ_LEN,
                '학습률': LR, '스케줄': LR_SCHEDULER, '에폭': EPOCHS,
                '배치': f'{BATCH} × {GRAD_ACC}', 'LoRA r / alpha': f'{LORA_R} / {LORA_ALPHA}',
                '2스텝 점검': SMOKE_TEST, **extra}
    print('\\n'.join(f'{k}: {v}' for k, v in settings.items()))
show_settings()
''')
    setcell(5, '''## 3. 입력 표현·도구
전체 도구의 이름·필수 인자·타입을 간단히 표시합니다. 육성형 중복만 참조로 줄이고 원문은 유지합니다.
서버에 붙일 때도 이 입력 표현을 적용해야 합니다.''')
    setcell(6, '''for p in (REPO / 'llm', REPO / 'llm/training'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from agent.prompt import SYSTEM as ORIGINAL_SYSTEM, screen_context
from agent.tools import TOOLS as CLAUDE_TOOLS
from compact_context import system_prompt, prepare_messages, mask_last_response
SYSTEM = system_prompt(ORIGINAL_SYSTEM, CLAUDE_TOOLS)
assert hashlib.sha256(SYSTEM.encode()).hexdigest() == report['version']['system_sha256'], '入力 표현 버전 불일치'
print('전체 도구:', ', '.join(t['name'] for t in CLAUDE_TOOLS))
'''.replace('入力', '입력'))
    setcell(7, '''## 4. 재구성 데이터
train/eval은 마지막 assistant 행동별 자료입니다. 원래 전체 대화는 source_train/source_eval.jsonl에 보존했습니다.
원본 팀·육성형·변형을 연결해서 학습/평가를 분리했습니다. 자연어 설명은 사람 검수 대기입니다.''')
    setcell(8, '''from collections import Counter
def read(name):
    return [json.loads(line) for line in (DATA_DIR / name).read_text().splitlines() if line.strip()]
train_rows, eval_rows = read('train.jsonl'), read('eval.jsonl')
print('학습 행동:', len(train_rows), Counter(r['kind'] for r in train_rows))
print('평가 행동:', len(eval_rows), Counter(r['kind'] for r in eval_rows))
print('원본 분리:', report['split'])
assert not ({r['origin_component'] for r in train_rows} & {r['origin_component'] for r in eval_rows})
if SMOKE_TEST:
    train_rows = sorted(train_rows, key=lambda r: r['tokens'], reverse=True)[:2]
    print('가장 긴 입력 2개로 점검:', [(r['id'], r['tokens']) for r in train_rows])
''')
    # 기존 모델 로더도 재실행 시 이전 모델을 메모리에 두지 않도록 정리한다.
    original_loader = ''.join(notebook['cells'][10]['source'])
    setcell(10, '''import gc
for key in ('trainer', 'model', 'tokenizer', 'tok'):
    if key in globals():
        del globals()[key]
gc.collect()
torch.cuda.empty_cache()
''' + original_loader)
    setcell(11, '''## 6. 실제 토크나이저로 길이 재확인
4096 초과 자료가 있으면 중단합니다. 조용히 제외하거나 잘라서 학습하지 않습니다.''')
    setcell(12, '''import math
from datasets import Dataset
def render(messages, add_generation_prompt=False):
    return tok.apply_chat_template(messages, tokenize=False, tools=None,
                                   add_generation_prompt=add_generation_prompt, enable_thinking=False)
def to_dataset(rows, label):
    texts = [render(r['messages']) for r in rows]
    lens = [len(tok(t, add_special_tokens=False).input_ids) for t in texts]
    overflow = [(r['id'], n) for r, n in zip(rows, lens) if n > MAX_SEQ_LEN]
    if overflow:
        raise ValueError(f'{label} 길이 초과 (제외 없이 중단): {overflow[:8]}')
    print(f'{label}: {len(rows)}행, 최대 {max(lens)} / 평균 {sum(lens)//len(lens)}토큰, 초과 0')
    return Dataset.from_dict({'text': texts})
dataset = to_dataset(train_rows, '학습')
# 평가를 한 종류에서만 뽑지 않도록 종류별로 번갈아 뽑는다.
def balanced_rows(rows, limit):
    buckets = {k: [r for r in rows if r['kind'] == k] for k in sorted({r['kind'] for r in rows})}
    result = []
    while len(result) < limit and any(buckets.values()):
        for values in buckets.values():
            if values and len(result) < limit:
                result.append(values.pop(0))
    return result
eval_selected = balanced_rows(eval_rows, EVAL_N)
eval_dataset = to_dataset(eval_selected, '평가')
STEPS = 2 if SMOKE_TEST else math.ceil(len(dataset)/(BATCH*GRAD_ACC))*EPOCHS
WARMUP_STEPS = 0 if SMOKE_TEST else math.ceil(STEPS*WARMUP_RATIO)
EVAL_EVERY = max(STEPS//5, 1)
show_settings(**{'총 스텝': STEPS, 'warmup 스텝': WARMUP_STEPS, '평가 주기': EVAL_EVERY})
print('\\n예시 정답:\\n', dataset[0]['text'][-800:])
''')
    setcell(13, '''## 7. 학습
마지막 assistant 응답만 학습합니다. 입력·조회 결과·지난 답변은 -100으로 마스킹합니다.
2스텝 점검에서는 평가를 생략합니다. 본 학습에서는 loss·학습률·grad norm·VRAM·평가 loss를 표시합니다.
기존 체크포인트를 재개하지 않습니다. OOM이면 런타임을 다시 시작하세요.''')
    original_training = ''.join(notebook['cells'][14]['source'])
    callback = original_training[original_training.index('class LiveLog'):original_training.index('trainer = SFTTrainer')]
    setcell(14, '''import time, inspect
from transformers import TrainerCallback, DataCollatorForSeq2Seq
from trl import SFTTrainer, SFTConfig
''' + callback + '''
config = dict(dataset_text_field='text', output_dir=str(OUT_DIR / 'checkpoints'),
    per_device_train_batch_size=BATCH, per_device_eval_batch_size=1, gradient_accumulation_steps=GRAD_ACC,
    num_train_epochs=EPOCHS, max_steps=2 if SMOKE_TEST else -1,
    learning_rate=LR, lr_scheduler_type=LR_SCHEDULER, warmup_steps=WARMUP_STEPS,
    optim='adamw_8bit', weight_decay=WEIGHT_DECAY, bf16=BF16, fp16=FP16,
    bf16_full_eval=False, fp16_full_eval=False, packing=False,
    logging_steps=LOG_EVERY, eval_strategy='no' if SMOKE_TEST else 'steps', eval_steps=EVAL_EVERY,
    save_strategy='no' if SMOKE_TEST else 'steps', save_steps=EVAL_EVERY, save_total_limit=2,
    seed=SEED, report_to='none', disable_tqdm=True)
fields = getattr(SFTConfig, '__dataclass_fields__', {})
params = inspect.signature(SFTConfig.__init__).parameters
length_key = next((k for k in ('max_length', 'max_seq_length') if k in fields or k in params), None)
if length_key is None:
    raise RuntimeError('SFTConfig 길이 인자를 확인할 수 없음. 라이브러리 버전을 확인하세요.')
config[length_key] = MAX_SEQ_LEN
kwargs = dict(model=model, train_dataset=dataset, eval_dataset=eval_dataset,
              args=SFTConfig(**config), callbacks=[LiveLog()],
              data_collator=DataCollatorForSeq2Seq(tokenizer=tok, padding=True, label_pad_token_id=-100))
trainer_params = inspect.signature(SFTTrainer.__init__).parameters
kwargs['processing_class' if 'processing_class' in trainer_params else 'tokenizer'] = tok
trainer = SFTTrainer(**kwargs)
marker = tok.encode('<|im_start|>assistant\\n', add_special_tokens=False)
for attr in ('train_dataset', 'eval_dataset'):
    ds = getattr(trainer, attr)
    ds = ds.map(lambda e: mask_last_response(e, marker), load_from_cache_file=False)
    if any(not any(x != -100 for x in r['labels']) for r in ds):
        raise ValueError('학습할 정답 토큰이 없는 자료')
    setattr(trainer, attr, ds)
print('정답 마스킹 확인:', sum(x != -100 for x in trainer.train_dataset[0]['labels']), '토큰')
stats = trainer.train(resume_from_checkpoint=None)
print(f"끝: {stats.metrics['train_runtime']/60:.1f}분, loss {stats.metrics['train_loss']:.4f}, "
      f"최대 VRAM {torch.cuda.max_memory_reserved()/2**30:.1f}GB")
''')
    setcell(17, '''## 8. 평가: 도구 인자까지 확인
평가 행동에 대해 도구 이름·필수 인자/타입·정확한 인자 일치를 비교합니다.
도구 없이 끝나는 답변은 출력과 정답을 사람이 비교합니다. 이 점수만으로 최종 추천 품질을 판단하지 않습니다.
2스텝 점검에서는 생략합니다.''')
    original_eval = ''.join(notebook['cells'][18]['source'])
    parse = original_eval[:original_eval.index('def generate')]
    setcell(18, parse + '''
from jsonschema import Draft202012Validator
validators = {t['name']: Draft202012Validator(t['input_schema']) for t in CLAUDE_TOOLS}
def generate(msgs, max_new_tokens=1024, prepared=False):
    messages = msgs if prepared else prepare_messages(msgs, SYSTEM)
    ids = tok(render(messages, add_generation_prompt=True), add_special_tokens=False, return_tensors='pt').to(model.device)
    room = MAX_SEQ_LEN - ids['input_ids'].shape[1]
    if room < 80:
        raise ValueError('대화 문맥이 가득 찼습니다. 새 대화에서 질문을 이어 주세요.')
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=min(max_new_tokens, room), do_sample=False, use_cache=True)
    return tok.decode(out[0][ids['input_ids'].shape[1]:], skip_special_tokens=False)
model.eval()
if not SMOKE_TEST:
    score = Counter()
    for r in balanced_rows(eval_rows, 24):
        gold = r['messages'][-1]
        output = generate(r['messages'][:-1], max_new_tokens=1024, prepared=True)
        calls = parse_calls(output)
        expected = [(c['function']['name'], c['function']['arguments']) for c in gold.get('tool_calls', [])]
        score['examples'] += 1
        if expected:
            score['tool_examples'] += 1
            score['name_match'] += [n for n, a in calls] == [n for n, a in expected]
            score['schema_valid'] += bool(calls) and all(n in validators and validators[n].is_valid(a) for n, a in calls)
            score['exact_args'] += calls == expected
        else:
            print(r['kind'], '\\n예측:', output[:500], '\\n정답:', gold['content'])
    print(dict(score))
else:
    print('2스텝 점검 모델의 품질 평가는 생략합니다.')
''')
    setcell(19, '''## 9. 저장
본 학습만 새 폴더에 어댑터를 저장합니다. 데이터·입력 표현·도구와 함께 보관해야 합니다.''')
    setcell(20, '''ADAPTER = OUT_DIR / 'qwen35-4b-coach-lora'
if not SMOKE_TEST:
    model.save_pretrained(ADAPTER)
    tokenizer.save_pretrained(ADAPTER)
    shutil.copy(DATA_DIR / 'report.json', ADAPTER / 'data_report.json')
    shutil.copy(REPO / 'llm/training/compact_context.py', ADAPTER / 'compact_context.py')
    print('저장:', ADAPTER)
else:
    print('2스텝 점검 결과는 어댑터로 저장하지 않습니다.')
''')
    setcell(21, '''if not USE_DRIVE and not SMOKE_TEST:
    from google.colab import files
    shutil.make_archive(str(ADAPTER), 'zip', ADAPTER)
    files.download(str(ADAPTER) + '.zip')
''')
    setcell(22, '''## 10. 채팅방
실제 back/DB 도구를 실행합니다. 2스텝 점검 모델은 추천 품질을 판단할 수 없습니다.
학습과 동일한 입력 표현을 사용하고 도구 호출 인자를 먼저 검사합니다.
“더블 파티 하나 짜줘”, “더블 한카리아스 샘플 짜줘”를 먼저 비교해 보세요.''')
    chat = ''.join(notebook['cells'][23]['source'])
    chat = chat.replace("out = json.dumps(await tools.run(n, a), ensure_ascii=False)",
                        "if n not in validators:\n                        raise ValueError(f'없는 도구: {n}')\n                    validators[n].validate(a)\n                    out = json.dumps(await tools.run(n, a), ensure_ascii=False, separators=(',', ':'))")
    chat = chat.replace("text = generate(msgs)",
                        "try:\n                text = generate(msgs, prepared=False)\n            except ValueError as e:\n                return str(e), log")
    setcell(23, chat)
    setcell(24, '''전체 대화·원본 ID·제외 사유는 ZIP의 source_train.jsonl/source_eval.jsonl/report.json에 있습니다.
자동 검사는 설명의 정확성이나 실제 추천 성능을 보장하지 않습니다. 마지막 채팅에서 조건 변경과 잘못된 이름도 확인하세요.''')
    for c in notebook['cells']:
        if c['cell_type'] == 'code':
            c['outputs'], c['execution_count'] = [], None
            compile(''.join(c['source']), '<notebook cell>', 'exec')
    return notebook
