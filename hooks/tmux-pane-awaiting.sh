#!/bin/sh
# tmux-pane-awaiting.sh
#
# 並走 clone (`<project>-parallel-N`) を tmux 6 ペイングリッド (tmux-grid.sh) で動かす際、各ペインの
# 状態を **そのペインのボーダー** で示す。Claude Code の statusline は各ペイン最下部に
# 出て 6 グリッドだと対象ペインが分かりにくいため、tmux ボーダー側に出す。
# (ファイル名は配線安定のため awaiting のままだが、現在は応答待ち + 完了の両方を扱う)
#
# 発火ペイン ($TMUX_PANE) の pane オプションを切り替える:
#   @pstate  … input (応答待ち=赤) / done (完了=緑) / 空 (作業中・無印)
#   @didwork … そのターンでツール実行があったか (1/0)。done 判定に使う
#   @pnum    … P 番号 (通常は tmux-grid.sh が起動時に設定。本 hook は cwd から補完)
# 表示書式は tmux-grid.sh が pane-border-format で定義する。
#
# イベント遷移:
#   PermissionRequest  → @pstate=input             (今ユーザー判断が必要 = 赤)
#   PostToolUse        → @didwork=1、@pstate を空に  (= 作業再開・無印)
#   Stop               → @pstate=input なら維持 / @didwork=1 なら done(緑)+@didwork=0
#                        / それ以外 (ツール無しの会話ターン) は空 (= 完了通知しない)
#   UserPromptSubmit   → @pstate 空 + @didwork=0    (新しい指示 = 作業中へ)
#   SessionStart(clear|startup) → @pstate 空 + @didwork=0
#
# 「完了 (緑)」は **ツール作業を伴ったターンが Stop した時だけ** 点灯する。短い会話の
# 返事 (ツール無し) では点かない (完了通知の誤発火を避けるため)。応答待ち (赤) が立って
# いる間は Stop でも緑で上書きしない (入力要求を優先)。
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
get() {  # $1 = @pstate | @didwork
  tmux show -p -t "$TMUX_PANE" -v "$1" 2>/dev/null
}

case "$EVENT" in
  PermissionRequest)
    # cwd→PNUM はこの分岐でだけ必要 (高頻度の PostToolUse 等では parse しない)。
    # @pnum は通常 tmux-grid.sh が起動時に設定済み。ここでの設定は grid を経由せず
    # 単独で起動した Claude 用のフォールバック (cwd から P 番号を補完)。
    PNUM=$(json_str cwd | sed -n 's#.*-parallel-\([0-9][0-9]*\).*#\1#p' | head -1)
    [ -n "$PNUM" ] && tmux set -p -t "$TMUX_PANE" @pnum "$PNUM" 2>/dev/null
    set_pstate input
    ;;
  PostToolUse)
    # 全ツールで高頻度発火する。そのターンで作業した印 (@didwork=1) を立て、直前の
    # input/done 表示は作業再開とみなしクリアする。コスト面: @didwork は
    # pane-border-format が参照しないので set しても再描画は起きず安価。border 再描画を
    # 伴う @pstate の set は「非空のときだけ」guard 済み (作業中=空の通常時は書かない)。
    # hook 自体が毎発火する分のコストは上の lean parse (EVENT のみ) で最小化している。
    set_didwork 1
    [ -n "$(get @pstate)" ] && set_pstate ""
    ;;
  Stop)
    # ツール作業を伴ったターンの終了だけ done(緑)。応答待ち(input)は緑で上書きしない
    # (awaiting シグナルを優先して落とさない安全側)。
    # 既知の制約: AskUserQuestion/ExitPlanMode の回答後に**ツール実行を伴わず**会話
    # だけで Stop すると、input をクリアする PostToolUse が来ないため赤が残りうる。
    # 次の UserPromptSubmit で解消する。実害は限定的なので現状の安全側を採用。
    if [ "$(get @pstate)" = "input" ]; then
      :
    elif [ "$(get @pstate)" = "done" ]; then
      # 既に done(緑)。同ターンで Stop が二重発火しても緑を消さない
      # (「done は次の指示まで残る」契約を堅牢化)。
      :
    elif [ "$(get @didwork)" = "1" ]; then
      set_pstate done
      set_didwork 0
    else
      set_pstate ""
    fi
    ;;
  UserPromptSubmit)
    set_pstate ""
    set_didwork 0
    ;;
  SessionStart)
    # source はこの分岐でだけ必要
    case "$(json_str source)" in
      clear|startup) set_pstate ""; set_didwork 0 ;;
    esac
    ;;
esac

exit 0
