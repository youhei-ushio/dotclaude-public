#!/usr/bin/env python3
"""
Pre-Tool-Use hook for Bash that blocks inline `COMPOSE_PROJECT_NAME=...`
prefixes on `sail` / `docker compose` commands.

Each parallel sets `env.COMPOSE_PROJECT_NAME` in
`.claude/settings.local.json`, so the variable is already in the Claude
Code session environment. Inline prefixes like:

    COMPOSE_PROJECT_NAME=myproject ./vendor/bin/sail artisan test

prevent `Bash(./vendor/bin/sail *)` permission rules from matching and
trigger an approval prompt every time. They are also redundant once
settings.local.json is in place.

Reads tool input from stdin (JSON) and:
- exit 0 (allow) when the command is not Bash, or when no sail / docker
  compose invocation is preceded by an inline COMPOSE_PROJECT_NAME=.
- exit 0 (allow) when the bypass marker is present.
- exit 2 (block) when an inline COMPOSE_PROJECT_NAME= prefix targets
  `./vendor/bin/sail`, `vendor/bin/sail`, `sail` (alone), or
  `docker compose`, with a stderr message naming the rewrite target.

Triggered by Claude Code's PreToolUse hook with matcher="Bash".

Bypass: append `# via:sail-env-inline: <reason>` to the bash command
after explicit user confirmation. The reason after the colon must be
non-empty so each bypass is a documented choice, not a habit.

Not blocked:
- `export COMPOSE_PROJECT_NAME=myproject` (intentional session-wide export)
- `./vendor/bin/sail ...` without an inline prefix (the desired form)
- Strings containing `COMPOSE_PROJECT_NAME=` inside quotes / comments
  (segment-head check, same approach as git-push-merged-pr-check.py)
"""

import json
import re
import sys


# Matches an inline VAR=VALUE prefix immediately followed (after optional
# additional VAR=VALUE pairs and whitespace) by a sail / docker-compose
# invocation. Anchored to a segment head via the segment splitter below,
# so `echo "COMPOSE_PROJECT_NAME=..."` and similar literals don't match.
INLINE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*"   # optional additional VAR=VALUE
    r"COMPOSE_PROJECT_NAME=\S+\s+"          # the offending inline assignment
    r"(?:[A-Z_][A-Z0-9_]*=\S+\s+)*"        # more env assignments after it
    r"(?:\./vendor/bin/sail|vendor/bin/sail|sail|docker\s+compose)\b"
)

# Allow `export COMPOSE_PROJECT_NAME=...` as an intentional session export
EXPORT_PATTERN = re.compile(r"^\s*export\s+COMPOSE_PROJECT_NAME=")

# Split on shell command separators to avoid matching quoted / commented
# literals (same idea as git-push-merged-pr-check.py).
SEGMENT_SPLIT_PATTERN = re.compile(r";|\&\&|\|\||\n|\|")

BYPASS_PATTERN = re.compile(r"#\s*via:sail-env-inline\s*:\s*\S+")


def has_blocking_inline(command):
    """Return True if any segment of the command is an inline
    `COMPOSE_PROJECT_NAME=... sail/docker-compose ...` invocation."""
    for segment in SEGMENT_SPLIT_PATTERN.split(command):
        if EXPORT_PATTERN.match(segment):
            continue
        if INLINE_PREFIX_PATTERN.match(segment):
            return True
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        print(f"[sail-env-inline-block] failed to parse payload: {e}", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name") or payload.get("toolName")
    if tool_name != "Bash":
        return 0

    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = tool_input.get("command", "") or ""
    if not isinstance(command, str):
        return 0

    if BYPASS_PATTERN.search(command):
        return 0

    if not has_blocking_inline(command):
        return 0

    print(
        "BLOCKED by sail-env-inline-block hook.\n"
        "reason: 各 parallel の .claude/settings.local.json で\n"
        "        env.COMPOSE_PROJECT_NAME が既に設定されているため、\n"
        "        `COMPOSE_PROJECT_NAME=myproject ./vendor/bin/sail ...` の\n"
        "        インライン指定は不要で、Bash(./vendor/bin/sail *) 等の\n"
        "        permission rule に毎回マッチせず許可確認が発生してしまう。\n"
        "\n"
        "書き換え方:\n"
        "  before: COMPOSE_PROJECT_NAME=myproject ./vendor/bin/sail <args>\n"
        "  after : ./vendor/bin/sail <args>\n"
        "\n"
        "Bypass (only with conscious justification): append\n"
        "`# via:sail-env-inline: <reason>` to the command.\n"
        "The reason after the colon must be non-empty so each bypass\n"
        "is a documented choice, not a habit.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
