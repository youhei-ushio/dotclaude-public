#!/usr/bin/env python3
"""
permission-request-logger.py

Claude Code PermissionRequest hook (Unix / WSL 向け; fcntl を使用するため
Windows ネイティブ Python では動作しない)。

公式 docs (https://code.claude.com/docs/en/hooks.md) で PermissionRequest が
独立 event として列挙されている。Notification + notification_type ==
"permission_prompt" 経由の旧設計は実機で 0 件しか捕捉できなかったため、
本実装は PermissionRequest event を直接受ける設計に切り替えた。

payload schema は公式未文書化のため observe-first で運用する:
  - 初版は環境変数 PERM_REQUEST_DEBUG が "0" 以外のとき (デフォルト ON)
    全 payload を ~/.claude/logs/debug-perm-request.log に dump する。
    判定は厳密に `!= "0"` で行うため、"false" / "off" / "no" 等も ON 扱い
    になる。明示的に停止するときは `PERM_REQUEST_DEBUG=0` のみが有効。
  - 十分な観測後 (Phase B) に default OFF へ切替予定。

【秘密値の取り扱い注意 — Phase A】
許可ダイアログの対象になるコマンド (Bash の curl/wget で Authorization header
を使う、WebFetch の URL に token を含む等) は秘密値を含むことが多く、
本 hook の debug log / 本体 JSONL は tool_input を平文で append する。よって:
  - LOG_PATH / DEBUG_PATH ともに 0o600 で作成し、`os.open` + umask 077 で
    生成時から狭い権限を保つ (touch → chmod の race を避ける)
  - 親 dir (~/.claude/logs/) は他 hook と共有しているため無条件 chmod は
    しない (副作用回避)。dir 内の他ファイルの mode は各 hook 責任とする
  - Phase B で payload schema 確定後、tool_input の sanitize / マスキング
    か default OFF 化を検討する
  - Phase A 期間中のログはオペレーター以外に共有しない

JSONL 出力 schema は旧 Notification 経由実装と完全に後方互換を維持。
statusline (~/.claude/statusline.sh) と /review-permissions skill は
~/.claude/logs/permission-requests.jsonl の行数と field 名で動いており、
本 hook の差し替えだけで完結する (skill / statusline は無変更)。

LOG_PATH / DEBUG_PATH / DEBUG_ENABLED は module import 時に 1 回だけ評価
される。テストはサブプロセス起動 (毎回 import) を前提に env 経由で
override する設計。pytest 等で同一プロセス内 override したい場合は
将来 helper 関数化が必要。

env 評価の挙動 (LOG_PATH / DEBUG_PATH と DEBUG_ENABLED で異なる):
  - LOG_PATH / DEBUG_PATH: `os.environ.get(...) or default` で **未設定 /
    空文字** どちらも default に fallback。設定ミスは安全側に倒す意図。
  - DEBUG_ENABLED: `os.environ.get(..., "1") != "0"` で **未設定** は
    default の `"1"` で ON、**空文字** は `"" != "0"` で ON。結果は両者
    ON で同じ。明示的 OFF は `"0"` のみ。
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(
    os.environ.get("PERM_REQUEST_LOG_PATH")
    or (Path.home() / ".claude" / "logs" / "permission-requests.jsonl")
)
DEBUG_PATH = Path(
    os.environ.get("PERM_REQUEST_DEBUG_PATH")
    or (Path.home() / ".claude" / "logs" / "debug-perm-request.log")
)
DEBUG_ENABLED = os.environ.get("PERM_REQUEST_DEBUG", "1") != "0"
# `<project>-parallel-N` 形式の cwd から parallel 番号を抽出する。
# プロジェクトで命名規約が違う場合はここを書き換える。
PARALLEL_RE = re.compile(r"-parallel-(\d+)")

# 本体 JSONL から除外する内部 tool 名。
# AskUserQuestion / ExitPlanMode は「awaiting 化シグナル」として
# 意図的に PermissionRequest を fire させる用途であり、許可要求としてレビュー
# 対象にする意義は無い (= /review-permissions skill のノイズになる)。
# 本体 JSONL のみ filter し、debug log と tmux-pane-awaiting.sh への
# PermissionRequest 伝達は影響を受けない (schema 観測の継続性 + awaiting 化の
# 維持)。
INTERNAL_TOOLS_SKIP_LOGGING = frozenset({"AskUserQuestion", "ExitPlanMode"})


def identify_parallel(cwd: str) -> int:
    """cwd から `<project>-parallel-N` の N を抽出。該当なしは 0。"""
    m = PARALLEL_RE.search(cwd or "")
    return int(m.group(1)) if m else 0


def _open_secure_append(path: Path):
    """秘密値を含む log ファイルを 0o600 で safely open して append 用 fd を返す。

    失敗時 (symlink 検出 / chmod 失敗 / open 失敗等) は None を返し、呼び
    出し元が write skip する fail-closed 設計。

    is_symlink チェックと `os.open` の間の TOCTOU race を塞ぐため、open
    自体に `O_NOFOLLOW` を付与: race で symlink が挿入されても `ELOOP`
    で fail-closed になる。新規作成 / 既存追記 を同一の `os.open` 呼び
    出しで処理し、chmod は `os.fchmod(fd, 0o600)` で fd 経由 (= symlink
    を辿らず inode 自体に作用) で確実に 0o600 に揃える。

    親 dir 自体が symlink だった場合も拒否する (本 hook の信頼境界は
    `~/.claude/logs/` の下流のみであり、parent dir が attacker controlled
    symlink になっている脅威モデルは Claude Code 全体の信頼境界の問題で
    本 hook 単独では防げないが、念のため浅い検出は入れる)。

    本 hook は単発起動 (stdin 受け → exit) のサブプロセスのため、
    `os.umask` 設定はプロセス全体に影響するが他処理に副作用しない。
    finally で復元するため例外時も umask は元に戻る。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        print(
            f"[permission-request-logger] refusing: parent is symlink: {path.parent}",
            file=sys.stderr,
        )
        return None
    if path.is_symlink():
        print(
            f"[permission-request-logger] refusing to write to symlink: {path}",
            file=sys.stderr,
        )
        return None
    old_umask = os.umask(0o077)
    try:
        try:
            fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as e:
            print(
                f"[permission-request-logger] secure open failed on {path}: {e}",
                file=sys.stderr,
            )
            return None
    finally:
        os.umask(old_umask)
    try:
        # fd 経由の fchmod は symlink を辿らず inode 自体に作用するため、
        # check-then-open の race を経た後でも安全に 0o600 を強制できる。
        os.fchmod(fd, 0o600)
    except OSError as e:
        print(
            f"[permission-request-logger] fchmod 0o600 failed on {path}: {e} (skipping write)",
            file=sys.stderr,
        )
        os.close(fd)
        return None
    return fd


def _safe_json_default(obj: object) -> str:
    """JSON 非 serializable な値を型情報のみで置き換える。

    `default=str` で `__str__` 経由にすると bytes や object の repr で
    秘密値が漏れる可能性があるため、型名のみ残す (Phase A 観測では型 schema
    が分かれば十分で、生値は不要)。
    """
    return f"<non-serializable: {type(obj).__name__}>"


def _debug_dump(payload: dict) -> None:
    """observe-first: 全 payload を debug log に append する。

    Phase A の運用期間中に payload schema を実機観測するために有効化する。
    PERM_REQUEST_DEBUG=0 で無効化可能。失敗時は stderr に痕跡を残す
    (Phase A の目的が観測であるため、サイレント失敗は許容しない)。
    """
    if not DEBUG_ENABLED:
        return
    payload_dict = payload if isinstance(payload, dict) else {}
    try:
        fd = _open_secure_append(DEBUG_PATH)
        if fd is None:
            return
        rec = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "hook_event_name": payload_dict.get("hook_event_name", ""),
            "session_id": payload_dict.get("session_id", ""),
            "cwd": payload_dict.get("cwd", ""),
            # all_keys は raw を見れば取れるが、grep / jq での top-level 横断
            # 解析 (例: schema 観測のため `jq '.all_keys | unique'`) を簡便に
            # するため top-level に冗長コピーする。raw が `_safe_json_default`
            # で型名にしか変換できなかった場合の最終 fallback としても有効。
            "all_keys": sorted(payload_dict.keys()),
            "raw": payload,
        }
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                # default は型名のみ残す安全 fallback (bytes 等の repr 漏洩防止)
                f.write(json.dumps(rec, ensure_ascii=False, default=_safe_json_default) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        sid = payload_dict.get("session_id", "")
        cwd = payload_dict.get("cwd", "")
        print(
            f"[permission-request-logger debug] session={sid} cwd={cwd} type={type(e).__name__} err={e}",
            file=sys.stderr,
        )


def _as_dict(value: object) -> dict:
    """value が dict なら返す、そうでなければ空 dict。

    Phase A の payload schema 未確定下では、想定 field に str / list 等が
    入る可能性がある (e.g. `payload["tool"] == "Bash"` のような flat 形式)。
    `or {}` パターンは falsy のみガードするため、truthy な非 dict (空でない
    str/list) では `.get` が AttributeError を起こす。本関数で明示的に
    dict 型ガードする。
    """
    return value if isinstance(value, dict) else {}


def _extract_tool_info(payload: dict) -> dict:
    """PermissionRequest payload から tool 情報を抽出。

    payload schema は未確定なので、想定される field 名を順に試す:
      1. payload["tool_name"] / payload["tool_input"] / payload["tool_use_id"]
         (PreToolUse 系互換)
      2. payload["tool"]["name"] / payload["tool"]["input"] / payload["tool"]["id"]
         (nested)
      3. payload["request"]["tool_name"] etc. (request サブオブジェクト経由)

    どれも空なら {} を返す (本体 append は schema 不一致でも空 tool_name で
    続行する)。各値は型ガードして JSONL の type pollution を防ぐ:
      - `name` / `id`: str に正規化 (None は "" に)
      - `input`: dict に正規化 (list/str/None は {} に)
    """
    tool = _as_dict(payload.get("tool"))
    request = _as_dict(payload.get("request"))
    candidates = [
        (
            payload.get("tool_name"),
            payload.get("tool_input"),
            payload.get("tool_use_id"),
        ),
        (tool.get("name"), tool.get("input"), tool.get("id")),
        (
            request.get("tool_name"),
            request.get("tool_input"),
            request.get("tool_use_id"),
        ),
    ]
    for name, inp, tid in candidates:
        if name:
            safe_name = name if isinstance(name, str) else str(name)
            safe_input = inp if isinstance(inp, dict) else {}
            safe_tid = tid if isinstance(tid, str) else ("" if tid is None else str(tid))
            return {"name": safe_name, "input": safe_input, "id": safe_tid}
    return {}


def append_log(payload: dict) -> None:
    """PermissionRequest event のときログに 1 行 append。

    防御 filter: hook_event_name が truthy かつ "PermissionRequest" 以外
    なら無視 (settings.json で誤って別 event に登録された場合の保険)。
    field 欠落 / 空文字は accept する (Claude Code バージョン差で field 自体が
    欠落した場合の false negative を防ぐ。docstring の「field 欠落でも accept」
    と一貫させる)。

    内部 tool filter: `INTERNAL_TOOLS_SKIP_LOGGING` に含まれる tool_name
    (AskUserQuestion / ExitPlanMode 等) は本体 JSONL から除外する。これらは
    awaiting 化シグナルとして意図的に PermissionRequest を fire させる用途で、
    許可要求としてレビュー対象にする意義が無いため。
    debug log (`_debug_dump`) と tmux-pane-awaiting.sh への伝達は本 filter の
    対象外で従来通り動作する。`_debug_dump` は main() で本関数より前に呼ばれる
    (本関数の filter は debug 出力後にのみ作用する) ため、Phase A の schema
    観測継続性は壊れない。
    比較は前後空白を除いた exact match (Claude Code の tool_name 文字列が
    厳密一致前提)。schema が変わって大小文字違いで来た場合は logger に流入
    するため、debug log で発見次第 `INTERNAL_TOOLS_SKIP_LOGGING` を更新する
    運用とする。
    """
    event = payload.get("hook_event_name")
    if event and event != "PermissionRequest":
        return
    try:
        tool_info = _extract_tool_info(payload)
        tool_name = (tool_info.get("name") or "").strip()
        if tool_name in INTERNAL_TOOLS_SKIP_LOGGING:
            return
        entry = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "parallel": identify_parallel(payload.get("cwd", "")),
            "cwd": payload.get("cwd", ""),
            "session_id": payload.get("session_id", ""),
            "transcript_path": payload.get("transcript_path", ""),
            "title": payload.get("title", ""),
            "message": payload.get("message", ""),
            "tool_use_id": tool_info.get("id", ""),
            "tool_name": tool_info.get("name", ""),
            "tool_input": tool_info.get("input", {}),
        }
        fd = _open_secure_append(LOG_PATH)
        if fd is None:
            return
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                # default は debug log と対称化 (型名のみ、bytes 等の repr 漏洩防止)
                f.write(json.dumps(entry, ensure_ascii=False, default=_safe_json_default) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        sid = payload.get("session_id", "")
        cwd = payload.get("cwd", "")
        print(
            f"[permission-request-logger] session={sid} cwd={cwd} type={type(e).__name__} err={e}",
            file=sys.stderr,
        )


def main() -> int:
    try:
        # json.JSONDecodeError は ValueError サブクラス。OSError は stdin の
        # I/O 障害 (まれ) を握り潰す。それ以外の予期せぬ例外 (MemoryError 等)
        # は素通り stderr に traceback を出すことで Phase A 観測情報とする。
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        # PermissionRequest payload は dict 想定 (json.load は list/str/number
        # 等も返しうるが、本 hook の対象は dict 形式のみ)。dict 以外は
        # observe-first でも本体 append でも処理対象外。stderr に痕跡を
        # 残して Phase A 観測の漏れを防ぐ。
        print(
            f"[permission-request-logger] non-dict payload type={type(payload).__name__}",
            file=sys.stderr,
        )
        return 0
    _debug_dump(payload)
    append_log(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
