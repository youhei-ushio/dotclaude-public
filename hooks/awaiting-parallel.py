#!/usr/bin/env python3
"""
awaiting-parallel.py

Claude Code PermissionRequest / UserPromptSubmit / SessionStart hook
(Unix / WSL 向け; fcntl を使用するため Windows ネイティブ Python では動作しない)。

並走 `<project>-parallel-N` 環境で「どの parallel が応答待ちか」を共有 state
ファイルで管理する。表示自体は statusline.sh の 4 行目で行う。

state ファイル: ~/.claude/state/awaiting.tsv
形式 (1 行 1 エントリ、tab 区切り):
    <session_id>\\t<parallel_num>\\t<unix_ts>

動作:
- PermissionRequest             → add (ユーザー入力要求の明示シグナル: AskUserQuestion /
                                        WebFetch / Bash 等の許可ダイアログ / ExitPlanMode)
- UserPromptSubmit              → remove (ユーザーが入力 = 待機解除、session_id 一致で削除)
- PostToolUse                   → remove (ツールが実行された = 直前の許可/質問が解決され
                                   Claude が再び稼働中 = もう awaiting でない、session_id 一致で削除。
                                   許可ダイアログ承認 / AskUserQuestion 回答 / ExitPlanMode 承認は
                                   UserPromptSubmit を発火しないため、それらを解決した後の最初の
                                   ツール実行でここから remove する。全ツールで高頻度発火するため
                                   lock-free 事前チェックで当該 session 不在なら即 return)
- SessionStart (clear/startup)  → parallel_num ベース全 remove (旧 session_id
                                   エントリ取りこぼし対策。/clear・/exit→再起動の両方)
- `<project>-parallel-N` 環境外 (parallel_num == 0) は無視

`Notification` / `Stop` / `SubagentStop` は **登録しない / 受信しても無視** する:
- `Stop` add (= Claude のターン終了で一律 awaiting 化) は過去に採用したが、
  「ありがとう→どういたしまして」のような対話の余韻まで awaiting 化される問題が
  あった。PermissionRequest event が「ユーザー入力要求の正規シグナル」として機能
  することが Phase A 観測で確認できたため、本実装で PermissionRequest 一本に
  切り替えた。
- `Notification` は元々主トリガーだったが、auto-classifier 経路で fire しない
  ケースが多く Stop add に反転していた。PermissionRequest に切り替えた本実装では
  Notification も無用。
- `SubagentStop` は subagent の session_id が親と異なる仕様で add/remove どちらも
  意味的に誤りのため未登録。

防御 filter (`if event == "PermissionRequest":` 等) で、settings.json で誤って
別 event 配下に登録された場合も hook 単体で安全に振る舞う。

例外は飲み込む。hook 失敗で Claude Code 側を止めない原則。

設計上の判断 (なぜこの形か):
- add トリガーは Notification → Stop → PermissionRequest と変遷した。最終的に
  PermissionRequest 一本にしたのは、それが「ユーザー入力要求」の最も正確な
  シグナルだったため (上記参照)。
- one-entry-per-parallel: add 時に同 parallel_num の旧 entry を排除する。親
  session の /exit → 再起動で session_id が変わると旧 entry が滞留し、
  session_id 一致 remove で消えない問題への対策。1 parallel = 1 Claude プロセス前提。
- SessionStart の clear / startup 両方で parallel_num ベース全 remove する。
  /clear・/exit→再起動のいずれも「その parallel を新しいコンテキストが引き継いだ」
  状態であり、旧 session の応答待ち残骸を消すのが妥当。
- PostToolUse remove: 許可ダイアログ承認 / AskUserQuestion 回答 / ExitPlanMode
  承認は UserPromptSubmit を発火しないため、それらの解決後に新規プロンプトを
  打たないと awaiting が滞留する。ツール実行 (= 解決後の稼働再開) を remove
  シグナルに追加してこの取りこぼしを塞ぐ。
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "state" / "awaiting.tsv"
# ロック専用ファイル。本体 (STATE_PATH) は os.replace で inode が変わるため
# 本体に対する flock は inode 切替で無効化される。inode 不変の別ファイルで
# 取って並走環境の同時更新を確実に逐次化する。
LOCK_PATH = STATE_PATH.parent / "awaiting.lock"
STATE_TMP_DIR = STATE_PATH.parent   # _atomic_rewrite が同 fs に tmp を作る場所
STALE_TTL_SEC = 4 * 60 * 60   # 4 時間。statusline 側 THRESHOLD と同値
# `<project>-parallel-N` 形式の cwd から parallel 番号を抽出する。
# プロジェクトで命名規約が違う場合はここを書き換える。
PARALLEL_RE = re.compile(r"-parallel-(\d+)")


@contextlib.contextmanager
def _exclusive_lock():
    """LOCK_PATH の flock を取得する context manager。
    本体 STATE_PATH が os.replace で inode 切替されても、LOCK_PATH の
    inode は不変なので並走 hook 間の排他が確実に効く。
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.touch(exist_ok=True)
    with LOCK_PATH.open("r+", encoding="utf-8") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            # close で自動解放されるが明示的に
            fcntl.flock(lf, fcntl.LOCK_UN)


def identify_parallel(cwd: str) -> int:
    """cwd から `<project>-parallel-N` の N を抽出。該当なしは 0。"""
    m = PARALLEL_RE.search(cwd or "")
    return int(m.group(1)) if m else 0


def _parse_line(line: str) -> tuple[str, int, int] | None:
    """1 行を (session_id, parallel_num, ts) に分解。不正行は None。
    parallel_num / ts は int で返す。フィールド数は厳密に 3 を要求。
    """
    parts = line.split("\t")
    if len(parts) != 3:
        return None
    try:
        pnum = int(parts[1])
        ts = int(parts[2])
    except ValueError:
        return None
    if pnum <= 0:
        return None
    return parts[0], pnum, ts


def _read_current() -> list[str]:
    """state file の現在内容を行リストで返す。不在/破損は []。"""
    try:
        return STATE_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError:
        return []


def _session_present(session_id: str) -> bool:
    """state file を **lock-free** で読み、session_id を含む行があれば True。

    PostToolUse は全ツールで高頻度に発火するため、当該 session が awaiting
    に登録されていない一般ケースでは flock を取らずに即 return できるよう
    にする hot-path 用の事前チェック。flock を取らないので read と後続の
    remove_entry の間に微小な race はあるが、remove は冪等であり (該当無し
    なら no-op)、取りこぼしても次のツール実行で再度ここを通るため許容する。
    """
    if not session_id:
        return False
    for raw in _read_current():
        parsed = _parse_line(raw)
        if parsed is not None and parsed[0] == session_id:
            return True
    return False


def _atomic_write(lines: list[str]) -> None:
    """state file をアトミックに書き換える。tmp に書いてから rename。
    呼び出し側が LOCK_PATH の flock を保持している前提。
    0 件なら state file を削除 (本来のクリーン状態にする)。
    """
    if not lines:
        try:
            STATE_PATH.unlink()
        except FileNotFoundError:
            pass
        return
    fd, tmp_path = tempfile.mkstemp(
        prefix="awaiting-", suffix=".tsv.tmp", dir=str(STATE_TMP_DIR)
    )
    # fd を fdopen に渡す前に失敗した場合に備え、fd 単独で close する経路を持つ
    try:
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
        except Exception:
            os.close(fd)
            raise
        with f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp_path, str(STATE_PATH))
    except Exception:
        # tmp 残骸を掃除
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _compact_and_filter(
    cutoff: int,
    skip_session_id: str | None = None,
) -> tuple[list[str], list[str], set[str], bool]:
    """現状を読んで (stale 除外 / skip_session_id 除外 / 破損行除外) 後の
    行リスト、元の有効行リスト (空行除く)、現存 session_id 集合、
    そして「除外が発生したか (= rewrite が必要)」フラグを返す。
    除外発生フラグは破損行 / stale / 指定 session_id 除去のいずれかが
    起きたら True。呼び出し側はこのフラグで rewrite 要否を判定する。
    """
    original_raw = _read_current()
    original_nonblank: list[str] = []
    live: list[str] = []
    session_ids: set[str] = set()
    excluded = False
    for raw in original_raw:
        if not raw.strip():
            continue
        original_nonblank.append(raw)
        parsed = _parse_line(raw)
        if parsed is None:
            excluded = True   # 破損行を捨てた
            continue
        sid, _pnum, ts = parsed
        if ts < cutoff:
            excluded = True   # stale を捨てた
            continue
        if skip_session_id is not None and sid == skip_session_id:
            excluded = True   # 削除指定された session を捨てた
            continue
        live.append(raw)
        session_ids.add(sid)
    return original_nonblank, live, session_ids, excluded


def add_entry(session_id: str, parallel_num: int) -> None:
    """parallel_num ごとに 1 entry を保証 (one-entry-per-parallel)。
    同 session_id が既にあれば ts 固定、無ければ append。
    同時に stale (TTL 超) と同 parallel_num の他 session_id 行を compaction。

    ts ポリシー:
      - 同 session_id 内では ts 固定 (= 最初の PermissionRequest 時点で打った値を維持)
      - parallel_num 単位で見ると、session_id が変わる (= /exit → 再起動) と
        新 ts が打たれる (= 再起動を起点に表示更新)

    意図: long-press 状態の応答待ちは TTL 4h で自動的に list から消えて
    画面表示が clean になる。再表示したい場合は次の PermissionRequest を待つ。

    add 時に **同じ parallel_num の異なる session_id の entry は常に削除** する
    (one-entry-per-parallel)。新規 session_id 経路 (再起動後の新 session の
    初回 PermissionRequest add) と既存 session_id 経路 (同 session 内の複数回
    PermissionRequest add) の両方で旧 entry を排除する。親 session の
    /exit → 再起動で session_id が変わると旧 session_id の entry が awaiting.tsv
    に滞留して UserPromptSubmit の session_id remove で消えない問題への対策。
    1 parallel に対し 1 Claude プロセスを前提とする。

    副作用: 本関数の呼び出しは「破損行 / stale (TTL 超過) 行 / 同 parallel の
    他 session_id 行」の 3 種を同時に compaction する (`_compact_and_filter`
    + parallel フィルタ)。新規 add 時だけでなく既存 session_id 経路でも、
    これらの掃除のために state file が書き戻される。
    """
    if not session_id or parallel_num <= 0:
        return
    if "\t" in session_id or "\n" in session_id:
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock():
        now = int(time.time())
        cutoff = now - STALE_TTL_SEC
        _original, live, session_ids, excluded = _compact_and_filter(cutoff)
        # 同 parallel_num の他 session_id 行を排除する。新規 add でも既存
        # session の再 add でも、同じ parallel 内に複数 session_id が並存
        # しないよう常に走らせる (one-entry-per-parallel を構造的に保証)。
        # invariant: 同 parallel フィルタも防御パスも空振り、かつ `excluded`
        # も False なら kept は live と同一順序・同一内容になる
        # (= needs_rewrite_for_compaction は False のまま、書き戻し不要)。
        kept: list[str] = []
        needs_rewrite_for_compaction = excluded
        for raw in live:
            parsed = _parse_line(raw)
            if parsed is None:
                # _compact_and_filter で parse 成功確定 (= 到達不能の防御パス)。
                # 万一到達した場合は invariant 違反として該当行を捨て、
                # 書き戻して clean up を促す (kept が live より短くなるため
                # 必ず disk に反映する必要がある)。診断性のため stderr にも
                # 痕跡を残し、invariant 違反が静かに hide されないようにする。
                print(
                    f"[awaiting-parallel] invariant violated: parse failed "
                    f"in add_entry kept loop (raw={raw!r})",
                    file=sys.stderr,
                )
                needs_rewrite_for_compaction = True
                continue
            sid, pnum, _ts = parsed
            if pnum == parallel_num and sid != session_id:
                needs_rewrite_for_compaction = True
                continue
            kept.append(raw)
        if session_id in session_ids:
            # 既存 session_id ヒット。ts は固定 (既存行が kept に残っている)。
            # 「破損 / stale / 同 parallel 他 session 排除 / 防御パス」の
            # いずれかが起きていたら kept != live になるため書き戻す。
            # `needs_rewrite_for_compaction` が False なら kept == live で no-op。
            if needs_rewrite_for_compaction:
                _atomic_write(kept)
            return
        # 新規 session_id。append して書き戻す。
        kept.append(f"{session_id}\t{parallel_num}\t{now}")
        _atomic_write(kept)


def remove_entries_by_parallel(parallel_num: int) -> None:
    """指定 parallel_num の全 entry を remove。`/clear` および `/exit`→再起動
    (source=startup) の SessionStart 時に呼ばれる。

    session_id ベースの `remove_entry` (UserPromptSubmit 経路) と別軸で、
    parallel 単位の一括クリアを担う。`/clear` 後・再起動後の新セッション
    は別 session_id を持つため session_id 一致では旧 entry を消せず、
    parallel_num 一致で消す。同時に stale (TTL 超) / 破損行も compaction する。
    """
    if parallel_num <= 0:
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock():
        cutoff = int(time.time()) - STALE_TTL_SEC
        _original, live, _sids, excluded = _compact_and_filter(cutoff)
        # `excluded` (= _compact_and_filter での stale / 破損行除去) を起点に
        # 累積フラグを立てる。`add_entry` の `needs_rewrite_for_compaction`
        # と同じパターンで一貫させる。
        kept: list[str] = []
        needs_rewrite = excluded
        for raw in live:
            parsed = _parse_line(raw)
            if parsed is None:
                # _compact_and_filter で parse 成功確定 (= 到達不能の防御パス)。
                # 万一到達した場合は invariant 違反として該当行を捨て、書き戻す。
                # 診断性のため stderr にも痕跡を残す (add_entry と一貫させる)。
                print(
                    f"[awaiting-parallel] invariant violated: parse failed "
                    f"in remove_entries_by_parallel kept loop (raw={raw!r})",
                    file=sys.stderr,
                )
                needs_rewrite = True
                continue
            sid, pnum, _ts = parsed
            if pnum == parallel_num:
                needs_rewrite = True
                continue
            kept.append(raw)
        # `needs_rewrite` が True (= 破損 / stale / 該当 parallel 除去のいずれか
        # が発生) なら書き戻す。False なら kept == live で no-op。
        if needs_rewrite:
            _atomic_write(kept)


def remove_entry(session_id: str) -> None:
    """当該 session_id の行を削除。同時に stale / 破損行も compaction。"""
    if not session_id:
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock():
        cutoff = int(time.time()) - STALE_TTL_SEC
        _original, live, _sids, excluded = _compact_and_filter(
            cutoff, skip_session_id=session_id
        )
        # 除外が一切発生しなかった (= 該当 session が元から無く、stale/破損も
        # 無かった) なら書き戻し不要
        if not excluded:
            return
        _atomic_write(live)


def main() -> int:
    # 二重 try: 内側で業務ロジック、外側で stderr 出力すら失敗するケースを吸収。
    # hook 失敗で Claude Code 側を絶対に止めないために bare except でガード。
    try:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError, OSError):
            return 0
        if not isinstance(payload, dict):
            return 0
        # except 節での UnboundLocalError 防止 (= payload.get 等で例外が出ても
        # 診断ログが出るよう、try 開始前に名前を確保しておく)
        event = ""
        session_id = ""
        parallel_num = 0
        tool_name = ""
        source = ""
        try:
            event = payload.get("hook_event_name", "") or ""
            session_id = payload.get("session_id", "") or ""
            cwd = payload.get("cwd", "") or ""
            parallel_num = identify_parallel(cwd)
            # tool_name は診断ログ用に取得。本ロジックでは使用しない
            # (Phase B で tool_name allowlist/denylist を検討する際に活用)
            tool_name = payload.get("tool_name", "") or ""
            # source は SessionStart event の発火元 (startup/clear/resume/compact)
            # を識別する field。診断ログにも含めて運用時の挙動切り分けを助ける
            source = payload.get("source", "") or ""

            if event == "PermissionRequest":
                # PermissionRequest = ユーザー入力要求 (AskUserQuestion / 許可
                # ダイアログ / ExitPlanMode 等) → add
                add_entry(session_id, parallel_num)
            elif event == "UserPromptSubmit":
                # ユーザーが入力 → 待機解除 (remove)
                remove_entry(session_id)
            elif event == "PostToolUse":
                # ツールが実行された = 直前の許可/質問が解決され Claude が再び
                # 稼働中 = もう awaiting でない → remove。
                # 許可ダイアログ承認 / AskUserQuestion 回答 / ExitPlanMode 承認は
                # UserPromptSubmit を発火しないため、それらの解決後に新規プロンプト
                # を打たないと awaiting が滞留する。解決後の最初のツール実行をここで
                # 捉えて remove する。
                # PostToolUse は全ツールで高頻度発火するので、parallel 外 / 当該
                # session が state に無い一般ケースは flock を取らず即 return する
                # (lock-free fast path)。flock を取るのは実際に削除がある場合のみ。
                if parallel_num > 0 and _session_present(session_id):
                    remove_entry(session_id)
            elif event == "SessionStart":
                # `clear` (/clear) と `startup` (/exit→再起動 や新規プロセス起動)
                # で awaiting をクリア。どちらも「その parallel を新しいコンテキスト
                # が引き継いだ」状態で、旧 session の応答待ち残骸を消すのが妥当
                # (1 parallel 1 Claude 前提)。
                # source が "resume" / "compact" の場合は「同一セッションの
                # コンテキスト維持」操作とみなし旧 awaiting を保持する
                # (resume は session_id も同一なので UserPromptSubmit で正規に
                # 解除される)。
                # settings.json で matcher による絞り込みも入れているが、
                # 誤配置時の保険として hook 単体でも source 判定で二重防御する。
                # 注: SessionStart の session_id は **新セッション** のもの。
                # awaiting.tsv に登録された旧 entry の session_id とは異なる
                # ため、session_id 一致 remove ではなく parallel_num ベースで
                # 全 remove する。
                if source in ("clear", "startup"):
                    remove_entries_by_parallel(parallel_num)
            # 上記以外 (Notification / Stop / SubagentStop / 未知 event) は
            # すべて無視 (= 「対話の余韻」は awaiting に含めない)。
            # 詳細は module docstring 参照。
        except Exception as e:
            try:
                # デバッグ用に event/session_id 先頭/parallel/tool_name/source
                # を含める。SessionStart 経路の session_id は新セッションのもの
                # (sid=new) で、awaiting.tsv に登録された旧 entry とは異なる
                # 点に注意。source 値で発火元 (startup/clear/resume/compact)
                # も切り分け可能
                print(
                    f"[awaiting-parallel] event={event} sid={session_id[:8]} "
                    f"pnum={parallel_num} tool={tool_name} source={source}: {e}",
                    file=sys.stderr,
                )
            except Exception:
                pass
    except BaseException:
        # KeyboardInterrupt 等も含めて確実に 0 終了
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
