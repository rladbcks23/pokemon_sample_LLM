"""Colab에서 받은 LoRA 어댑터를 기본 모델에 합쳐 llama.cpp용 GGUF(기본 Q8_0)로 만든다. GPU 불필요 (RAM 약 12GB).

    .venv\\Scripts\\pip install <llama.cpp 소스>\\gguf-py
    .venv\\Scripts\\python llm/training/scripts/export_gguf.py --llama-cpp C:/Users/<나>/llama.cpp

llama.cpp: https://github.com/ggml-org/llama.cpp/releases 의 win-cuda 빌드(+cudart)를 <dir>/bin에,
같은 태그의 소스(convert_hf_to_gguf.py)를 <dir>/llama.cpp-<태그>에 푼다.
결과: llm/models/qwen35-4b-coach-<quant>.gguf (git 제외). 중간 파일(합친 모델·bf16 GGUF)은 지운다.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

LLM = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--adapter', default=str(LLM / 'models/qwen35-4b-coach-lora'))
    ap.add_argument('--llama-cpp', required=True, help='bin/과 llama.cpp-<태그>/ 소스가 있는 폴더')
    ap.add_argument('--quant', default='Q8_0')       # 원본에 가장 가깝고 6GB GPU에 들어감 (Q4_K_M은 2.5GB·약 30% 빠름)
    ap.add_argument('--keep', action='store_true', help='중간 파일을 남김')
    a = ap.parse_args()

    adapter, root = Path(a.adapter), Path(a.llama_cpp)
    convert = next(root.glob('llama.cpp-*/convert_hf_to_gguf.py'))
    quantize = next(root.glob('bin/**/llama-quantize.exe'), None) or next(root.glob('bin/**/llama-quantize'))
    out = LLM / f'models/qwen35-4b-coach-{a.quant}.gguf'
    merged, bf16 = LLM / 'models/_merged', LLM / 'models/_merged-bf16.gguf'

    if not merged.exists():
        import torch
        from peft import PeftModel
        from transformers import AutoModelForImageTextToText
        base = json.loads((adapter / 'adapter_config.json').read_text(encoding='utf-8'))['base_model_name_or_path']
        print('합치는 중:', base, '+', adapter, flush=True)
        model = AutoModelForImageTextToText.from_pretrained(base, dtype=torch.bfloat16, device_map='cpu')
        model = PeftModel.from_pretrained(model, adapter).merge_and_unload()
        model.save_pretrained(merged)
        for f in adapter.glob('*'):       # 토크나이저·채팅 템플릿·processor 설정은 어댑터 폴더 것 (학습 때와 같게)
            if f.name.startswith(('tokenizer', 'chat_template', 'processor', 'preprocessor')):
                shutil.copy(f, merged / f.name)
        del model

    subprocess.run([sys.executable, str(convert), str(merged), '--outtype', 'bf16', '--outfile', str(bf16)], check=True)
    subprocess.run([str(quantize), str(bf16), str(out), a.quant], check=True)
    if not a.keep:
        shutil.rmtree(merged)
        bf16.unlink()
    print('완료:', out, f'{out.stat().st_size / 2**30:.2f}GB')


if __name__ == '__main__':
    main()
