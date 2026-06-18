#!/usr/bin/env bash
#
# tmux-grid.sh
#   固定 3×2 グリッドの tmux セッションを作り、各ペインで worktree の
#   Claude Code を起動する。ペインID で位置を確定させているので、
#   ターミナルの縦横比に関係なく必ず「3列×2行」になる。
#
#   レイアウト (PARALLELS=5 / DIR_PREFIX=myproject-parallel の例):
#     [1] [2] [3]    ← 上段 (myproject-parallel-1,2,3)
#     [4] [5] [ ]    ← 下段 (myproject-parallel-4,5 / 右下は空ターミナル)
#
#   使い方:
#     chmod +x tmux-grid.sh
#     ./tmux-grid.sh [セッション名]                 # 省略時は "parallel"。各ペインは -c 付き (直近会話を継続) で起動
#     ./tmux-grid.sh [セッション名] --no-continue   # -c 無しで起動 (設定/会話をリセットして新規で始めたいとき)
#
#   プロジェクトに合わせて DIR_PREFIX / NAME_PREFIX / BASE / PARALLELS を
#   環境変数で上書きできる (下記デフォルトはサンプル):
#     DIR_PREFIX=myapp-parallel NAME_PREFIX=myapp PARALLELS=3 ./tmux-grid.sh
#
#   既に同名セッションがあれば、新規作成せずアタッチするだけ。
#
set -euo pipefail

# ===== 設定（環境変数で上書き可。デフォルトはサンプル値） =====
# 引数 (順不同):
#   [セッション名]        位置引数。省略時は "parallel"
#   -n / --no-continue   各ペインの claude を -c 無し (新規会話) で起動する。
#                        既定は -c 付き (cwd 単位で直近会話を継続)。設定/会話を
#                        リセットして始めたいときに付ける。
SESSION=""
SEEN_POS=0                    # 位置引数を受け取ったか (空文字セッション名でも数える)
CONTINUE="-c"                 # 既定: 直近会話を継続 (-c)。--no-continue で空にする
for arg in "$@"; do
  case "$arg" in
    -n|--no-continue) CONTINUE="" ;;
    -*) echo "不明なオプション: $arg (使えるのは -n / --no-continue)" >&2; exit 1 ;;
    *)  if [ "$SEEN_POS" -eq 1 ]; then
          echo "位置引数 (セッション名) は 1 個まで (余分な引数: '$arg')" >&2; exit 1
        fi
        SEEN_POS=1
        SESSION="$arg" ;;
  esac
done
SESSION="${SESSION:-parallel}"   # 位置引数省略時 (または空文字) は "parallel"
BASE="${BASE:-$HOME/repos}"               # worktree の親ディレクトリ
DIR_PREFIX="${DIR_PREFIX:-myproject-parallel}"  # worktree ディレクトリ = $BASE/$DIR_PREFIX-N
NAME_PREFIX="${NAME_PREFIX:-myproject}"   # claude --name = $NAME_PREFIX-N
                              # ※ NAME_PREFIX / DIR_PREFIX は send-keys でペインの
                              #   シェルに送出されるため、英数字・ハイフン等のシェル
                              #   安全なトークンのみにすること（空白・特殊文字は不可）。
PARALLELS="${PARALLELS:-5}"   # Claude Code を起動する worktree 数 (1〜6)
                              # グリッドは常に 3×2(6ペイン)。余りは空ターミナル。
# ===============================================

# 設定値の検証: PARALLELS は 1〜6 の整数のみ許可
case "$PARALLELS" in
  [1-6]) ;;
  *) echo "PARALLELS は 1〜6 の整数で指定してください (現在: '$PARALLELS')" >&2; exit 1 ;;
esac

# NAME_PREFIX / DIR_PREFIX は send-keys でペインのシェルにそのまま送出されるため、
# 空白・特殊文字が混入するとコマンドインジェクション相当になる。英数字・ハイフン・
# アンダースコアのみ許可する (注意コメントだけに頼らず機械的に弾く)。
case "$NAME_PREFIX$DIR_PREFIX" in
  *[!A-Za-z0-9_-]*)
    echo "NAME_PREFIX / DIR_PREFIX は英数字・ハイフン・アンダースコアのみ可 (現在: '$NAME_PREFIX' / '$DIR_PREFIX')" >&2
    exit 1 ;;
esac

wt()    { printf '%s/%s-%s' "$BASE" "$DIR_PREFIX" "$1"; }
cname() { printf '%s-%s' "$NAME_PREFIX" "$1"; }

# ペイン i の起動ディレクトリ: worktree があればそこ、無ければ $BASE
pane_dir() {
  local i="$1"
  if [ "$i" -le "$PARALLELS" ]; then wt "$i"; else printf '%s' "$BASE"; fi
}

# セッションへ移る。tmux 内から実行された場合は attach できない (nested) ため
# switch-client を使う。
attach_session() {
  if [ -n "${TMUX:-}" ]; then
    exec tmux switch-client -t "$SESSION"
  else
    exec tmux attach -t "$SESSION"
  fi
}

# 既にセッションがあれば、そのままアタッチ
if tmux has-session -t "$SESSION" 2>/dev/null; then
  attach_session
fi

# worktree ディレクトリの存在チェック (1..PARALLELS のみ)
for i in $(seq 1 "$PARALLELS"); do
  if [ ! -d "$(wt "$i")" ]; then
    echo "worktree が見つかりません: $(wt "$i")" >&2
    exit 1
  fi
done

# --- 上段の3列を作る ---
tmux new-session -d -s "$SESSION" -c "$(pane_dir 1)"
A=$(tmux display -t "$SESSION" -p '#{pane_id}')
B=$(tmux split-window -h -t "$A" -c "$(pane_dir 2)" -P -F '#{pane_id}')
C=$(tmux split-window -h -t "$B" -c "$(pane_dir 3)" -P -F '#{pane_id}')
tmux select-layout -t "$A" even-horizontal      # 3等幅の列に整列

# --- 各列を上下に割って下段を作る ---
D=$(tmux split-window -v -t "$A" -c "$(pane_dir 4)" -P -F '#{pane_id}')
E=$(tmux split-window -v -t "$B" -c "$(pane_dir 5)" -P -F '#{pane_id}')
F=$(tmux split-window -v -t "$C" -c "$(pane_dir 6)" -P -F '#{pane_id}')

# --- ペイン状態をボーダーで示す設定 ---
#   各ペイン (Claude Code) は hooks/tmux-pane-awaiting.sh が自分の pane オプション
#   @pstate (input=応答待ち / done=完了 / 空=作業中) を切り替える。ここでは見た目を定義:
#     input → 赤背景「⏳ PN 待機」 / done → 緑背景「✓ PN 完了」 / それ以外 → 淡色「PN」
#   書式は #{?cond,then,else} の 3 段ネスト (分岐順 input > done > work、閉じ括弧 3 個)。
#   各 then 句末の #[default] は必須。#[...] 内のリテラルカンマは #, でエスケープする。
# ペイン境界線を太線字形 (heavy box-drawing) にして見やすくする (tmux 3.3+)。
# 実際の太さはフォント依存 (heavy 字形を太く描くフォントで効果が出る)。
tmux set-option -t "$SESSION" pane-border-lines heavy
tmux set-option -t "$SESSION" pane-border-status top
tmux set-option -t "$SESSION" pane-border-format \
  '#{?#{==:#{@pstate},input},#[fg=colour231#,bg=colour196#,bold] ⏳ P#{@pnum} 待機 #[default],#{?#{==:#{@pstate},done},#[fg=colour231#,bg=colour028#,bold] ✓ P#{@pnum} 完了 #[default],#{?@pnum,#[fg=colour244] P#{@pnum} #[default],}}}'

# --- 1..PARALLELS のペインだけ Claude Code 起動。残りは空ターミナルのまま ---
#   ペインは split-window -c で worktree に cd 済みなので、そのまま claude を起動。
#   $CONTINUE 既定 "-c": その cwd の直近会話を継続する (--no-continue で空になり新規起動)。
panes=("$A" "$B" "$C" "$D" "$E" "$F")
i=1
for p in "${panes[@]}"; do
  if [ "$i" -le "$PARALLELS" ]; then
    # ボーダー表示用に P 番号と状態初期値 (空=作業中) を設定してから起動
    tmux set -p -t "$p" @pnum "$i"
    tmux set -p -t "$p" @pstate ""
    tmux set -p -t "$p" @didwork 0
    tmux set -p -t "$p" @await_sig ""
    tmux set -p -t "$p" @notif_turn 0
    tmux send-keys -t "$p" "claude ${CONTINUE:+$CONTINUE }--name $(cname "$i")" C-m
  fi
  i=$((i + 1))
done

# 左上を選択してアタッチ
tmux select-pane -t "$A"
tmux rename-window -t "$SESSION" parallel
attach_session

