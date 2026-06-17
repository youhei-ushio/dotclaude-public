#!/bin/sh
# tmux-pane-awaiting.sh
#
# 並走 `<project>-parallel-N` を tmux 6 ペイングリッド (tmux-grid.sh) で動かす際、各ペインの
# 状態を **そのペインのボーダー** で示す。Claude Code の statusline は各ペイン最下部に
# 出て 6 グリッドだと対象ペインが分かりにくいため、tmux ボーダー側に出す。
# (ファイル名は配線安定のため awaiting のままだが、現在は応答待ち + 完了の両方を扱う)
#
# 発火ペイン ($TMUX_PANE) の pane オプションを切り替える:
#   @pstate    … input (応答待ち=赤) / done (完了=緑) / 空 (作業中・無印)
#   @didwork   … そのターンでツール実行があったか (1/0)。done 判定に使う
#   @pnum      … P 番号 (通常は tmux-grid.sh が起動時に設定。本 hook は cwd から補完)
#   @await_sig … input を立てた「当の tool」の signature (tool_name + tool_input ハッシュ)。
#                並列バッチで別 tool の PostToolUse が赤を誤って落とすのを防ぐ厳密一致用。
#   @notif_turn … このターンがサブ完了の <task-notification> 由来の中間処理か (1/0)。
#                 立っている間の Stop は完了(緑)にしない (大元タスクの続きであって完了でない)。
# 表示書式は tmux-grid.sh が pane-border-format で定義する。
#
# イベント遷移:
#   PermissionRequest  → @pstate=input + @await_sig=この tool の sig (ユーザー判断待ち = 赤)
#   PostToolUse        → @didwork=1。@pstate=input かつ sig が @await_sig と一致した時だけ
#                        input を解除 (= その許可を出した当の tool が完了した = 待機解消)
#   Stop               → @pstate=done なら維持 / **実行中サブエージェント (background_tasks) が
#                        居る or @notif_turn=1 なら空 (大元未完=緑にしない)** / @didwork=1 なら
#                        done(緑)+@didwork=0 / それ以外 (input 残り含む) は空。
#                        Stop 時点では許可は必ず解決済み (許可待ちでブロック中は Stop が
#                        発火しない) なので古い input は安全に落とす
#   UserPromptSubmit   → @pstate 空 + @didwork=0 + @await_sig 空、prompt が <task-notification>
#                        なら @notif_turn=1 (サブ完了の再起動) / 人間の指示なら @notif_turn=0
#   SessionStart(clear|startup) → @pstate 空 + @didwork=0 + @await_sig 空 + @notif_turn=0
#
# 「完了 (緑)」は **ツール作業を伴ったターンが Stop した時だけ** 点灯する。短い会話の
# 返事 (ツール無し) では点かない (ツール無しの短い返事で緑を乱発しない設計)。**さらに
# サブエージェント関連の偽完了を防ぐため、実行中サブが居るターン / サブ完了通知由来の
# 中間処理ターンでは緑にしない**。代償として、サブ完了で締めくくる自律オーケストレーション
# は最終の緑バッジも出ない (結果テキストは出る)。
#
# 応答待ち (赤) の解除は「input を立てた当の tool の完了」に厳密一致させる。これにより:
#   - 並列バッチで別 tool の PostToolUse が pending 中の赤を巻き込んで消す誤りを防ぐ
#     (= 「応答待ちなのに赤が消える」の解消)
#   - 古い input は Stop で必ず落ちるので、ツール無し会話で終わっても赤は残らない
#     (= 「関係ないのに赤が残る」の解消)
#
# tmux 外 / tmux 不在では何もしない。例外は飲み込み必ず exit 0
# (hook 失敗で Claude Code を止めない原則)。

[ -n "${TMUX:-}" ] || exit 0
[ -n "${TMUX_PANE:-}" ] || exit 0
command -v tmux >/dev/null 2>&1 || exit 0

# hook JSON を 1 行化して読む (compact JSON 前提、念のため改行を潰す)
payload=$(cat 2>/dev/null | tr '\n' ' ')

# 単純な文字列値を JSON から取り出す (event / cwd / source はいずれも特殊文字を
# 含まない素直な値なので grep+sed で十分。python3 spawn を避けて軽量に)。
# grep -o で **最初に現れる** "key":"value" を取る。先頭 .* を貪欲マッチさせると
# tool_input.cwd 等のネストした同名キーの「最後の」一致を拾い、PNUM を取り違える。
# 前提: top-level の cwd が payload の出現順で nested な同名キーより先に来ること
# (実測の payload では常に成立。出現順依存なので、将来 payload 順が変わって取り違えが
# 再発したらここが起点)。
json_str() {
  printf '%s' "$payload" \
    | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
    | head -1 \
    | sed "s/^\"$1\"[[:space:]]*:[[:space:]]*\"\(.*\)\"\$/\1/"
}

# EVENT のみ常時 parse する。cwd / source は必要な分岐 (PermissionRequest /
# SessionStart) の中でだけ parse し、高頻度発火の PostToolUse 等で無駄な
# grep+sed を走らせない (lean fast path)。
EVENT=$(json_str hook_event_name)

set_pstate() {  # $1 = input | done | "" (空=作業中)
  tmux set -p -t "$TMUX_PANE" @pstate "$1" 2>/dev/null
}
set_didwork() {  # $1 = 0 | 1
  tmux set -p -t "$TMUX_PANE" @didwork "$1" 2>/dev/null
}
set_sig() {  # $1 = signature 文字列 ("" でクリア)
  tmux set -p -t "$TMUX_PANE" @await_sig "$1" 2>/dev/null
}
set_notif() {  # $1 = 0 | 1 (このターンがサブ完了 task-notification 由来の中間処理か)
  tmux set -p -t "$TMUX_PANE" @notif_turn "$1" 2>/dev/null
}
get() {  # $1 = @pstate | @didwork | @await_sig | @notif_turn
  tmux show -p -t "$TMUX_PANE" -v "$1" 2>/dev/null
}

# input を立てた「当の tool」を識別する signature。PermissionRequest と PostToolUse の
# 両 payload に共通して存在するのは tool_name + tool_input だけ (PermissionRequest payload
# には tool_use_id が無い — 実測で確認済み)。両者を正規化 JSON (sort_keys) でハッシュし
# 「同一 tool 呼び出し」を判定する。
# python3 は他 hook も前提とする。万一不在/失敗時は空を返し、PostToolUse 側の guard で
# 「一致せず = 赤を消さない」安全側に倒れる (その場合でも赤は Stop で必ず解消するため
# stuck しない)。
# 前提: 両 event の tool_input が完全一致すること。将来 Claude Code がどちらかで tool_input を
# 正規化/省略すると sig 不一致で「赤が PostToolUse で消えず Stop まで残る」症状になる
# (それでも安全側=偽の消去はしない)。回帰時はここが起点。
tool_sig() {
  printf '%s' "$payload" | python3 -c '
import sys, json, hashlib
try:
    d = json.load(sys.stdin)
    ti = json.dumps(d.get("tool_input", {}), sort_keys=True, ensure_ascii=False)
    h = hashlib.sha1(ti.encode("utf-8")).hexdigest()[:16]
    print((d.get("tool_name") or "") + ":" + h)
except Exception:
    pass
' 2>/dev/null
}

# Stop payload の background_tasks に「実行中のサブエージェント」が居るか (1/0)。
# background_tasks は実測で [{"type":"subagent","status":"running",...}] 形式。これが在る間は
# 大元のタスクは未完なので Stop でも完了(緑)にしない。Stop は低頻度なので python3 spawn で可。
# スコープは意図的に type=="subagent" かつ status=="running" に限定: subagent 以外の
# background タスク (例: バックグラウンド Bash) は緑を妨げない。status 値は実測の "running" に
# 依存しており、将来 Claude Code が別の中間 status (paused/queued 等) を導入すると completed と
# 同様「緑を妨げない」側に倒れる。緑が想定外に復活したらこの判定が起点。
running_subagent() {
  printf '%s' "$payload" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    bt = d.get("background_tasks") or []
    run = any(isinstance(t, dict) and t.get("type") == "subagent" and t.get("status") == "running" for t in bt)
    print("1" if run else "0")
except Exception:
    print("0")
' 2>/dev/null
}

case "$EVENT" in
  PermissionRequest)
    # cwd→PNUM はこの分岐でだけ必要 (高頻度の PostToolUse 等では parse しない)。
    # @pnum は通常 tmux-grid.sh が起動時に設定済み。ここでの設定は grid を経由せず
    # 単独で起動した Claude 用のフォールバック (cwd から P 番号を補完)。
    PNUM=$(json_str cwd | sed -n 's#.*-parallel-\([0-9][0-9]*\).*#\1#p' | head -1)
    [ -n "$PNUM" ] && tmux set -p -t "$TMUX_PANE" @pnum "$PNUM" 2>/dev/null
    set_sig "$(tool_sig)"
    set_pstate input
    ;;
  PostToolUse)
    # 全ツールで高頻度発火する。そのターンで作業した印 (@didwork=1) を立てる。
    # 応答待ち(input)を消すのは「その input を立てた当の tool が完了したとき」だけ —
    # sig が @await_sig と一致した場合に限る。これで並列バッチの別 tool 完了が pending 中の
    # 赤を巻き込んで消す誤りを防ぐ。input でない通常時 (=空) は sig (python3 spawn) を
    # 計算しないので hot path は軽いまま。@didwork は pane-border-format が参照しないので
    # set しても再描画は起きず安価。
    set_didwork 1
    if [ "$(get @pstate)" = "input" ]; then
      s=$(tool_sig)
      if [ -n "$s" ] && [ "$s" = "$(get @await_sig)" ]; then
        set_pstate ""
        set_sig ""
      fi
    fi
    ;;
  Stop)
    # 完了(緑)は「ツール作業を伴って停止し、かつ大元のタスクが本当に終わっている」時だけ。
    # @pstate=input が Stop 時点まで残っている = その許可は既に解決済み (許可待ちで
    # ブロック中はそもそも Stop が発火しない)。よって古い input は安全に落とす。
    # 大元が未完なのに緑を出さないため、次の 2 つでは緑にしない (= サブ境界の偽完了通知を防ぐ):
    #   1. background_tasks に実行中のサブエージェントが居る (まだ走っている)
    #   2. @notif_turn=1 — このターンがサブ完了の <task-notification> 由来の中間処理ターン
    #      (サブ完了で main が再起動された処理ターン。大元の続きであって完了ではない)
    # @didwork=1 (作業あり) を緑判定のゲートにする: 緑になりうるのは作業したターンだけ
    # なので、running_subagent (python3 spawn) を評価するのも @didwork=1 の時だけで足りる。
    # 抑止に該当した場合も @didwork=0 に落として「このターンは完了扱いしない」を状態へ反映
    # する。これで同ターンで Stop が二重発火しても、2 回目に古い @didwork=1 が残って偽の緑が
    # 点くことがない。
    if [ "$(get @pstate)" = "done" ]; then
      # 既に done(緑)。同ターンで Stop が二重発火しても緑を消さない
      # (「done は次の指示まで残る」契約を堅牢化)。
      :
    elif [ "$(get @didwork)" = "1" ]; then
      if [ "$(running_subagent)" = "1" ] || [ "$(get @notif_turn)" = "1" ]; then
        # @notif_turn は「次の UserPromptSubmit まで」のターン属性。ここでは敢えて 0 に
        # 戻さない: notif ターン内で Stop が複数回起きても全て抑止し続けるため (Stop で
        # 落とすと、同ターンで作業が続いた 2 回目の Stop が緑になり偽完了が復活する)。
        set_pstate ""
      else
        set_pstate done
      fi
      set_didwork 0
    else
      set_pstate ""
    fi
    set_sig ""
    ;;
  UserPromptSubmit)
    set_pstate ""
    set_didwork 0
    set_sig ""
    # このターンがサブ完了の再起動 (prompt が <task-notification>) か、人間の新規指示かを記録。
    # 前者の Stop は中間処理として緑にしない (大元の続き)。後者は通常どおり完了で緑になりうる。
    case "$payload" in
      *'<task-notification>'*) set_notif 1 ;;
      *) set_notif 0 ;;
    esac
    ;;
  SessionStart)
    # source はこの分岐でだけ必要
    case "$(json_str source)" in
      clear|startup) set_pstate ""; set_didwork 0; set_sig ""; set_notif 0 ;;
    esac
    ;;
esac

exit 0
