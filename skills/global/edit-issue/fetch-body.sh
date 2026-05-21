#!/usr/bin/env bash
# edit-issue スキルの Issue 本文取得スクリプト
# Usage: fetch-body.sh <issue-number> [out-file]
# 既定の出力先: docs/temp/issue-body.md

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <issue-number> [out-file]" >&2
  exit 1
fi

ISSUE_NUM="$1"
OUT_FILE="${2:-docs/temp/issue-body.md}"

# 出力先ディレクトリを作成
mkdir -p "$(dirname "$OUT_FILE")"

# Issue本文を取得して保存
gh issue view "$ISSUE_NUM" --json body --jq .body > "$OUT_FILE"

LINES=$(wc -l < "$OUT_FILE")
SIZE=$(stat -c %s "$OUT_FILE")
echo "--> $OUT_FILE ($LINES lines, $SIZE bytes)"
