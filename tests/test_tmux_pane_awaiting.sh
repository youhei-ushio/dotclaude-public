#!/bin/bash
# Regression tests for hooks/tmux-pane-awaiting.sh (応答待ち=赤 / 完了=緑 の状態遷移)。
#
# 実行: bash tests/test_tmux_pane_awaiting.sh
# 前提:
#   - リポ内 hooks/tmux-pane-awaiting.sh を直接実行する (~/.claude への symlink 状況に非依存)。
#   - tmux と python3 が必要 (tool_sig が python3 を使う)。無ければ SKIP。
#   - 専用 socket (-L) で隔離した tmux サーバを起動し、本番 tmux に影響しない。
#
# 検証対象 (2 つの既知バグの回帰):
#   症状① 関係ないのに赤が残る … ツール無しで Stop しても input(赤) が残らないこと。
#   症状② 応答待ちなのに赤が消える … 並列バッチで別 tool の PostToolUse が pending 中の
#          赤を消さないこと (input を立てた当の tool の完了でのみ赤が消える厳密一致)。

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO/hooks/tmux-pane-awaiting.sh"
[ -f "$HOOK" ] || { echo "HOOK not found: $HOOK"; exit 1; }

command -v tmux >/dev/null 2>&1 || { echo "SKIP: tmux not available"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 0; }

SOCK="tpa_test_$$"
SESSION="t"
FAIL=0

cleanup() { tmux -L "$SOCK" kill-server 2>/dev/null; }
trap cleanup EXIT

# 隔離サーバ + 1 ペインを用意し、その socket_path と pane_id を取得する。
tmux -L "$SOCK" new-session -d -s "$SESSION" -x 80 -y 24 2>/dev/null \
  || { echo "SKIP: cannot start tmux server (no PTY?)"; exit 0; }
SOCKET_PATH=$(tmux -L "$SOCK" display -p '#{socket_path}')
PANE=$(tmux -L "$SOCK" list-panes -t "$SESSION" -F '#{pane_id}' | head -1)

# hook は bare `tmux` を使い $TMUX (先頭フィールド=socket) を参照する。
export TMUX="$SOCKET_PATH,0,0"
export TMUX_PANE="$PANE"

# 直接 pane オプションを操作 (前提条件のセットアップ用)。
setopt() { tmux -L "$SOCK" set -p -t "$PANE" "$1" "$2"; }
getopt() { tmux -L "$SOCK" show -p -t "$PANE" -v "$1" 2>/dev/null; }

# payload を stdin で渡して hook を 1 回起動。
fire() { printf '%s' "$1" | sh "$HOOK"; }

assert_eq() {  # $1=name $2=expected $3=actual
  if [ "$2" = "$3" ]; then
    printf 'PASS  %s\n' "$1"
  else
    printf 'FAIL  %s  (expected=[%s] actual=[%s])\n' "$1" "$2" "$3"
    FAIL=1
  fi
}

# --- payload 定義 (tool_input は PermissionRequest と PostToolUse で同一にして sig を一致させる) ---
PR_BASH_X='{"hook_event_name":"PermissionRequest","cwd":"/home/me/repos/myapp-parallel-3","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}'
PTU_BASH_X='{"hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"},"tool_use_id":"toolu_A"}'
PTU_READ_SIB='{"hook_event_name":"PostToolUse","tool_name":"Read","tool_input":{"file_path":"/tmp/y"},"tool_use_id":"toolu_B"}'
PTU_BASH_DIFF='{"hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"echo other"},"tool_use_id":"toolu_C"}'
PR_ASK='{"hook_event_name":"PermissionRequest","cwd":"/home/me/repos/myapp-parallel-3","tool_name":"AskUserQuestion","tool_input":{"questions":[{"q":"?"}]}}'
UPS='{"hook_event_name":"UserPromptSubmit"}'
STOP='{"hook_event_name":"Stop"}'
# 実行中サブエージェントが居る Stop (background_tasks に running な subagent)
STOP_SUB_RUNNING='{"hook_event_name":"Stop","background_tasks":[{"id":"a1","type":"subagent","status":"running","agent_type":"Explore"}]}'
# サブが完了済みの Stop (running なし)
STOP_SUB_DONE='{"hook_event_name":"Stop","background_tasks":[{"id":"a1","type":"subagent","status":"completed"}]}'
SS_CLEAR='{"hook_event_name":"SessionStart","source":"clear"}'
# サブ完了による再起動の UserPromptSubmit (prompt が <task-notification>)
UPS_NOTIF='{"hook_event_name":"UserPromptSubmit","prompt":"<task-notification>\n<task-id>a1</task-id>\n<result>done</result>\n</task-notification>"}'
# 人間の新規指示の UserPromptSubmit
UPS_HUMAN='{"hook_event_name":"UserPromptSubmit","prompt":"次のバグを直して"}'

reset() { setopt @pstate ""; setopt @didwork 0; setopt @await_sig ""; setopt @notif_turn 0; }

# === T1: PermissionRequest で input(赤) が立ち @await_sig が記録される ===
reset
fire "$PR_BASH_X"
assert_eq "T1a PermissionRequest -> @pstate=input" "input" "$(getopt @pstate)"
assert_eq "T1b @await_sig recorded (non-empty)" "yes" "$([ -n "$(getopt @await_sig)" ] && echo yes || echo no)"

# === T2 (症状②本丸): pending 中、別 tool の PostToolUse では赤が消えない ===
reset
fire "$PR_BASH_X"                       # input + sig(Bash X)
fire "$PTU_READ_SIB"                    # 兄弟 (別 tool_name/input) -> 赤維持
assert_eq "T2a sibling Read PostToolUse keeps input" "input" "$(getopt @pstate)"
fire "$PTU_BASH_DIFF"                   # 同 tool_name 別 input -> 赤維持 (tool_input まで見る証拠)
assert_eq "T2b same-name diff-input PostToolUse keeps input" "input" "$(getopt @pstate)"
assert_eq "T2c @didwork set by PostToolUse" "1" "$(getopt @didwork)"

# === T3: input を立てた当の tool の PostToolUse でだけ赤が消える (厳密一致) ===
reset
fire "$PR_BASH_X"
fire "$PTU_BASH_X"                      # 一致 -> 解除
assert_eq "T3a matching PostToolUse clears input" "" "$(getopt @pstate)"
assert_eq "T3b @await_sig cleared on match" "" "$(getopt @await_sig)"

# === T4 (症状①本丸): ツール無しで Stop しても赤が残らない ===
reset
fire "$UPS"
fire "$PR_ASK"                          # AskUserQuestion で input (赤)
assert_eq "T4a AskUserQuestion -> input" "input" "$(getopt @pstate)"
fire "$STOP"                            # didwork=0 のまま Stop -> 無印 (赤は残さない)
assert_eq "T4b tool-less Stop clears stale input" "" "$(getopt @pstate)"
assert_eq "T4c @await_sig cleared at Stop" "" "$(getopt @await_sig)"

# === T5: ツール作業を伴ったターンの Stop は done(緑) ===
reset
fire "$UPS"
fire "$PTU_READ_SIB"                    # pstate 空のまま didwork=1 (sig 判定はしない)
assert_eq "T5a PostToolUse on empty keeps empty" "" "$(getopt @pstate)"
fire "$STOP"
assert_eq "T5b work then Stop -> done" "done" "$(getopt @pstate)"

# === T6: input + 当該 tool 完了 + 作業 の後 Stop は done ===
reset
fire "$UPS"
fire "$PR_BASH_X"
fire "$PTU_BASH_X"                      # 解除 + didwork=1
assert_eq "T6a cleared after match" "" "$(getopt @pstate)"
fire "$STOP"
assert_eq "T6b -> done" "done" "$(getopt @pstate)"

# === T7: done は二重 Stop で維持され、次の指示 (UserPromptSubmit) でクリア ===
# (先頭 reset で自己完結。前ケースの状態に依存しない)
reset
fire "$UPS_HUMAN"
fire "$PTU_READ_SIB"                    # 作業 (didwork=1)
fire "$STOP"                            # done(緑) を点ける
assert_eq "T7a work then Stop -> done" "done" "$(getopt @pstate)"
fire "$STOP"                            # 二重 Stop でも done を維持
assert_eq "T7b double Stop keeps done" "done" "$(getopt @pstate)"
fire "$UPS_HUMAN"
assert_eq "T7c UserPromptSubmit clears done" "" "$(getopt @pstate)"
assert_eq "T7d UserPromptSubmit resets didwork" "0" "$(getopt @didwork)"

# === T8: SessionStart(clear) で全状態リセット ===
reset
fire "$PR_BASH_X"                       # input + sig
fire "$SS_CLEAR"
assert_eq "T8a SessionStart clears pstate" "" "$(getopt @pstate)"
assert_eq "T8b SessionStart clears await_sig" "" "$(getopt @await_sig)"
assert_eq "T8c SessionStart clears notif_turn" "0" "$(getopt @notif_turn)"

# === T9 (誤緑本丸その1): 実行中サブが居るターンの Stop は緑にしない ===
reset
fire "$UPS_HUMAN"
fire "$PTU_READ_SIB"                    # 何か作業 (didwork=1)
fire "$STOP_SUB_RUNNING"                # background_tasks に running サブ -> 完了でない
assert_eq "T9 Stop with running subagent is NOT done" "" "$(getopt @pstate)"

# === T10 (誤緑本丸その2): サブ完了通知由来の中間処理ターンの Stop は緑にしない ===
reset
fire "$UPS_NOTIF"                       # <task-notification> 由来 -> @notif_turn=1
assert_eq "T10a task-notification sets notif_turn" "1" "$(getopt @notif_turn)"
fire "$PTU_READ_SIB"                    # 通知ターンで作業 (didwork=1)
fire "$STOP_SUB_DONE"                   # running サブは居ないが notif_turn=1 -> 緑にしない
assert_eq "T10b Stop on task-notification turn is NOT done" "" "$(getopt @pstate)"

# === T11: 人間の指示ターンで作業して停止、走るサブも無ければ通常どおり緑 ===
reset
fire "$UPS_HUMAN"                       # 人間の指示 -> @notif_turn=0
assert_eq "T11a human prompt clears notif_turn" "0" "$(getopt @notif_turn)"
fire "$PTU_READ_SIB"                    # 作業 (didwork=1)
fire "$STOP"                            # running サブ無し + notif_turn=0 -> done(緑)
assert_eq "T11b human turn, work, no sub -> done(緑)" "done" "$(getopt @pstate)"

# === T12: 人間ターンでも background_tasks に running サブが居れば緑にしない ===
reset
fire "$UPS_HUMAN"
fire "$PTU_READ_SIB"
fire "$STOP_SUB_RUNNING"
assert_eq "T12 human turn but subagent running -> NOT done" "" "$(getopt @pstate)"

# === T13: completed のみ (running 無し) の background_tasks は緑を妨げない ===
reset
fire "$UPS_HUMAN"
fire "$PTU_READ_SIB"
fire "$STOP_SUB_DONE"                   # status=completed のみ、notif_turn=0 -> done
assert_eq "T13 completed-only subagent does not block green" "done" "$(getopt @pstate)"

# === T14: 抑止 Stop の後、同ターンでサブが消えて二重 Stop しても偽の緑が点かない ===
# (抑止分岐で @didwork=0 に落とす保証の回帰。落とさないと 2 回目の Stop で done になる)
reset
fire "$UPS_HUMAN"                       # notif_turn=0
fire "$PTU_READ_SIB"                    # didwork=1
fire "$STOP_SUB_RUNNING"                # running サブで抑止 -> 無印 + didwork=0
assert_eq "T14a suppressed Stop is NOT done" "" "$(getopt @pstate)"
assert_eq "T14b suppressed Stop clears didwork" "0" "$(getopt @didwork)"
fire "$STOP"                            # サブ消失後の二重 Stop。didwork=0 なので緑にならない
assert_eq "T14c double Stop after suppression stays NOT done" "" "$(getopt @pstate)"

# === T15: input が残ったまま作業ありで Stop → done (古い input は緑で上書き) ===
# Stop 時点で許可は解決済みの前提。input が残り + 作業あり + 走るサブ無しなら done が正。
reset
fire "$UPS_HUMAN"
fire "$PR_BASH_X"                       # input + sig(Bash X)
fire "$PTU_READ_SIB"                    # 別 tool 完了 (didwork=1、sig 不一致で input は残る)
assert_eq "T15a input remains before Stop" "input" "$(getopt @pstate)"
fire "$STOP"                            # input 残り + didwork=1 + サブ無し -> done
assert_eq "T15b stale input + work at Stop -> done" "done" "$(getopt @pstate)"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ALL PASS"
else
  echo "SOME FAILED"
fi
exit "$FAIL"
