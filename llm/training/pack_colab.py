"""Colab에 올릴 묶음 만들기: back 코드 + DB + 코치 도구 + 학습 데이터 → llm/training/colab_bundle.zip

Colab 노트북은 이 zip 하나만 올리면 된다 (학습 + 마지막 채팅방에서 실제 도구 실행까지).
저장소와 같은 폴더 구조로 넣으므로 Colab에서도 back 설정(data/pokemon.db 경로)이 그대로 맞는다.

    cd llm
    ..\\.venv\\Scripts\\python training\\make_data.py --export 220
    ..\\.venv\\Scripts\\python training\\pack_colab.py
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'llm/training/colab_bundle.zip'

FILES = [
    *[p for p in (ROOT / 'back').rglob('*') if p.is_file() and '__pycache__' not in p.parts
      and 'ui' not in p.relative_to(ROOT / 'back').parts[:1]],
    *[p for p in (ROOT / 'llm/agent').rglob('*.py') if '__pycache__' not in p.parts],
    ROOT / 'llm/training/inproc_back.py',
    ROOT / 'data/pokemon.db',
    ROOT / 'llm/training/finetuning_data_ver2/train.jsonl',      # make_data.py --export
    ROOT / 'llm/training/finetuning_data_ver2/eval.jsonl',
]


def main():
    missing = [str(p.relative_to(ROOT)) for p in FILES if not p.exists()]
    if missing:
        raise SystemExit(f'없는 파일: {missing} (DB는 load_dex/load_meta, 학습 데이터는 make_data.py --export로 먼저 만들 것)')
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in FILES:
            z.write(p, p.relative_to(ROOT).as_posix())
    print(f'{OUT} ({OUT.stat().st_size / 2**20:.1f}MB, 파일 {len(FILES)}개) → Colab 왼쪽 파일 탭에 올릴 것')


if __name__ == '__main__':
    main()
