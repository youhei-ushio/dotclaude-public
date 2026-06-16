#!/bin/bash
# Regression tests for hooks/destructive-guard.py
#
# 実行: bash tests/test_destructive_guard.sh
#
# destructive-guard は stateless (stdin の JSON コマンド文字列のみ判定し、
# ファイルには触れない) なので HOME 隔離は不要。リポ実体の hook を直接叩く。
# exit 2 = block / exit 0 = allow を検証する。
#
# 各テストは `&&` 連結 (bash -e が if 配下で効かない POSIX 仕様への対策)。

HOOK="$(cd "$(dirname "$0")/.." && pwd)/hooks/destructive-guard.py"
FAIL=0

run() {
    local name="$1"; shift
    if "$@"; then
        echo "[PASS] $name"
    else
        echo "[FAIL] $name"
        FAIL=$((FAIL + 1))
    fi
}

# Bash payload を生成して hook に流し、exit code を返す
_rc() {
    local cmd="$1"
    python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$cmd" \
        | python3 "$HOOK" >/dev/null 2>&1
    echo $?
}

blocked() { [ "$(_rc "$1")" = "2" ]; }
allowed() { [ "$(_rc "$1")" = "0" ]; }

# ---------- block されるべき (exit 2) ----------
run "B1: find -delete を block"            blocked "find . -name '*.log' -delete"
run "B2: find -exec rm を block"           blocked "find /tmp/x -type f -exec rm {} \\;"
run "B3: git clean -fd を block"           blocked "git clean -fd"
run "B4: git push --force を block"        blocked "git push --force origin main"
run "B5: git push -f を block"             blocked "git push -f origin main"
run "B6: ~/.claude への上書き > を block"  blocked "cat foo.txt > ~/.claude/settings.json"
run "B7: /etc への上書き > を block"        blocked "echo x > /etc/hosts"

# ---------- allow されるべき (exit 0) ----------
run "A1: find (削除なし) は allow"          allowed "find . -name '*.log'"
run "A2: git clean -n (dry-run) は allow"  allowed "git clean -n"
run "A3: git push --force-with-lease は allow" allowed "git push --force-with-lease origin main"
run "A4: git push (force なし) は allow"    allowed "git push origin main"
run "A5: >> 追記は allow"                   allowed "cat a b >> combined.txt"
run "A6: 2>/dev/null (fd redirect) は allow" allowed "grep -r foo . 2>/dev/null"
run "A7: 相対パスへの > 上書きは allow"      allowed "cat foo > out.txt"
run "A8: /tmp への > は allow"              allowed "echo x > /tmp/scratch.txt"
run "A9: git commit は allow"               allowed "git commit -m 'x'"
run "A10: 通常の grep は allow"             allowed "grep -rn foo src/"

# ---------- レビュー で発見した回避経路の回帰テスト ----------
run "B8: 2> で ~/.claude 上書きを block"        blocked "grep foo x 2> ~/.claude/settings.json"
run "B9: &> で /etc 上書きを block"             blocked "echo x &> /etc/hosts"
run "B10: クォート付き \$HOME/.claude 上書きを block" \
    blocked 'cat x > "$HOME/.claude/settings.json"'
run "B11: git push -fd (束ね) を block"          blocked "git push -fd origin main"
run "B12: git push -uf (束ね) を block"          blocked "git push -uf origin main"
run "B13: git -C <repo> push --force を block"   blocked "git -C /tmp/r push --force"
run "B14: find | xargs rm を block"              blocked "find . -type f | xargs rm -f"
run "B15: git push origin +main (refspec) を block" blocked "git push origin +main"
run "B16: tee で ~/.claude 上書きを block"       blocked "cat x | tee ~/.claude/settings.json"
run "B17: ~/.ssh への上書き > を block"          blocked "echo k > ~/.ssh/authorized_keys"

run "A11: git push --force-if-includes は allow" allowed "git push --force-if-includes origin main"
run "A12: git push -v (force なし) は allow"     allowed "git push -v origin main"
run "A13: find | xargs ls (rm でない) は allow"  allowed "find . -type f | xargs ls -l"
run "A14: git push origin main:feature (+なし) は allow" allowed "git push origin main:feature"

# ---------- 2 巡目レビュー で発見した回避経路 / 誤 block の回帰 ----------
run "B18: >| (noclobber 上書き) で /etc を block"   blocked "echo x >| /etc/hosts"
run "B19: tee 複数宛先の 2 番目 (~/.claude) を block" blocked "cat x | tee /tmp/ok ~/.claude/settings.json"
run "B20: > ~/.claude (末尾スラッシュ無し) を block"  blocked "echo x > ~/.claude"
run "B21: find | xargs unlink を block"             blocked "find . -type f | xargs unlink"

run "A15: lease 付き +refspec (--force-with-lease +main) は allow" \
    allowed "git push --force-with-lease origin +main"
run "A16: git commit -m に push --force を含んでも allow" \
    allowed "git commit -m 'remember to push --force later'"
run "A17: git stash push (subcommand でない) は allow" allowed "git stash push -m wip"
run "A18: git -c x=y push (force なし) は allow"     allowed "git -c user.name=x push origin main"
run "A19: tee -a (追記) は allow"                    allowed "cat x | tee -a build.log"

# ---------- 3 巡目レビュー: broad git allow の非復旧形をガード ----------
run "B22: git push --delete を block"            blocked "git push --delete origin feature-x"
run "B23: git push -d を block"                  blocked "git push -d origin feature-x"
run "B24: git push origin :branch (削除) を block" blocked "git push origin :feature-x"
run "B25: git stash clear を block"              blocked "git stash clear"
run "B26: git checkout -f を block"              blocked "git checkout -f other-branch"
run "B27: git checkout -- <path> を block"       blocked "git checkout -- src/app.py"
run "B28: git checkout . を block"               blocked "git checkout ."
run "B29: git restore <path> を block"           blocked "git restore src/app.py"
run "B30: git switch --discard-changes を block" blocked "git switch --discard-changes other"

run "A20: git push origin main:feature (通常 refspec) は allow" \
    allowed "git push origin main:feature"
run "A21: git checkout <branch> (通常切替) は allow" allowed "git checkout develop"
run "A22: git checkout -b <new> (作成) は allow"  allowed "git checkout -b feature/new"
run "A23: git switch <branch> は allow"           allowed "git switch main"
run "A24: git restore --staged <path> (unstage) は allow" allowed "git restore --staged src/app.py"
run "A25: git stash drop は allow"                allowed "git stash drop"
run "A26: git stash push は allow"                allowed "git stash push -m wip"

# ---------- 4 巡目レビュー: mirror/prune ガード + stash clear 誤 block 修正 ----------
run "B31: git push --mirror を block"            blocked "git push --mirror origin"
run "B32: git push --prune を block"             blocked "git push --prune origin"
run "A27: git stash push -m 'clear...' は allow"  allowed "git stash push -m 'clear cache before rebase'"
run "A28: git stash push src/clear.py は allow"   allowed "git stash push src/clear.py"
run "A29: git fetch --prune (push でない) は allow" allowed "git fetch --prune origin"

# ---------- 改行 segment 分割 (多行コマンドの false positive 修正) ----------
run "B33: 多行で行末の git push --force は block 維持" \
    blocked $'git add .\ngit commit -m x\ngit push --force origin main'
run "A30: 多行で別行の rm -f を push の force と誤認しない (allow)" \
    allowed $'git add .\nrm -f /tmp/x\ngit push origin main'
run "A31: 多行で別行の rm -rf を push の force と誤認しない (allow)" \
    allowed $'echo done\ngit push origin main\nrm -rf /tmp/build'
run "B34: シェル行継続の git push \\<改行>--force は block 維持 (継続畳み込み)" \
    blocked $'git push \\\n--force origin main'

# ---------- bypass ----------
run "BY1: # via:destructive-ok: 理由付きは allow" \
    allowed "find . -delete # via:destructive-ok: clean test artifacts"
run "BY2: bypass の理由が空なら block 維持" \
    blocked "find . -delete # via:destructive-ok:"

# ---------- 非 Bash tool は対象外 (allow) ----------
non_bash_allowed() {
    echo '{"tool_name":"Read","tool_input":{"file_path":"/etc/hosts"}}' \
        | python3 "$HOOK" >/dev/null 2>&1
    [ "$?" = "0" ]
}
run "N1: 非 Bash tool (Read) は対象外で allow" non_bash_allowed

if [ "$FAIL" -gt 0 ]; then
    echo "=== $FAIL test(s) FAILED ==="
    exit 1
fi
echo "=== ALL TESTS PASSED ==="
