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


# Each rule: (compiled regex, reason)
RULES = [
    (
        re.compile(
            r"\bgrep\b[^|;&]*?(?:" + CODE_PATH_PATTERN + r"|"
            + CODE_EXT_PATTERN + r"|" + BLADE_EXT_PATTERN + r")"
        ),
        "コードを対象にした grep は禁止。Serena の "
        "mcp__serena__search_for_pattern / mcp__serena__find_symbol を使う。",
    ),
    (
        re.compile(
            r"\bfind\b[^|;&]*?(?:" + CODE_PATH_PATTERN + r"|-name\s+['\"][^'\"]*?(?:"
            + CODE_EXT_PATTERN + r"|" + BLADE_EXT_PATTERN + r"))"
        ),
        "コードを対象にした find は禁止。Serena の "
        "mcp__serena__find_file / mcp__serena__find_symbol を使う。",
    ),
    (
        re.compile(
            r"\b(?:cat|head|tail|wc|less|more)\b[^|;&]*?(?:"
            + CODE_EXT_PATTERN + r"|" + BLADE_EXT_PATTERN + r")"
        ),
        "コードファイルの cat/head/tail/less は禁止。Serena の "
        "mcp__serena__get_symbols_overview / mcp__serena__find_symbol(include_body=true) を使う。",
    ),
    (
        re.compile(
            r"\bls\b[^|;&]*?-[a-zA-Z]*R[a-zA-Z]*\b[^|;&]*?(?:" + CODE_PATH_PATTERN + r")"
        ),
        "コード配下の再帰 ls は禁止。Serena の "
        "mcp__serena__list_dir / mcp__serena__find_file を使う。",
    ),
]


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

    # Bypass requires a non-empty reason after the colon:
    #   `# via:bash-discovery: <reason>`
    # A bare `# via:bash-discovery` (no colon or empty/whitespace-only reason)
    # is not enough — this makes the bypass a deliberate, documented choice.
    if re.search(r"#\s*via:bash-discovery\s*:\s*\S+", command):
        return 0

    for pattern, reason in RULES:
        if pattern.search(command):
            print(
                "BLOCKED by serena-enforcer hook.\n"
                f"reason: {reason}\n"
                "Use Serena's symbolic tools (mcp__serena__*) instead.\n"
                "Bypass (only with conscious justification): append "
                "`# via:bash-discovery: <reason>` to the command.\n"
                "The reason after the colon must be non-empty so each bypass "
                "is a documented choice, not a habit.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
