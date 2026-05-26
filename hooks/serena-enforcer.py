#!/usr/bin/env python3
"""
Pre-Tool-Use hook for Bash that blocks code-discovery commands which
should be done via Serena's symbolic tools (mcp__serena__*) instead.

Reads tool input from stdin (JSON) and:
- Returns exit 0 (allow) when the command does not look like code discovery.
- Returns exit 2 (block) with stderr message naming the right Serena tool
  when the command pattern matches code discovery on code paths/files.

Triggered by Claude Code's PreToolUse hook with matcher="Bash".

Patterns are intentionally narrow: we only flag commands that operate on
code (paths under app/, src/, tests/, database/, routes/, lib/, config/,
bootstrap/ or files with code extensions). Non-code targets (logs, JSON,
YAML, markdown, etc.) are not blocked.

Bypass: append `# via:bash-discovery: <reason>` to the command if you
have a justified reason to use bash for discovery anyway (e.g., a quick
sanity check that serena cannot do, or running tests via grep on test
names). The bypass REQUIRES a non-empty reason after the colon so it
is a conscious, documented choice rather than a habit. A bare
`# via:bash-discovery` (no colon or empty reason) does not bypass.
"""

import json
import re
import sys


CODE_PATH_PATTERN = (
    r"(?:\bapp/|\bsrc/|\btests?/|\bdatabase/|\broutes/|\blib/|\bconfig/|\bbootstrap/)"
)
CODE_EXT_PATTERN = (
    r"\.(?:php|ts|tsx|js|jsx|py|rb|go|java|kt|rs|cpp|cc|c|h|hpp|cs|swift|scala|vue)\b"
)
BLADE_EXT_PATTERN = r"\.blade\.php\b"


# Each rule: (compiled regex, reason, tool_label)
# tool_label は BYPASS_WARNINGS と結合して bypass 多用警告に使う。
# cat と head/tail/wc/less/more は同根 (read-only コード閲覧) だが、cat だけ
# bypass で Read tool 強推奨警告を出すため別ラベルに分けている。
RULES = [
    (
        re.compile(
            r"\bgrep\b[^|;&]*?(?:" + CODE_PATH_PATTERN + r"|"
            + CODE_EXT_PATTERN + r"|" + BLADE_EXT_PATTERN + r")"
        ),
        "コードを対象にした grep は禁止。Serena の "
        "mcp__serena__search_for_pattern / mcp__serena__find_symbol を使う。",
        "grep",
    ),
    (
        re.compile(
            r"\bfind\b[^|;&]*?(?:" + CODE_PATH_PATTERN + r"|-name\s+['\"][^'\"]*?(?:"
            + CODE_EXT_PATTERN + r"|" + BLADE_EXT_PATTERN + r"))"
        ),
        "コードを対象にした find は禁止。Serena の "
        "mcp__serena__find_file / mcp__serena__find_symbol を使う。",
        "find",
    ),
    (
        re.compile(
            r"\bcat\b[^|;&]*?(?:"
            + CODE_EXT_PATTERN + r"|" + BLADE_EXT_PATTERN + r")"
        ),
        "コードファイルの cat は禁止。Read tool または Serena の "
        "mcp__serena__get_symbols_overview / mcp__serena__find_symbol(include_body=true) を使う。",
        "cat",
    ),
    (
        re.compile(
            r"\b(?:head|tail|wc|less|more)\b[^|;&]*?(?:"
            + CODE_EXT_PATTERN + r"|" + BLADE_EXT_PATTERN + r")"
        ),
        "コードファイルの head/tail/wc/less/more は禁止。Serena の "
        "mcp__serena__get_symbols_overview / mcp__serena__find_symbol(include_body=true) を使う。",
        "read-family",
    ),
    (
        re.compile(
            r"\bls\b[^|;&]*?-[a-zA-Z]*R[a-zA-Z]*\b[^|;&]*?(?:" + CODE_PATH_PATTERN + r")"
        ),
        "コード配下の再帰 ls は禁止。Serena の "
        "mcp__serena__list_dir / mcp__serena__find_file を使う。",
        "ls-R",
    ),
]


# tool_label 別の bypass 多用警告。
# bypass マッチ時 (= block しない経路) に該当ラベルの警告を stderr に出すことで、
# 真に必要な bypass (例: find -path / ls / git ls-tree) は妨げず、serena で
# 代替可能な tool (grep / cat) の習慣的多用を抑制する。
# 警告は出すが block はしない (= bypass の意図は尊重)。
BYPASS_WARNINGS = {
    "grep": (
        "[serena-enforcer] WARN: grep の bash-discovery bypass は serena 代替推奨。"
        "mcp__serena__search_for_pattern (パターン検索) / "
        "mcp__serena__find_symbol (シンボル定義) を検討してください。"
    ),
    "cat": (
        "[serena-enforcer] WARN: cat の bash-discovery bypass は Read tool 代替推奨。"
        "既知パスは Read tool の方が安全 (line range / offset 制御 / 大ファイル truncation)。"
    ),
    # find / read-family (head/tail/wc/less/more) / ls-R は WARN なし (現状維持)。
    # find はパスベース検索で serena 代替が薄く、ls-R / read-family は頻度低く
    # 観察上も多用傾向が見られなかったため。
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        print(f"[serena-enforcer] failed to parse payload: {e}", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name") or payload.get("toolName")
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}

    if tool_name != "Bash":
        return 0

    command = tool_input.get("command", "") or ""
    if not isinstance(command, str):
        return 0

    # まず RULES に対してマッチ判定 (どの tool 系のコード探索コマンドか特定)。
    # マッチしなければ何もせず exit 0 (= block 対象外コマンドはそのまま通す)。
    matched_reason = None
    matched_tool_label = None
    for pattern, reason, tool_label in RULES:
        if pattern.search(command):
            matched_reason = reason
            matched_tool_label = tool_label
            break

    if matched_reason is None:
        return 0

    # Bypass requires a non-empty reason after the colon:
    #   `# via:bash-discovery: <reason>`
    # A bare `# via:bash-discovery` (no colon or empty/whitespace-only reason)
    # is not enough — this makes the bypass a deliberate, documented choice.
    if re.search(r"#\s*via:bash-discovery\s*:\s*\S+", command):
        # bypass あり → block しないが、tool_label 別の警告があれば出す
        # (grep / cat の習慣的多用を stderr 痕跡で抑制)。
        warning = BYPASS_WARNINGS.get(matched_tool_label)
        if warning:
            print(warning, file=sys.stderr)
        return 0

    # bypass なし → 既存の block 挙動
    print(
        "BLOCKED by serena-enforcer hook.\n"
        f"reason: {matched_reason}\n"
        "Use Serena's symbolic tools (mcp__serena__*) instead.\n"
        "Bypass (only with conscious justification): append "
        "`# via:bash-discovery: <reason>` to the command.\n"
        "The reason after the colon must be non-empty so each bypass "
        "is a documented choice, not a habit.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
