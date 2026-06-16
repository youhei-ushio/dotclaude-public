#!/bin/bash
# Claude Code statusline - 最大3行構成
# 1行目: セッション名 | ブランチ | ディレクトリ
# 2行目: モデル | コンテキストバー | コスト | 5h/7dレートリミット
# 3行目: 未レビュー許可要求の件数 (pending review、0 件のときは非表示)

input=$(cat)

# --- フィールド抽出 ---
MODEL=$(echo "$input"     | jq -r '.model.display_name')
NAME=$(echo "$input"      | jq -r '.session_name // "unnamed"')
DIR=$(echo "$input"       | jq -r '.workspace.current_dir')
CWD=$(echo "$input"       | jq -r '.cwd')
PCT=$(echo "$input"       | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
COST=$(echo "$input"      | jq -r '.cost.total_cost_usd // 0')
FIVE=$(echo "$input"      | jq -r '.rate_limits.five_hour.used_percentage // empty')
WEEK=$(echo "$input"      | jq -r '.rate_limits.seven_day.used_percentage // empty')
RESET_5H=$(echo "$input"  | jq -r '.rate_limits.five_hour.resets_at // empty')

# --- 色 ---
RED=$'\033[31m'
YELLOW=$'\033[33m'
GREEN=$'\033[32m'
CYAN=$'\033[36m'
DIM=$'\033[2m'
RESET=$'\033[0m'

# --- 1行目: 🏷️ session | 🌿 branch | 📁 dir ---
BRANCH=$(git -C "$CWD" --no-optional-locks branch --show-current 2>/dev/null)
LINE1="🏷️  ${CYAN}${NAME}${RESET}"
[ -n "$BRANCH" ] && LINE1="$LINE1 ${DIM}|${RESET} 🌿 ${BRANCH}"
LINE1="$LINE1 ${DIM}|${RESET} 📁 ${DIR##*/}"

# --- 2行目: コンテキストバー(70%黄/90%赤) ---
if   [ "$PCT" -ge 90 ]; then BAR_COL="$RED"
elif [ "$PCT" -ge 70 ]; then BAR_COL="$YELLOW"
else                         BAR_COL="$GREEN"
fi
FILLED=$((PCT / 10))
EMPTY=$((10 - FILLED))
printf -v F "%${FILLED}s"
printf -v E "%${EMPTY}s"
BAR="${F// /█}${E// /░}"

# --- コスト ---
COST_FMT=$(printf '$%.2f' "$COST")

# --- レートリミット(Pro/Maxのみ。APIレスポンス前は欠落) ---
RL=""
if [ -n "$FIVE" ]; then
    FIVE_INT=$(printf '%.0f' "$FIVE")
    if [ -n "$RESET_5H" ]; then
        NOW=$(date +%s)
        MINS_LEFT=$(( (RESET_5H - NOW) / 60 ))
        RL="5h:${FIVE_INT}% (${MINS_LEFT}m)"
    else
        RL="5h:${FIVE_INT}%"
    fi
fi
if [ -n "$WEEK" ]; then
    WEEK_INT=$(printf '%.0f' "$WEEK")
    [ -n "$RL" ] && RL="$RL ${DIM}|${RESET} 7d:${WEEK_INT}%" || RL="7d:${WEEK_INT}%"
fi

LINE2="[${MODEL}] ${BAR_COL}${BAR}${RESET} ${PCT}% ${DIM}|${RESET} 💰${COST_FMT}"
[ -n "$RL" ] && LINE2="$LINE2 ${DIM}|${RESET} $RL"

# --- 3行目: 未レビュー許可要求 (件数 > 0 のときのみ) ---
PERM_LOG="$HOME/.claude/logs/permission-requests.jsonl"
LINE3=""
if [ -s "$PERM_LOG" ]; then
    PENDING=$(wc -l < "$PERM_LOG" 2>/dev/null | tr -d '[:space:]')
    # 想定外出力 (空 / 非数値) で `-gt` 評価が文法エラーで死ぬのを防ぐ。
    if [[ "$PENDING" =~ ^[0-9]+$ ]] && [ "$PENDING" -gt 0 ]; then
        if   [ "$PENDING" -ge 10 ]; then PCOL="$RED"
        elif [ "$PENDING" -ge 5 ];  then PCOL="$YELLOW"
        else                             PCOL="$DIM"
        fi
        LINE3="${PCOL}👁  pending review: ${PENDING}${RESET} ${DIM}(/review-permissions)${RESET}"
    fi
fi

# --- 出力 ---
echo "$LINE1"
echo "$LINE2"
if [ -n "$LINE3" ]; then
    echo "$LINE3"
fi
