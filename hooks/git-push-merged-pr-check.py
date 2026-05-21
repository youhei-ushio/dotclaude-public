#!/usr/bin/env python3
"""
Pre-Tool-Use hook for Bash that blocks `git push` when the current branch
already has a MERGED PR.

Reads tool input from stdin (JSON) and:
- exit 0 (allow) when the command is not `git push`.
- exit 0 (allow) when the command explicitly targets a branch other than current.
- exit 0 (allow) when current branch is main / master.
- exit 0 (allow) when current branch has no merged PR.
- exit 2 (block) when the current branch already has a MERGED PR, with a
  stderr message naming the PR and suggesting branch alternatives.

Triggered by Claude Code's PreToolUse hook with matcher="Bash".

Bypass: append `# via:git-push-merged-pr-check` to the bash command after
explicit user confirmation that the push is intentional.
"""

import json
import re
import subprocess
import sys


PUSH_SEGMENT_PATTERN = re.compile(r"^\s*git\s+push\b")
SEGMENT_SPLIT_PATTERN = re.compile(r";|\&\&|\|\||\n|\|")
BYPASS_PATTERN = re.compile(r"#\s*via:git-push-merged-pr-check\b")
PROTECTED_BRANCHES = ("main", "master")
REMOTE_NAMES = ("origin", "upstream")
# Flags that take a following value as an argument. The value would otherwise
# be misread as a branch spec (e.g. `git push -o ci.skip origin main`).
VALUE_TAKING_FLAGS = ("-o", "--push-option", "--receive-pack", "--repo", "--exec")


def get_current_branch():
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def get_merged_prs(branch):
    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--head", branch,
                "--state", "merged",
                "--json", "number,title,url",
                "--limit", "1",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout or "[]")
    except Exception:
        return []


def is_git_push_command(command):
    """Return True if any segment of the command starts with `git push`.

    Splits the command on shell separators (`;`, `&&`, `||`, `|`, `\\n`) and
    checks the head of each segment. This avoids false positives like
    `echo "git push"` or `# git push` where the literal appears mid-line."""
    for segment in SEGMENT_SPLIT_PATTERN.split(command):
        if PUSH_SEGMENT_PATTERN.match(segment):
            return True
    return False


def explicit_target_branch(command):
    """Parse `git push` arguments to find an explicitly specified target branch.

    Returns None if push targets the implicit (current) branch."""
    tokens = re.findall(r"\S+", command)
    try:
        idx = tokens.index("push")
    except ValueError:
        return None

    args = tokens[idx + 1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in VALUE_TAKING_FLAGS:
            i += 2  # skip the flag AND its value
            continue
        if arg.startswith("-"):
            i += 1
            continue
        if arg in REMOTE_NAMES:
            i += 1
            continue
        # First non-flag, non-remote token is the branch spec.
        # refspec "local:remote" → take local side.
        return arg.split(":")[0]
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        print(f"[git-push-merged-pr-check] failed to parse payload: {e}", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name") or payload.get("toolName")
    if tool_name != "Bash":
        return 0

    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = tool_input.get("command", "") or ""
    if not isinstance(command, str) or not is_git_push_command(command):
        return 0

    if BYPASS_PATTERN.search(command):
        return 0

    current_branch = get_current_branch()
    if not current_branch or current_branch in PROTECTED_BRANCHES:
        return 0

    target = explicit_target_branch(command)
    if target and target != current_branch:
        return 0

    prs = get_merged_prs(current_branch)
    if not prs:
        return 0

    pr = prs[0]
    print(
        "BLOCKED by git-push-merged-pr-check hook.\n"
        f"reason: 現在ブランチ \"{current_branch}\" は MERGED 済みの PR #{pr['number']} ({pr['title']}) を持っています。\n"
        f"  URL: {pr['url']}\n"
        "このブランチへの追加 push は混乱の元になります。以下のいずれかを検討してください:\n"
        "  1. 新しいブランチを切る (例: git checkout -b feature/<次の作業名>)\n"
        "  2. 意図的な追加 push の場合はユーザーに確認したうえで実行する\n"
        "Bypass (only after user confirmation): append `# via:git-push-merged-pr-check` to the command.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
