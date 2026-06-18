#!/usr/bin/env python3
"""
destructive-guard.py

Claude Code PreToolUse (matcher: Bash) hook。

allowlist を read-only 探索動詞 (grep/find/cat/ls/...) や git/gh へ広く広げた
ことに伴い、**broad allow で自動承認
されうる「git でも復旧できない / 高被害」なコマンド形だけ** を block する二重防御。
allow は friction を無くし、危険形はこの hook が止める、という役割分担
(serena-enforcer が「コード探索 → serena 誘導」を担うのと同じ二重防御パターン)。

block 対象 (いずれも exit 2 で拒否):
- `find ... -delete`                         : ファイル一括削除 (復旧不可)
- `find ... -exec/-execdir ... rm ...`       : find 経由の rm (復旧不可)
- `... | xargs ... rm ...`                   : xargs 経由の一括 rm (find/grep allow から到達)
- `git clean -f...`                          : untracked/ignored 削除 (git でも復旧不可)
- `git ... push ... --force` / `-f`束ね / `+refspec` : リモート履歴の巻き戻し
  (ただし `--force-with-lease` / `--force-if-includes` は安全として許可)
- `git ... push --delete` / `-d` / `origin :branch` : リモートブランチ削除
  (unmerged push-only ブランチは ref が消失)
- `git ... checkout -f` / `checkout -- <path>` / `checkout .` / `git switch -f`
  / `git restore <path>` (--staged のみは除く) : 未コミット変更の破棄
  (reflog/remote に残らず復旧不可。通常のブランチ切替は許可)
- `git ... stash clear`                      : 全 stash 削除 (復旧困難)
- overwrite redirect (`>` `&>` `N>`、ただし `>>` 追記は除く) や `tee`、または `rm` で
  `~/.claude/**` `~/.ssh/**` および `/etc /usr /bin /sbin /boot /sys /lib` を
  破壊するもの : 稼働中ライブ設定 / 鍵 / システムファイルの破壊
  (素の `rm -rf ~/.claude` も含む。redirect/tee だけでなく rm 直撃も止める。
  さらに home ディレクトリ自体 `rm -rf ~` / `$HOME` / 絶対 home path も .claude/.ssh ごと
  巻き込むため止める)

block しない (= 通す):
- `>>` 追記、`> /tmp/...` / `> /var/tmp/...` / `> /dev/null`、相対パスやリポ配下への上書き
  (git 管理下なら復旧可能)
- `git push --force-with-lease` / `--force-if-includes`、`git clean -n` (dry-run)
- `git -C <repo> ...` のグローバルオプション前置形も検知する (segment 単位判定)

allowlist 外の mutator (`cp` / `mv` / `dd` / `truncate` 等) は本 hook では個別検知せず、
**allowlist に無い = 都度確認** に委ねる。`tee` のみ redirect 相当として検知。

**静的判定の原理的限界 (block しない = 検知不能。防御範囲の誤認を防ぐため明記)**:
- 変数展開・コマンド置換・eval 経由で組み立てる動的コマンド (`F=--force; git push $F` /
  `rm $(find . -name x)` / `eval "..."`)
- プロセス置換 (`tee >(...)`) や相対パス依存 (`cd ~/.claude && rm settings.json`) で
  cwd に依存して保護対象に到達するもの
- `cp` / `mv` / `dd of=` / `truncate` 等での保護対象上書き (allowlist 外 = 都度確認に委ねる)
- ブレース展開 (`rm ~/{.claude,other}`) 等のシェル展開を経て保護対象に至るもの
  (展開前トークンで判定するため未検知。`rm ~/.claude/{a,b}` のように prefix が保護対象なら検知)
これらは静的 regex では原理的に検知できない。allow された道具で意図的回避が可能な点は
broad-allow 運用の前提 (コマンドは Claude 自身が組み、敵対的回避は想定外) で許容する。

bypass: コマンド末尾の **本物のシェルコメント** `# via:destructive-ok: <理由>` (理由必須)。
クォート内データに同テキストを紛れ込ませても bypass にはならない (クォート除去後に判定)。

例外は飲み込み、hook 失敗で Claude Code を止めない (exit 0)。
"""

from __future__ import annotations

import json
import os
import re
import sys

# overwrite で保護する絶対パス prefix。/tmp /var/tmp /dev/null は除外。
PROTECTED_ABS_PREFIXES = (
    "/etc/", "/usr/", "/bin/", "/sbin/", "/boot/", "/sys/", "/lib/",
)


def _protected_home_dirs() -> tuple[str, ...]:
    home = os.path.expanduser("~")
    # 稼働中ライブ設定 (~/.claude、symlink 配布) と SSH 鍵を保護
    return (home + "/.claude/", home + "/.ssh/")


def _is_protected_target(raw_target: str) -> bool:
    """リダイレクト / tee / rm の宛先文字列が保護対象なら True。
    クォートを (外側だけでなく内部も) 除去し、~ / $HOME / ${HOME} を展開してから判定する。
    末尾スラッシュ無し (ディレクトリ実体や symlink ファイル) も保護対象に含める。
    """
    # 内部クォートも除去する: `"$HOME"/.claude` のように $HOME 部分だけをクォートする
    # 記法でも展開・判定できるようにするため (外側 strip だけだと `$HOME"/...` が残り
    # `startswith("$HOME/")` が外れる)。パスに literal な引用符が含まれることはまず無い。
    target = raw_target.strip().replace('"', "").replace("'", "")
    if not target:
        return False
    home = os.path.expanduser("~")
    expanded = target
    if target in ("~", "$HOME", "${HOME}"):
        expanded = home
    elif target.startswith("~/"):
        expanded = home + target[1:]
    elif target.startswith("$HOME/"):
        expanded = home + target[len("$HOME"):]
    elif target.startswith("${HOME}/"):
        expanded = home + target[len("${HOME}"):]
    # 連続スラッシュを 1 個に畳む (`//etc/passwd` のような冗長表記での検知漏れ防止)
    expanded = re.sub(r"/{2,}", "/", expanded)
    # 安全な書き込み先は除外
    if expanded.startswith(("/tmp/", "/var/tmp/")) or expanded == "/dev/null":
        return False
    # home ディレクトリ自体 (`~` / `$HOME` / `${HOME}` / 絶対 home path) は配下の
    # .claude/.ssh ごと巻き込むため保護対象 (主に `rm -rf ~` 対策。redirect では dir 宛は
    # 通常起きないので実害は rm 経路)。
    if expanded.rstrip("/") == home:
        return True
    protected = _protected_home_dirs() + PROTECTED_ABS_PREFIXES
    for base in protected:
        # prefix 一致 (配下ファイル) または実体そのもの (末尾スラッシュ無し) を保護
        if expanded.startswith(base) or expanded == base.rstrip("/"):
            return True
    return False


def _check_overwrite_targets(cmd: str) -> str | None:
    """overwrite redirect (`>` `&>` `N>` `>|`、`>>` 追記は除く) と `tee` (追記
    `-a` でない場合) の宛先が保護対象なら理由を返す。"""
    # `>>` (追記) / `&>>` / `N>>` は除外。`>` `&>` `N>` `>|` (truncate) のみ拾う。
    # `>|` は noclobber を上書きする truncate 演算子なので含める。
    for m in re.finditer(r"(?<!>)(?:&|\d*)>(?!>)\|?\s*([^\s;|&>]+)", cmd):
        if _is_protected_target(m.group(1)):
            return f"保護対象 ({m.group(1)}) への上書きリダイレクトはライブ設定/鍵/システムを破壊しうる"
    # tee: -a/--append (追記、`>>` と同等に許可) でない場合のみ、全宛先引数を検査。
    # 引数取得は segment 境界 (`;` `|` `&`) で止める。
    for m in re.finditer(r"\btee\b((?:\s+[^\s;|&]+)*)", cmd):
        args = m.group(1).split()
        if any(a in ("-a", "--append") for a in args):
            continue
        for a in args:
            if a.startswith("-"):
                continue
            if _is_protected_target(a):
                return f"保護対象 ({a}) への tee 書き込みはライブ設定/鍵/システムを破壊しうる"
    return None


def _split_segments(cmd: str) -> list[str]:
    """`|` `;` `&&` `||` `&` および **改行** で粗く分割。git push/clean のオプション
    前置形を segment 単位で判定するため (`git -C <repo> push --force` 等を取りこぼさない)。
    改行を含めるのは、多行コマンドで `git push` (ある行) と別行の `-f`/`+` 等が同一 segment
    扱いになり force push と誤認される false positive を防ぐため (例:
    `git add .<改行>rm -f x<改行>git push` の `rm -f` を push の force と誤認しない)。

    ただし分割前に **シェル行継続 (`\\` + 改行) を空白に畳む**。これをしないと
    `git push \\<改行>--force` のような 1 コマンドの行継続が `git push \\` と `--force` に
    分断され、force-push を検知し損ねる (改行 split で新たに生じる false negative の防止)。"""
    cmd = re.sub(r"\\\n", " ", cmd)
    return re.split(r"[;&|\n]+", cmd)


# git の subcommand を厳密に判定する。`git` の後にグローバルオプション
# (`-C <path>` / `-c x=y` / `--git-dir=...` / `--no-pager` 等) が任意個並び、
# その後に当該 subcommand が来る形のみ True。これにより `git stash push` /
# `git commit -m "...push..."` / `git config alias.x 'push -f'` のような
# 「push/clean が subcommand でない」ケースを force 判定から除外する
# (false positive 対策)。`git -C <repo> push` のような前置形は引き続き検知。
def _git_subcommand(seg: str, sub: str) -> bool:
    """seg の `git` の subcommand が sub なら True。`git` の後のグローバルオプション
    (`-C <path>` / `-c <x=y>` は次トークンを値として取る / `--opt[=val]` / `-f` 等の
    短・長オプション) を読み飛ばし、最初の非オプション位置のトークンが sub かで判定する。

    正規表現の繰り返し+バックトラックを使わない **トークン走査** にしているのは:
    - 線形で ReDoS が起きない (`git --foo=bar ×多数 commit` のような末尾不一致入力でも
      破滅的バックトラッキングしない。以前の atomic group `(?>...)` 版が担っていた ReDoS 耐性を
      バックトラック不在で代替)。
    - atomic group / 所有量化子など Python 3.11+ 専用構文に依存せず **3.9+ で動く**
      (3.9/3.10 では `(?>...)` が re.error → except 飲み込みで git block が無言 fail-open する
      回帰を根絶)。
    クォート区間は単一トークン Q に潰してから走査するので、`git commit -m "...push..."` /
    `git config alias.x 'push -f'` / `git -C "/my repo" push` のような
    「push/clean が subcommand でない or 値に空白を含む」ケースも誤検知/取りこぼししない。"""
    toks = re.sub(r"'[^']*'|\"[^\"]*\"", "Q", seg).split()
    if "git" not in toks:
        return False
    i = toks.index("git") + 1
    while i < len(toks):
        t = toks[i]
        if t in ("-C", "-c"):
            i += 2  # 次トークンを値として消費 (`-C <path>` / `-c <x=y>`)
            continue
        if t.startswith("-"):
            i += 1  # `--opt[=val]` / `-f` 等は単一トークン
            continue
        break  # 非オプション = subcommand 位置
    return i < len(toks) and toks[i] == sub


def _has_lease(seg: str) -> bool:
    return bool(re.search(r"--force-with-lease|--force-if-includes", seg))


def _is_force_push(seg: str) -> bool:
    """segment が force push か。`git ... push` (subcommand) 内に true-force /
    `-f`束ね / (lease 無しの) `+refspec` のいずれかがあれば True。
    `--force-with-lease` / `--force-if-includes` は安全として除外。"""
    if not _git_subcommand(seg, "push"):
        return False
    # true --force のみ (--force-with-lease / --force-if-includes / --force= は除外)
    if re.search(r"--force(?![-\w=])", seg):
        return True
    # 単ダッシュの短縮オプション束に f を含む (-f / -fd / -uf 等)。-- は除外。
    if re.search(r"(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])", seg):
        return True
    # refspec force (先頭 + のレフスペック)。ただし lease 付きは安全なので除外。
    if not _has_lease(seg) and re.search(r"(?:^|\s)\+[\w./-]+", seg):
        return True
    return False


def _is_force_clean(seg: str) -> bool:
    """segment が `git ... clean` (subcommand) の force 形か。-n (dry-run) は安全。"""
    if not _git_subcommand(seg, "clean"):
        return False
    if re.search(r"--force\b", seg):
        return True
    # 単ダッシュ束に f を含む (-f / -fd / -xfd 等)
    if re.search(r"(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])", seg):
        return True
    return False


def _is_remote_delete(seg: str) -> bool:
    """`git ... push` でリモートブランチを削除する形か (`--delete` / `-d` 束ね /
    先頭コロン refspec `origin :branch`)。通常の `src:dst` refspec は削除でない。"""
    if not _git_subcommand(seg, "push"):
        return False
    if re.search(r"--delete\b", seg):
        return True
    if re.search(r"(?<![\w-])-[A-Za-z]*d[A-Za-z]*(?![\w-])", seg):
        return True
    # --mirror / --prune もリモート ref を非復旧で削除する (--delete と同クラス)。
    # `git fetch --prune` は push subcommand でないので上の gate で除外済み。
    if re.search(r"--(?:mirror|prune)\b", seg):
        return True
    # 先頭が空 (= 空白の直後がコロン) の refspec は削除。`main:feature` は非該当。
    if re.search(r"(?:^|\s):[\w./+-]+", seg):
        return True
    return False


def _is_worktree_discard(seg: str) -> bool:
    """未コミットの作業ツリー変更を破棄する形か (reflog/remote に残らず復旧不可)。
    通常のブランチ切替 (`git checkout <branch>` / `git switch <branch>` /
    `git checkout -b ...`) や `git restore --staged <path>` (unstage のみ) は安全。"""
    if _git_subcommand(seg, "checkout"):
        if re.search(r"--force\b|(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])", seg):
            return True
        # path-mode の破棄: `checkout -- <path>` / `checkout .`
        if re.search(r"\bcheckout\b[^|;&]*\s--(?:\s|$)", seg):
            return True
        if re.search(r"\bcheckout\b[^|;&]*\s\.(?:\s|$)", seg):
            return True
    if _git_subcommand(seg, "switch"):
        if re.search(r"--force\b|--discard-changes\b|(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])", seg):
            return True
    if _git_subcommand(seg, "restore"):
        # restore は --staged のみ (unstage) を除き作業ツリーを破棄する
        has_staged = re.search(r"--staged\b", seg)
        has_worktree = re.search(r"--worktree\b|(?<![\w-])-W\b", seg)
        if has_worktree or not has_staged:
            return True
    return False


def _is_stash_clear(seg: str) -> bool:
    """`git ... stash clear` (全 stash 削除、復旧困難)。drop/pop/list/push/save 等は安全。
    `clear` は stash の直後サブコマンド位置のみ一致 (`git stash push -m 'clear...'` や
    `git stash push src/clear.py` を誤 block しないため。push/clean と同じ堅牢化)。"""
    return bool(
        _git_subcommand(seg, "stash") and re.search(r"\bstash\s+clear\b", seg)
    )


def _is_protected_rm(seg: str) -> bool:
    r"""segment が保護対象 (~/.claude ~/.ssh /etc 等) を対象にした `rm` か。
    `rm` は broad-allow だが、保護対象への rm は redirect/tee と同じく止める
    (素の `rm -rf ~/.claude` が hook の謳う「ライブ設定/鍵の保護」を貫通する
    false-negative を塞ぐ)。`_is_protected_target` が /tmp 等を除外するので、
    通常の `rm /tmp/x` や `rm docs/temp/x` は false-positive にならない。
    誤 block を避けるため: `rm` が segment の **動詞位置** (先頭、前置として `VAR=val` 代入と
    単純 wrapper (`sudo`/`command`/`env`/`time`/`nice`/`exec`/`builtin`/`doas`) を読み飛ばした
    位置、先頭 `\`、絶対パス `/bin/rm`) のときだけ対象にし、`git commit -m 'rm ~/.claude'` や
    `echo rm ~/.claude`・`sudo grep -r rm /etc` のようにデータ/引数/別コマンドとして現れる
    `rm` を誤検知しない。各引数は `_is_protected_target` (クォート除去+展開) で判定。
    **静的限界 (対象外)**: `sudo -u root rm` / `nice -n 10 rm` のように wrapper が
    **オプションを伴う**形は静的に安全判定できない (`-u root` の `root` がオプション引数か
    コマンドか判別不能。lazy 化すると `sudo grep rm /etc` 等を誤 block する) ため対象外。
    第一層の許可プロンプトが `sudo`/`rm` を別途止める前提で許容する。
    処理順: (1) クォート区間を同長プレースホルダで潰す (offset 保存)。(2) その潰した文字列上で
    行頭/空白直後の `#` 以降を末尾コメントとして除去 (元文字列も同 offset で切る)。クォートを
    先に無害化することで `rm 'a#b' ~/.claude` のようにクォート内 `#` で rm/パスが消える ordering
    バグを防ぐ。(3) 潰した文字列で rm 動詞位置を判定し、引数は**元の文字列**から走査する
    (`"$HOME"/.ssh` 等の部分クォート保護パスの検知を維持)。"""
    # (1) クォート区間を同長プレースホルダで潰す (offset 保存)
    blanked = re.sub(r"'[^']*'|\"[^\"]*\"", lambda mo: "Q" * len(mo.group(0)), seg)
    # (2) 行頭/空白直後の `#` 以降を末尾コメントとして除去 (blanked 上で位置特定、元 seg も同 offset で切る)
    mc = re.search(r"(?:^|\s)#", blanked)
    end = mc.start() if mc else len(seg)
    blanked, s = blanked[:end], seg[:end]
    # (3) 動詞位置の rm。単純 wrapper / VAR=val / 先頭 `\` / 絶対パスを読み飛ばす
    #     (オプション付き wrapper は上記「静的限界」のとおり対象外)。
    m = re.match(
        r"\s*(?:(?:[A-Za-z_]\w*=\S*|sudo|command|env|time|nice|exec|builtin|doas)\s+)*"
        r"\\?(?:/\S*/)?rm(?=\s|$)",
        blanked,
    )
    if not m:
        return False
    # 引数は元 s から (offset は同長 blanked と一致)。クォート付き保護パスを保持。
    for a in s[m.end():].split():
        if a.startswith("-"):
            continue
        if _is_protected_target(a):
            return True
    return False


def _danger_reason(cmd: str) -> str | None:
    # find ... -delete
    if re.search(r"\bfind\b[^|;&]*\s-delete\b", cmd):
        return "`find ... -delete` はファイル一括削除で復旧不可"
    # find ... -exec/-execdir ... rm
    if re.search(r"\bfind\b[^|;&]*-exec(?:dir)?\b[^|;&]*\brm\b", cmd):
        return "`find ... -exec rm` は find 経由の削除で復旧不可"
    # ... | xargs ... rm/unlink/shred (find/grep allow から到達する一括削除)
    if re.search(r"\bxargs\b[^|;&]*\b(?:rm|unlink|shred)\b", cmd):
        return "`xargs ... rm/unlink/shred` は一括削除で復旧不可"
    # git の非復旧形は segment 単位で判定 (オプション前置形も検知)
    for seg in _split_segments(cmd):
        if _is_force_push(seg):
            return "`git push --force`/`-f`/`+refspec` (非 --force-with-lease) はリモート履歴を巻き戻す"
        if _is_remote_delete(seg):
            return "`git push --delete`/`:branch` はリモートブランチ削除 (unmerged は ref が消える)"
        if _is_force_clean(seg):
            return "`git clean -f` は untracked/ignored 削除で git でも復旧不可"
        if _is_stash_clear(seg):
            return "`git stash clear` は全 stash 削除で復旧困難"
        if _is_worktree_discard(seg):
            return "`git checkout -f`/`restore <path>`/`checkout -- ` 等は未コミット変更を破棄 (reflog/remote に残らない)"
        if _is_protected_rm(seg):
            return "保護対象 (~/.claude ~/.ssh /etc 等) への `rm` はライブ設定/鍵/システムを破壊しうる"
    # overwrite redirect / tee で保護対象を上書き
    r = _check_overwrite_targets(cmd)
    if r is not None:
        return r
    return None


def main() -> int:
    try:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError, OSError):
            return 0
        if not isinstance(payload, dict):
            return 0
        if payload.get("tool_name") != "Bash":
            return 0
        ti = payload.get("tool_input") or {}
        cmd = ti.get("command", "") if isinstance(ti, dict) else ""
        if not isinstance(cmd, str) or not cmd.strip():
            return 0

        reason = _danger_reason(cmd)
        if reason is None:
            return 0

        # bypass: コマンド末尾の **本物のシェルコメント** `# via:destructive-ok: <非空の理由>`。
        # クォート文字列を先に除去してから探すことで、`echo '# via:destructive-ok: x' >
        # ~/.claude/...` のように **クォート内データに紛れ込ませた擬似コメント** での bypass を
        # 防ぐ。`#` は行頭または空白直後 (= 実際にコメントが始まる位置) のみ有効。
        # 二重引用符内は \" エスケープも 1 区間として食う (`"a\""` 等で残りが露出して
        # bypass が誤成立するのを防ぐ)。bypass 理由にクォート文字は含めないこと。
        stripped = re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", "", cmd)
        if re.search(r"(?:^|\s)#\s*via:destructive-ok\s*:\s*\S", stripped):
            return 0

        print(
            "BLOCKED by destructive-guard hook.\n"
            f"reason: {reason}\n"
            "broad allowlist 下でも『git でも復旧できない / 高被害』な形は止めています。\n"
            "意図的に実行する場合のみ、コマンド末尾に "
            "`# via:destructive-ok: <理由>` を付けてください (理由は非空必須)。",
            file=sys.stderr,
        )
        return 2
    except BaseException:
        # hook 失敗で Claude Code を止めない
        return 0


if __name__ == "__main__":
    sys.exit(main())
