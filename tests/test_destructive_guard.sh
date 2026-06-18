#!/bin/bash
# Regression tests for hooks/destructive-guard.py
#
# 実行: bash tests/test_destructive_guard.sh
#
# destructive-guard は stateless (stdin の JSON コマンド文字列のみ判定し、
# ファイルには触れない) なので HOME 隔離は不要。リポ実体の hook を直接叩く。
# exit 2 = block / exit 0 = allow を検証する。
#
# 各テストは `&&` 連結 (bash -e が if 配下で効かない POSIX 仕様への対策。
# test_awaiting_parallel.sh と同じ規約)。

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

# ReDoS 回帰: 時間内 (5s) に判定が終われば OK (timeout=124/137 は NG)。
# 長い `--k=v` 反復で壊滅的バックトラッキングしないことを保証する。
redos_ok() {
    local cmd="$1" rc
    timeout 5 sh -c '
        python3 -c "import json,sys; print(json.dumps({\"tool_name\":\"Bash\",\"tool_input\":{\"command\":sys.argv[1]}}))" "$1" \
            | python3 "$2"
    ' _ "$cmd" "$HOOK" >/dev/null 2>&1
    rc=$?
    [ "$rc" != "124" ] && [ "$rc" != "137" ]
}

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

# ---------- レビュー指摘の回帰 (保護パス rm / クォート git option / bypass 厳密化) ----------
# SF2: 素の rm で保護対象を破壊するのを block (find/xargs/redirect だけでなく rm 直撃も)
run "B35: rm -rf ~/.claude を block"             blocked "rm -rf ~/.claude"
run "B36: rm -rf \"\$HOME\"/.ssh を block"        blocked 'rm -rf "$HOME"/.ssh'
run "B37: rm -rf /etc/foo を block"              blocked "rm -rf /etc/foo"
run "B38: rm ~/.claude/settings.json (単一) を block" blocked "rm ~/.claude/settings.json"
# SF2 の false-positive 不在: 保護対象でない rm は通す
run "A32: rm -rf /tmp/x は allow"                allowed "rm -rf /tmp/x"
run "A33: rm docs/temp/x.md (相対) は allow"      allowed "rm docs/temp/x.md"
run "A34: rm -rf node_modules は allow"          allowed "rm -rf node_modules"
# SF1: クォート内に空白を含むグローバルオプション値があっても force push を block
run "B39: git -c core.pager=\"less -R\" push --force を block" \
    blocked 'git -c core.pager="less -R" push --force origin main'
# SF3: \$HOME 部分だけクォートする記法でも保護対象と判定して block
run "B40: echo > \"\$HOME\"/.claude/... (部分クォート) を block" \
    blocked 'echo x > "$HOME"/.claude/settings.json'
# NTH1: クォート内データに紛れ込ませた擬似コメントでは bypass しない (なお block)
run "B41: クォート内データの擬似 bypass は無効 (block 維持)" \
    blocked "echo '# via:destructive-ok: x' > ~/.claude/settings.json"
# NTH1: 末尾の本物のコメント bypass は有効 (保護パス rm を allow)
run "BY3: 保護パス rm + 末尾 bypass は allow" \
    allowed "rm -rf ~/.claude # via:destructive-ok: 意図的なクリア"

# ---------- セルフレビュー指摘の回帰 (ReDoS / rm 誤 block) ----------
# A-R1: 長い --k=v 反復の git (非 push) で ReDoS せず時間内に判定が終わる
# (反復数を多め=200 にして準線形劣化も検知しやすくする)
run "RD1: 長い --k=v 反復 git (非 push) が ReDoS しない" \
    redos_ok "$(python3 -c 'print("git " + "--foo=bar "*200 + "commit -m x")')"
# 2 巡目 R-1: -c/-C の引数全体をクォートした force push を取りこぼさない
run "B43: git -C \"/my repo\" push --force (空白パス) を block" \
    blocked 'git -C "/my repo" push --force'
run "B44: git -c \"alias.x=push --force\" push --force を block" \
    blocked 'git -c "alias.x=push --force" push --force'
# 2 巡目 R-2/R-1: 前置コマンド付き rm を取りこぼさない
run "B45: sudo rm -rf /etc/foo を block"          blocked "sudo rm -rf /etc/foo"
run "B46: command rm -rf ~/.claude を block"      blocked "command rm -rf ~/.claude"
run "B47: /bin/rm -rf ~/.ssh (絶対パス) を block" blocked "/bin/rm -rf ~/.ssh"
run "B48: \\rm -rf ~/.claude (バックスラッシュ) を block" blocked '\rm -rf ~/.claude'
run "B49: time rm -rf ~/.claude を block"         blocked "time rm -rf ~/.claude"
run "B50: env FOO=bar rm -rf ~/.claude を block"  blocked "env FOO=bar rm -rf ~/.claude"
# 前置形でも保護対象でなければ allow (false-positive 不在の対称確認)
run "A38: sudo rm -rf /tmp/x は allow"            allowed "sudo rm -rf /tmp/x"

# ---------- 単純 wrapper 前置の保護パス rm は block (オプション無し形) ----------
# (B45-B50 で sudo rm / command rm / /bin/rm / \rm / time rm / env FOO=bar rm を既に確認)
# wrapper が非 rm コマンドを実行 / クォート内 rm は誤 block しない (false-positive 不在)
run "A39: sudo git commit -m 'rm ~/.claude' (クォート内 rm) は allow" \
    allowed "sudo git commit -m 'remember to rm ~/.claude later'"
run "A40: sudo apt install foo (rm 無し) は allow"  allowed "sudo apt install foo"
run "A41: sudo grep -r rm /etc (非 rm コマンド) は allow" allowed "sudo grep -r rm /etc"
run "A42: sudo cat rm ~/.ssh/id_rsa (非 rm コマンド) は allow" allowed "sudo cat rm ~/.ssh/id_rsa"
# 順序修正の回帰: クォート内 `#` を含む引数があっても rm/保護パスが消えず block (B の ordering バグ)
run "B51: rm 'foo#bar' ~/.claude (クォート内# + 保護パス) を block" \
    blocked "rm 'foo#bar' ~/.claude"
# 静的限界 (現状 allow を pin): wrapper のオプション付き形は対象外。検知拡張/縮小を意図的に
run "L1: [静的限界] sudo -u root rm -rf ~/.claude は現状 allow" \
    allowed "sudo -u root rm -rf ~/.claude"
run "L2: [静的限界] nice -n 10 rm -rf /etc/foo は現状 allow" \
    allowed "nice -n 10 rm -rf /etc/foo"
# wrapper 前置の長い非 rm コマンドで ReDoS しない
run "RD2: sudo + 長い非 rm 引数で ReDoS しない" \
    redos_ok "$(python3 -c 'print("sudo " + "arg "*300 + "echo done")')"
# A-R2/B-R1/B-R2: rm が動詞位置でない / コメント内の保護パス言及は誤 block しない
run "A35: git commit -m 'rm ~/.claude/..' (クォート内) は allow" \
    allowed "git commit -m 'remember to rm ~/.claude/old later'"
run "A36: echo rm ~/.claude (rm が引数) は allow" allowed "echo rm ~/.claude"
run "A37: rm foo.txt # ~/.claude のバックアップ (コメント) は allow" \
    allowed "rm foo.txt # backup of ~/.claude"
# 動詞位置の保護パス rm は引き続き block (回帰の対称確認)
run "B42: && の後の rm ~/.claude (動詞位置) は block 維持" \
    blocked "echo start && rm -rf ~/.claude"

# ---------- 公開 PR #11 2 巡目レビュー: home 直下保護 / 冗長スラッシュ / rm 動詞境界 ----------
# SF (home 自体): ~ / $HOME / ${HOME} / 末尾スラッシュ は .claude/.ssh ごと巻き込むため block
run "B52: rm -rf ~ (home 直下) を block"          blocked "rm -rf ~"
run "B53: rm -rf \$HOME を block"                 blocked 'rm -rf $HOME'
run "B54: rm -rf \${HOME} を block"               blocked 'rm -rf ${HOME}'
run "B55: rm -rf ~/ (末尾スラッシュ) を block"     blocked "rm -rf ~/"
# Nice (冗長スラッシュ): // で /etc 検知漏れしない
run "B56: rm //etc/passwd (冗長スラッシュ) を block" blocked "rm //etc/passwd"
# home 配下の非保護サブディレクトリは home 自体保護で巻き込まない (false-positive 不在)
run "A43: rm -rf ~/projects (home 配下の非保護) は allow" allowed "rm -rf ~/projects"
# Nice (rm 動詞境界): rm.real は rm コマンドでないので誤 block しない
run "A44: rm.real ~/.claude (rm 動詞でない) は allow" allowed "rm.real ~/.claude"
# Must-fix の回帰: atomic group を外しても引用符付きグローバルオプションの force push を検知
# (本体は B39/B43/B44 で確認済み。本ケースは非アトミック化後も維持されることの再確認)
run "B57: git -c core.pager=\"less -R\" push -f (非アトミック後) を block" \
    blocked 'git -c core.pager="less -R" push -f origin main'

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
