#!/usr/bin/env bash
# sync-dotclaude.sh — dotclaude リポの内容を ~/.claude へ冪等に反映する。
#
# なぜ必要か:
#   CLAUDE.md / settings.json / statusline.sh は「ファイル単位の symlink」なので
#   git pull だけで中身が追従する。しかし skills / hooks は「項目ごとの symlink」で
#   デプロイしており、リポに *新規追加* された skill・hook は pull しても
#   ~/.claude 側に symlink が張られない（＝取りこぼす）。
#   特に settings.json は symlink で即最新化されるため、「新 hook を参照するのに
#   実体ファイルが無い」状態になると、その hook が発火する全 tool がブロックされる。
#
# このスクリプトは pull 後に実行して以下を保証する（何度実行しても安全）:
#   1. skills/global/* と hooks/* の不足 symlink を張る
#   2. CLAUDE.md / settings.json / statusline.sh の symlink を保証（新規セットアップ兼用）
#   3. settings.json が参照する hook が全て実在するか検証（全 tool ブロック事故の検知）
#   4. リポから消えた skill/hook を指す dangling symlink を検知（--prune で除去）
#
# 使い方:
#   ./sync-dotclaude.sh           # 同期＋検証（安全な既定）
#   ./sync-dotclaude.sh --prune   # 併せて dangling symlink を除去
#
# 環境変数:
#   CLAUDE_HOME  デプロイ先（既定: ~/.claude）
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"

PRUNE=0
for arg in "$@"; do
  case "$arg" in
    --prune) PRUNE=1 ;;
    *) echo "不明な引数: $arg (使用可能: --prune)" >&2; exit 64 ;;
  esac
done

linked=0; okcnt=0; fixed=0; warncnt=0; pruned=0

mkdir -p "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/skills"

# link_one <target-symlink> <source-in-repo>
# 既存が正しい symlink なら何もしない。別 symlink なら張り直す。
# 実ディレクトリ/実ファイルが居座っている場合はネスト事故を避けてスキップ＋警告。
link_one() {
  local link="$1" src="$2"
  if [ -L "$link" ]; then
    if [ "$(readlink "$link")" = "$src" ]; then
      okcnt=$((okcnt + 1)); return
    fi
    ln -sfn "$src" "$link"
    echo "  fix    : $(basename "$link")  (別リンクから張り直し)"
    fixed=$((fixed + 1)); return
  fi
  if [ -e "$link" ]; then
    echo "  WARN   : $link は実体（symlink でない）。ネスト回避のためスキップ。手動確認が必要"
    warncnt=$((warncnt + 1)); return
  fi
  ln -s "$src" "$link"
  echo "  link   : $(basename "$link")"
  linked=$((linked + 1))
}

echo "==> dotclaude 同期: $REPO_DIR -> $CLAUDE_DIR"

# 1) トップレベルの単体ファイル（新規セットアップ時のみ実効、既存はほぼ ok）
echo "-- top-level files"
link_one "$CLAUDE_DIR/CLAUDE.md"     "$REPO_DIR/CLAUDE.md"
link_one "$CLAUDE_DIR/settings.json" "$REPO_DIR/settings.json"
link_one "$CLAUDE_DIR/statusline.sh" "$REPO_DIR/statusline.sh"

# 2) hooks（*.py / *.sh を項目ごとに symlink。既存デプロイと同じく末尾スラッシュ無し）
echo "-- hooks"
for f in "$REPO_DIR"/hooks/*.py "$REPO_DIR"/hooks/*.sh; do
  [ -e "$f" ] || continue
  link_one "$CLAUDE_DIR/hooks/$(basename "$f")" "$f"
done

# 3) global skills（既存デプロイに合わせ末尾スラッシュ付きでリンク）
echo "-- skills/global"
for d in "$REPO_DIR"/skills/global/*/; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  link_one "$CLAUDE_DIR/skills/$name" "$d"
done

# 4) dangling 検知（リポから消えた skill/hook を指す壊れリンク）
echo "-- dangling リンク検査"
for dir in "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/skills"; do
  for l in "$dir"/*; do
    [ -L "$l" ] || continue
    tgt="$(readlink "$l")"
    case "$tgt" in
      "$REPO_DIR"/*) ;;    # このリポ由来のみ対象
      *) continue ;;
    esac
    if [ ! -e "$l" ]; then
      if [ "$PRUNE" -eq 1 ]; then
        rm "$l"; echo "  prune  : $(basename "$l")  (リポから消えたため除去)"
        pruned=$((pruned + 1))
      else
        echo "  DANGLE : $(basename "$l") -> $tgt  (リポに実体無し。--prune で除去可)"
        warncnt=$((warncnt + 1))
      fi
    fi
  done
done

# 5) 致命チェック: settings.json が参照する hook が全て実在するか
echo "-- settings.json 参照 hook の実在検査"
missing_hook=0
# hook として発火するのは "command" 行のみ。permissions の allow 文字列
# (例: "Bash(~/.claude/hooks/xxx:*)") は tool ブロックに無関係なので対象外にする。
refs="$(grep -E '"command"' "$REPO_DIR/settings.json" 2>/dev/null \
  | grep -oE '(~|\$CLAUDE_HOME|\$HOME)/\.claude/hooks/[A-Za-z0-9._-]+' | sort -u || true)"
if [ -n "$refs" ]; then
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    name="$(basename "$ref")"
    if [ ! -e "$CLAUDE_DIR/hooks/$name" ]; then
      echo "  FATAL  : settings.json が参照する hook が実在しない: $name  (この hook 発火 tool が全ブロックされる)"
      missing_hook=$((missing_hook + 1))
    fi
  done <<EOF
$refs
EOF
fi

echo
echo "==> 完了: link=$linked fix=$fixed ok=$okcnt warn=$warncnt prune=$pruned"
if [ "$missing_hook" -gt 0 ]; then
  echo "!! settings.json 参照 hook が $missing_hook 件欠落。hooks/ にファイルが存在するか確認してください。" >&2
  exit 1
fi
if [ "$warncnt" -gt 0 ]; then
  exit 2
fi
