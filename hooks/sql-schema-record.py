#!/usr/bin/env python3
"""
PostToolUse hook for Bash that detects schema-inspection queries and
records which tables have been dumped in this working session.

Pairs with `sql-schema-check.py` (PreToolUse on Write):
- This hook UPDATES the state file when schema queries are observed.
- The other hook READS the state file to validate `.sql` files being written.

State file: /tmp/claude-sql-schemas-<sha1(cwd)[:8]>.json

Detection patterns (any of these in the bash command):
- `INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'X'`
- `INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = "X"`
- `INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME IN ('A','B')`
- `SHOW CREATE TABLE X`
- `DESCRIBE X` / `DESC X`
- Loops with `$tables = [...]` followed by INFORMATION_SCHEMA query

Returns exit 0 always (never blocks). PostToolUse, so blocking would be
pointless. Side effect: appends discovered tables to the state file.
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone


def state_file_path() -> Path:
    cwd = os.getcwd()
    key = hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:8]
    return Path(f"/tmp/claude-sql-schemas-{key}.json")


def load_state() -> dict:
    p = state_file_path()
    if not p.exists():
        return {"checked_tables": [], "updated_at": None}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"checked_tables": [], "updated_at": None}


def save_state(state: dict) -> None:
    p = state_file_path()
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# Patterns that extract table names from schema-inspection commands.
PATTERNS = [
    # WHERE TABLE_NAME = 'X' or "X"
    re.compile(r"TABLE_NAME\s*=\s*['\"]([\w]+)['\"]"),
    # WHERE TABLE_NAME = ? with array of names in surrounding scope
    # (we cover the array case below via PHP array literal scan)
    # SHOW CREATE TABLE X / SHOW CREATE TABLE `X`
    re.compile(r"SHOW\s+CREATE\s+TABLE\s+[`\"]?([\w]+)[`\"]?", re.IGNORECASE),
    # DESCRIBE X / DESC X
    re.compile(r"\b(?:DESCRIBE|DESC)\s+[`\"]?([\w]+)[`\"]?", re.IGNORECASE),
    # WHERE TABLE_NAME IN ('A','B','C')
]

# PHP array literal like: $tables = ["A", "B", "C"]
# Capture the entire array body, then split.
PHP_ARRAY = re.compile(
    r"\$tables\s*=\s*\[([^\]]+)\]",
    re.IGNORECASE,
)
ARRAY_ITEM = re.compile(r"['\"]([\w]+)['\"]")

# IN ('A','B','C')
IN_LITERAL = re.compile(
    r"TABLE_NAME\s+IN\s*\(([^)]+)\)",
    re.IGNORECASE,
)


def extract_tables(command: str) -> list[str]:
    tables = set()
    for pat in PATTERNS:
        for m in pat.finditer(command):
            tables.add(m.group(1))
    # PHP array literal: $tables = ["users", "orders", ...]
    for m in PHP_ARRAY.finditer(command):
        body = m.group(1)
        for item in ARRAY_ITEM.finditer(body):
            tables.add(item.group(1))
    # WHERE TABLE_NAME IN ('A','B','C')
    for m in IN_LITERAL.finditer(command):
        body = m.group(1)
        for item in ARRAY_ITEM.finditer(body):
            tables.add(item.group(1))
    return sorted(tables)


def looks_like_schema_query(command: str) -> bool:
    if "INFORMATION_SCHEMA" in command.upper():
        return True
    if re.search(r"SHOW\s+CREATE\s+TABLE", command, re.IGNORECASE):
        return True
    if re.search(r"\b(?:DESCRIBE|DESC)\s+\w+", command, re.IGNORECASE):
        return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = payload.get("tool_name") or payload.get("toolName")
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    tool_response = payload.get("tool_response") or payload.get("toolResponse") or {}

    if tool_name != "Bash":
        return 0

    command = tool_input.get("command", "") or ""
    if not isinstance(command, str):
        return 0

    if not looks_like_schema_query(command):
        return 0

    # Also require the bash command actually succeeded - if it failed (exit !=0),
    # the schema dump may be incomplete. Be permissive here: record anyway, since
    # partial dumps still constitute "claude has seen output" evidence.

    tables = extract_tables(command)
    if not tables:
        return 0

    state = load_state()
    existing = set(state.get("checked_tables", []))
    existing.update(tables)
    state["checked_tables"] = sorted(existing)
    save_state(state)

    # Optional: stderr note so claude sees what was recorded.
    sys.stderr.write(
        "[sql-schema-record] recorded tables: "
        + ", ".join(tables)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
