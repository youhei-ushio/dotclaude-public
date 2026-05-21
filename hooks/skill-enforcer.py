#!/usr/bin/env python3
"""
Pre-Tool-Use hook for Bash that blocks commands which should be invoked
through a Skill instead.

Reads tool input from stdin (JSON) and:
- Returns exit 0 (allow) when the command does not match any known pattern.
- Returns exit 2 (block) with a stderr message naming the correct skill
  when the command matches a registered pattern.

Triggered by Claude Code's PreToolUse hook with matcher="Bash".

Patterns are intentionally narrow: only block the literal commands that
correspond to a known skill, so general bash usage is not affected.
"""

import json
import re
import sys


# Each rule: (compiled regex, skill name, reason)
RULES = [
    (
        re.compile(r"\bdrawio\b(?=[^|;&]*--export\b)"),
        "run-drawio-export",
        "drawio --export を直接呼ばないこと。~/.claude/hooks/run-drawio-export.sh 経由で実行する（Xvfb 起動と後始末をまとめてやる）。",
    ),
    (
        re.compile(r"\bgh\s+pr\s+create\b"),
        "create-pr",
        "gh pr create を直接呼ばないこと。/create-pr スキル経由で実行する。",
    ),
    # NOTE: md-to-pdf rule removed.
    # /pdf skill's instructions internally call `npx md-to-pdf`, so this rule
    # would block the skill's own execution. Detecting "md-to-pdf without
    # prior SVG embedding" is too fragile, so we rely on memory/skill discipline
    # for /pdf invocation. drawio and gh pr create are still enforced because
    # those commands have meaningful pre/post setup that the skill orchestrates.
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        # If we can't parse, do not block.
        print(f"[skill-enforcer] failed to parse payload: {e}", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name") or payload.get("toolName")
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}

    if tool_name != "Bash":
        return 0

    command = tool_input.get("command", "") or ""
    if not isinstance(command, str):
        return 0

    # Bypass: explicit acknowledgment that the call is part of a skill flow.
    # Add a comment like `# via:export-drawio` at the end of the bash command
    # to confirm you went through the Skill tool first. This forces a conscious
    # confirmation rather than silent rule-evasion: if you add this comment
    # without first invoking the Skill, that's a deliberate choice you've made.
    if re.search(r"#\s*via:[a-z0-9_-]+", command):
        return 0

    for pattern, skill, reason in RULES:
        if pattern.search(command):
            print(
                "BLOCKED by skill-enforcer hook.\n"
                f"reason: {reason}\n"
                f"use skill: /{skill}\n"
                "Stop and re-run via the Skill tool with the matching skill name.\n"
                f"Bypass (only after invoking the skill): append `# via:{skill}` to the command.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
