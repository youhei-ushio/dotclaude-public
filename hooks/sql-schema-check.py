#!/usr/bin/env python3
"""
PreToolUse hook for Write that validates SQL files reference only tables
whose schemas have been previously dumped in this working session.

Pairs with `sql-schema-record.py` (PostToolUse on Bash):
- `sql-schema-record.py` UPDATES the state file when schema queries run.
- This hook READS the state file to validate `.sql` files being written.

Triggered by Claude Code's PreToolUse hook with matcher="Write".

State file: /tmp/claude-sql-schemas-<sha1(cwd)[:8]>.json

Fires only when:
- tool_name == "Write"
- file_path matches `**/*.sql` (case-insensitive)

Validation:
- Parse content for table references (FROM/JOIN/UPDATE/INSERT INTO/DELETE FROM)
- For each non-system table name, require it appear in state's `checked_tables`
- Block (exit 2) with stderr listing unverified tables otherwise

Bypass: include a comment line in the SQL like:
  -- via:no-schema-check: <reason>
The hook will allow writing and surface the bypass reason in stderr.
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path


def state_file_path() -> Path:
    cwd = os.getcwd()
    key = hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:8]
    return Path(f"/tmp/claude-sql-schemas-{key}.json")


def load_checked_tables() -> set[str]:
    p = state_file_path()
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
        return set(data.get("checked_tables", []))
    except Exception:
        return set()


# Table extraction patterns. Capture group 1 = table name.
# Handle SQL Server [Table], MySQL `Table`, "Table", or bare identifier.
TOKEN = r"[\[\"`]?([\w]+)[\]\"`]?"

TABLE_PATTERNS = [
    re.compile(r"\bFROM\s+" + TOKEN + r"(?:\s+(?:AS\s+)?\w+)?", re.IGNORECASE),
    re.compile(r"\bJOIN\s+" + TOKEN + r"(?:\s+(?:AS\s+)?\w+)?", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+" + TOKEN + r"(?:\s+(?:AS\s+)?\w+)?", re.IGNORECASE),
    re.compile(r"\bINSERT\s+INTO\s+" + TOKEN, re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+" + TOKEN, re.IGNORECASE),
    re.compile(r"\bMERGE\s+INTO\s+" + TOKEN, re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+TABLE\s+" + TOKEN, re.IGNORECASE),
]

# Identifiers that should NOT be treated as table references.
# - SQL keywords commonly following FROM (rare but possible in subqueries)
# - System tables / schema-qualified system objects
SYSTEM_PREFIXES = (
    "INFORMATION_SCHEMA",
    "SYS",
    "MASTER",
    "TEMPDB",
    "MODEL",
    "MSDB",
    "PERFORMANCE_SCHEMA",
    "MYSQL",
)
SQL_RESERVED = {
    "SELECT", "WHERE", "AND", "OR", "NOT", "NULL", "TRUE", "FALSE",
    "AS", "ON", "BY", "ORDER", "GROUP", "HAVING", "LIMIT", "OFFSET",
    "UNION", "ALL", "DISTINCT", "INTO", "VALUES", "SET", "CASE",
    "WHEN", "THEN", "ELSE", "END", "BEGIN", "COMMIT", "ROLLBACK",
    "TRANSACTION", "DUAL", "LATERAL",
}


def is_system_or_reserved(name: str) -> bool:
    upper = name.upper()
    if upper in SQL_RESERVED:
        return True
    for prefix in SYSTEM_PREFIXES:
        if upper == prefix or upper.startswith(prefix + "."):
            return True
    return False


def extract_referenced_tables(sql: str) -> list[str]:
    found = set()
    for pat in TABLE_PATTERNS:
        for m in pat.finditer(sql):
            name = m.group(1)
            if not name:
                continue
            if is_system_or_reserved(name):
                continue
            # Skip schema-qualified system tables like INFORMATION_SCHEMA.COLUMNS
            if "." in name:
                # The TOKEN pattern doesn't match `.` so this shouldn't fire,
                # but kept for defensive parsing.
                continue
            found.add(name)
    return sorted(found)


def has_bypass(sql: str) -> tuple[bool, str]:
    m = re.search(r"--\s*via:no-schema-check\s*:\s*([^\n]+)", sql, re.IGNORECASE)
    if m:
        return True, m.group(1).strip()
    return False, ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = payload.get("tool_name") or payload.get("toolName")
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}

    if tool_name != "Write":
        return 0

    file_path = tool_input.get("file_path", "") or ""
    if not isinstance(file_path, str):
        return 0
    if not file_path.lower().endswith(".sql"):
        return 0

    content = tool_input.get("content", "") or ""
    if not isinstance(content, str) or not content.strip():
        return 0

    # Bypass marker takes precedence.
    bypassed, reason = has_bypass(content)
    if bypassed:
        sys.stderr.write(
            "[sql-schema-check] bypassed via marker: " + reason + "\n"
        )
        return 0

    referenced = extract_referenced_tables(content)
    if not referenced:
        return 0

    checked = load_checked_tables()
    unverified = [t for t in referenced if t not in checked]
    if not unverified:
        sys.stderr.write(
            "[sql-schema-check] OK: all referenced tables ("
            + ", ".join(referenced)
            + ") have been schema-dumped in this session.\n"
        )
        return 0

    print(
        "BLOCKED by sql-schema-check hook.\n"
        "reason: SQL ファイルに、このセッションでスキーマ dump していないテーブルが含まれている。\n"
        "file: " + file_path + "\n"
        "unverified tables: " + ", ".join(unverified) + "\n"
        "checked tables in this session: "
        + (", ".join(sorted(checked)) if checked else "(none)")
        + "\n"
        "Action: 当該テーブルを INFORMATION_SCHEMA.COLUMNS / SHOW CREATE TABLE で dump\n"
        "してから再度 Write を試みること。dump は production-investigate スキルの\n"
        "STEP 2.5 「使用テーブルの宣言と一括 dump」に従う。\n"
        "Bypass (only with explicit justification): add\n"
        "  -- via:no-schema-check: <reason>\n"
        "as a comment line in the SQL.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
