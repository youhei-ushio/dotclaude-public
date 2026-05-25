#!/usr/bin/env bash
# pdf-read スキルの PDF → PNG 全ページレンダリング + テキスト抽出
# Usage: render.sh <input.pdf> [output_dir]

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <input.pdf> [output_dir]" >&2
  exit 1
fi

src="$1"
if [[ ! -f "$src" ]]; then
  echo "ERROR: file not found: $src" >&2
  exit 2
fi

src_lower=$(printf '%s' "$src" | tr '[:upper:]' '[:lower:]')
if [[ "$src_lower" != *.pdf ]]; then
  echo "ERROR: not a PDF: $src" >&2
  exit 2
fi

# 出力ディレクトリ
if [[ $# -ge 2 ]]; then
  out_dir="$2"
else
  src_dir=$(dirname "$src")
  base=$(basename "$src" .pdf)
  out_dir="$src_dir/${base}-pages"
fi

mkdir -p "$out_dir"

# pypdfium2 (Apache 2.0 / BSD 3-clause) + Pillow (HPND) が無ければインストール
# PyMuPDF は AGPL のため使わない
if ! python3 -c "import pypdfium2, PIL" 2>/dev/null; then
  echo "[pdf-read] installing pypdfium2 + Pillow (--user --break-system-packages)..." >&2
  pip install --user --break-system-packages --quiet pypdfium2 Pillow >&2 || {
    echo "ERROR: failed to install pypdfium2/Pillow" >&2
    exit 3
  }
fi

# pdfplumber が無ければインストール (任意、テキスト抽出の補助)
if ! python3 -c "import pdfplumber" 2>/dev/null; then
  echo "[pdf-read] installing pdfplumber (--user --break-system-packages)..." >&2
  pip install --user --break-system-packages --quiet pdfplumber >&2 || {
    echo "WARN: failed to install pdfplumber (text extraction skipped)" >&2
  }
fi

python3 "$(dirname "$0")/render.py" "$src" "$out_dir"
