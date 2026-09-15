#!/usr/bin/env python3
"""
serve-ui-approval.py — スクリーンショットの承認/指摘を収集する Web UI サーバー。

使い方:
    python3 serve-ui-approval.py <review.json> [port]

review.json のスキーマ:
    {
      "title": "レビュータイトル",
      "items": [
        {
          "id": "screen-1",
          "label": "画面名",
          "image_path": "docs/images/xxx.png",
          "description": "説明",
          "design_rationale": "設計根拠"
        }
      ]
    }

image_path は基点ディレクトリ (git toplevel、無ければ cwd) からの相対パス。
配信する画像は起動時に items[].image_path から作った allowlist に完全一致するものだけ。

起動時にトークンを生成し (プロセス寿命で有効)、stdout に `?t=<token>` 付き URL を出力する。
GET / と GET /image は `?t=`、POST /submit は `X-Review-Token` ヘッダで照合する (不一致は 403)。

送信後、review.json に results を書き戻して exit 0 する。
"""

from __future__ import annotations

import hmac
import html
import json
import os
import re
import secrets
import socket
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, unquote, urlsplit

VALID_STATUS = {"approved", "rejected"}
MAX_BODY_BYTES = 1_000_000


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def resolve_base_dir() -> Path:
    """image_path の基点。git toplevel、取れなければ cwd。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if out:
            return Path(out).resolve()
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.cwd().resolve()


def build_allowlist(items: list, base_dir: Path) -> dict:
    """image_path (相対) → 解決済み絶対パス。絶対パス・base 外に出るパスは ValueError。"""
    allowed = {}
    base = base_dir.resolve()
    for item in items:
        rel = item.get("image_path")
        if not isinstance(rel, str) or not rel:
            raise ValueError(f"review.json: item {item.get('id')!r} needs a non-empty image_path")
        if Path(rel).is_absolute():
            raise ValueError(f"review.json: image_path must be relative to the base dir: {rel!r}")
        full = (base / rel).resolve()
        if full != base and base not in full.parents:
            # symlink も解決した結果で判定する (base 内の symlink が外を指す場合も含む)
            raise ValueError(f"review.json: image_path escapes the base dir: {rel!r} (resolved: {full})")
        if not full.is_file():
            raise ValueError(f"review.json: image file not found: {rel!r} (resolved: {full})")
        allowed[rel] = full
    return allowed


# プレースホルダは str.replace で埋める (str.format は CSS/JS の {} と衝突する)
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; color: #333; padding: 20px; }
h1 { text-align: center; margin-bottom: 24px; font-size: 1.5rem; }
.progress { text-align: center; margin-bottom: 20px; color: #666; }
.card { background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 24px; overflow: hidden; max-width: 900px; margin-left: auto; margin-right: auto; }
.card-header { padding: 16px 20px; background: #fafafa; border-bottom: 1px solid #eee; }
.card-header h2 { font-size: 1.1rem; }
.card-header .desc { color: #666; font-size: 0.9rem; margin-top: 4px; }
.card-header .rationale { color: #888; font-size: 0.85rem; margin-top: 4px; font-style: italic; }
.card-image { padding: 16px; text-align: center; background: #fafafa; }
.card-image img { max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; }
.card-actions { padding: 16px 20px; display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
.btn { padding: 10px 24px; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer;
       transition: background 0.2s; }
.btn-approve { background: #4caf50; color: #fff; }
.btn-approve:hover { background: #43a047; }
.btn-approve.active { background: #2e7d32; box-shadow: 0 0 0 3px rgba(76,175,80,0.3); }
.btn-reject { background: #ff9800; color: #fff; }
.btn-reject:hover { background: #f57c00; }
.btn-reject.active { background: #e65100; box-shadow: 0 0 0 3px rgba(255,152,0,0.3); }
.comment-box { flex: 1; min-width: 200px; }
.comment-box textarea { width: 100%; height: 80px; padding: 8px; border: 1px solid #ddd;
                         border-radius: 6px; font-size: 0.9rem; resize: vertical; }
.comment-box.hidden { display: none; }
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;
                margin-left: 8px; }
.status-approved { background: #e8f5e9; color: #2e7d32; }
.status-rejected { background: #fff3e0; color: #e65100; }
.submit-bar { text-align: center; margin: 32px 0; }
.btn-submit { padding: 14px 48px; background: #1976d2; color: #fff; font-size: 1.1rem;
              border: none; border-radius: 8px; cursor: pointer; }
.btn-submit:hover { background: #1565c0; }
.btn-submit:disabled { background: #bbb; cursor: not-allowed; }
.summary { text-align: center; color: #666; margin-bottom: 12px; }
</style>
</head>
<body>
<h1>__TITLE__</h1>
<div class="progress" id="progress"></div>

<div id="cards"></div>

<div class="summary" id="summary"></div>
<div class="submit-bar">
  <button class="btn btn-submit" id="submitBtn" disabled onclick="submitResults()">
    全項目レビュー後に送信可能
  </button>
</div>

<script>
const items = __ITEMS_JSON__;
const token = __TOKEN_JSON__;
const results = Object.create(null);   // id が __proto__ 等でも Object.prototype に当たらない

function esc(s) {
  // text と属性の両コンテキストで使うので引用符も変換する
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderCards() {
  const container = document.getElementById('cards');
  container.innerHTML = '';
  items.forEach((item, idx) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.id = 'card-' + item.id;

    const statusBadge = results[item.id]
      ? `<span class="status-badge ${results[item.id].status === 'approved' ? 'status-approved' : 'status-rejected'}">${results[item.id].status === 'approved' ? '✓ 承認' : '✎ 指摘あり'}</span>`
      : '';

    card.innerHTML = `
      <div class="card-header">
        <h2>${idx + 1}. ${esc(item.label)} ${statusBadge}</h2>
        <div class="desc">${esc(item.description)}</div>
        ${item.design_rationale ? `<div class="rationale">設計根拠: ${esc(item.design_rationale)}</div>` : ''}
      </div>
      <div class="card-image">
        <img src="/image/${encodeURIComponent(item.image_path)}?t=${encodeURIComponent(token)}" alt="${esc(item.label)}" loading="lazy">
      </div>
      <div class="card-actions">
        <button class="btn btn-approve ${results[item.id]?.status === 'approved' ? 'active' : ''}"
                data-status="approved">✓ 承認</button>
        <button class="btn btn-reject ${results[item.id]?.status === 'rejected' ? 'active' : ''}"
                data-status="rejected">✎ 指摘</button>
        <div class="comment-box ${results[item.id]?.status === 'rejected' ? '' : 'hidden'}">
          <textarea placeholder="修正内容を記入..."
          >${esc(results[item.id]?.comment || '')}</textarea>
        </div>
      </div>
    `;
    // id を属性に埋めず、クロージャで束縛する (inline handler は引用符で属性が壊れる)
    card.querySelectorAll('.btn-approve, .btn-reject').forEach(btn => {
      btn.addEventListener('click', () => setStatus(item.id, btn.dataset.status));
    });
    card.querySelector('textarea').addEventListener('input', ev => updateComment(item.id, ev.target.value));
    container.appendChild(card);
  });
  updateProgress();
}

function setStatus(id, status) {
  if (!results[id]) results[id] = {};
  results[id].status = status;   // コメントは消さない (取消→再指摘で入力を失わないため)。送信時に rejected のみ付ける
  renderCards();
  if (status === 'rejected') {
    const card = document.getElementById('card-' + id);
    if (card) card.querySelector('textarea').focus();
  }
}

function updateComment(id, value) {
  if (!results[id]) return;   // status 未設定のカードは対象外 (rejected 時しか入力欄は出ない)
  results[id].comment = value;
  updateProgress();
}

function missingComments() {
  return Object.values(results).filter(r => r.status === 'rejected' && !(r.comment || '').trim()).length;
}

function updateProgress() {
  const total = items.length;
  const done = Object.keys(results).length;
  const approved = Object.values(results).filter(r => r.status === 'approved').length;
  const rejected = Object.values(results).filter(r => r.status === 'rejected').length;

  document.getElementById('progress').textContent =
    `${done} / ${total} 件レビュー済み`;

  const btn = document.getElementById('submitBtn');
  const missing = missingComments();
  if (done === total && missing === 0) {
    btn.disabled = false;
    btn.textContent = `送信（承認: ${approved} 件 / 指摘: ${rejected} 件）`;
  } else if (done === total) {
    btn.disabled = true;
    btn.textContent = `指摘のコメント未記入が ${missing} 件あります`;
  } else {
    btn.disabled = true;
    btn.textContent = `全項目レビュー後に送信可能（残り ${total - done} 件）`;
  }

  document.getElementById('summary').textContent =
    done === total ? (rejected > 0 ? '指摘がある項目は修正後に再レビューされます' : '全件承認です') : '';
}

async function submitResults() {
  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  const payload = items.map(item => ({
    id: item.id,
    status: results[item.id].status,
    ...(results[item.id].status === 'rejected' ? { comment: results[item.id].comment.trim() } : {})
  }));

  let res;
  try {
    res = await fetch('/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Review-Token': token },
      body: JSON.stringify({ items: payload })
    });
  } catch (e) {
    alert('送信に失敗しました (サーバーに接続できません)');
    btn.disabled = false;
    return;
  }

  if (res.ok) {
    document.body.innerHTML = '<h1 style="text-align:center;margin-top:40vh;color:#4caf50">送信完了 ✓</h1><p style="text-align:center;color:#666">このタブを閉じてください</p>';
  } else {
    alert('送信に失敗しました (HTTP ' + res.status + ')');
    btn.disabled = false;
  }
}

renderCards();
</script>
</body>
</html>"""


def render_html(review_data: dict, token: str) -> str:
    """テンプレートにタイトル・items・トークンを埋める。"""
    title = html.escape(str(review_data.get("title") or "UI 承認レビュー"))
    # <script> 内に埋めるので "</" と "<!--" をエスケープする (</script> 混入や
    # script data の escaped state で崩れないようにする)
    items_json = (json.dumps(review_data["items"], ensure_ascii=False)
                  .replace("</", "<\\/").replace("<!--", "<\\!--"))
    mapping = {"__TITLE__": title, "__ITEMS_JSON__": items_json, "__TOKEN_JSON__": json.dumps(token)}
    # 1 パスで置換する (逐次 replace だとデータ中のプレースホルダ文字列が再置換される)
    return re.sub(r"__(TITLE|ITEMS_JSON|TOKEN_JSON)__", lambda m: mapping[m.group(0)], HTML_TEMPLATE)


def validate_submission(body, expected_ids: set):
    """/submit の body を検証する。問題があれば理由文字列、無ければ None。"""
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        return "items must be a list"
    seen = set()
    for r in body["items"]:
        if not isinstance(r, dict):
            return "item must be an object"
        rid = r.get("id")
        if not isinstance(rid, str) or rid not in expected_ids:
            return f"unknown id: {rid!r}"
        if rid in seen:
            return f"duplicate id: {rid!r}"
        seen.add(rid)
        if r.get("status") not in VALID_STATUS:
            return f"invalid status for {rid!r}"
        if "comment" in r and not isinstance(r["comment"], str):
            return f"comment must be a string for {rid!r}"
        if r["status"] == "rejected" and not (r.get("comment") or "").strip():
            return f"rejected item needs a comment: {rid!r}"
    if seen != expected_ids:
        return "ids do not match review items"
    return None


def make_handler(review_data: dict, review_path: Path, server_ref: list, token: str, allowlist: dict):
    expected_ids = {item.get("id") for item in review_data["items"]}

    class Handler(BaseHTTPRequestHandler):
        timeout = 30   # body を送らず握るクライアントが単一スレッドを塞ぎ続けないようにする

        def log_message(self, fmt, *args):
            pass

        def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8",
                  extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # トークン入りページ・業務画面のスクショを端末キャッシュに残さない
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _token_ok(self, presented) -> bool:
            if not isinstance(presented, str):
                return False
            # str 同士の compare_digest は非 ASCII で TypeError になるので bytes で比較する
            return hmac.compare_digest(presented.encode("utf-8", "surrogateescape"), token.encode("utf-8"))

        def do_GET(self):
            parts = urlsplit(self.path)
            if parts.path == "/":
                presented = parse_qs(parts.query).get("t", [None])[0]
                if not self._token_ok(presented):
                    self._send(403, b"Forbidden: token required")
                    return
                page = render_html(review_data, token)
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif parts.path.startswith("/image/"):
                presented = parse_qs(parts.query).get("t", [None])[0]
                if not self._token_ok(presented):
                    self._send(403, b"Forbidden: token required")
                    return
                rel = unquote(parts.path[7:])
                full_path = allowlist.get(rel)
                if full_path is not None and full_path.is_file():
                    ext = full_path.suffix.lower()
                    ct = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                        ".svg": "image/svg+xml",
                    }.get(ext, "application/octet-stream")
                    try:
                        data = full_path.read_bytes()
                    except OSError:
                        self._send(404, b"Not found")
                        return
                    # 直接開かれた SVG 内の script を同一オリジンで走らせない
                    self._send(200, data, ct, {"Content-Security-Policy": "sandbox"})
                else:
                    self._send(404, b"Not found")
            else:
                self._send(404, b"Not found")

        def do_POST(self):
            if self.path != "/submit":
                self._send(404, b"Not found")
                return
            if not self._token_ok(self.headers.get("X-Review-Token")):
                self._send(403, b"Forbidden: token required")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(400, b"Bad request: invalid Content-Length")
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError):
                self._send(400, b"Bad request: invalid JSON")
                return
            problem = validate_submission(body, expected_ids)
            if problem:
                self._send(400, f"Bad request: {problem}".encode("utf-8"))
                return

            # 書き戻すのは契約どおりのキーだけ (id / status、rejected のみ comment)
            review_data["results"] = [
                {"id": r["id"], "status": r["status"],
                 **({"comment": r["comment"].strip()} if r["status"] == "rejected" else {})}
                for r in body["items"]
            ]
            try:
                review_path.write_text(
                    json.dumps(review_data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as e:
                review_data.pop("results", None)
                self._send(500, b"Failed to write review file (see server log)")
                print(f"WRITE FAILED: {review_path}: {e}", file=sys.stderr)
                return

            # 書き込み済みなので、応答送信に失敗しても報告と停止は必ず行う
            approved = sum(1 for r in body["items"] if r["status"] == "approved")
            rejected = sum(1 for r in body["items"] if r["status"] == "rejected")
            print(f"SUBMITTED: {review_path} (approved={approved}, rejected={rejected})")
            sys.stdout.flush()
            try:
                self._send(200, b'{"ok":true}', "application/json")
            finally:
                Thread(target=lambda: server_ref[0].shutdown(), daemon=True).start()

    return Handler


def build_server(review_path: Path, host: str, port: int, base_dir: Path | None = None):
    """サーバーを構築して (httpd, token) を返す。serve_forever は呼び出し側。"""
    review_data = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(review_data, dict):
        raise ValueError("review.json: top level must be an object")
    items = review_data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("review.json: items must be a non-empty list")
    ids = [item.get("id") if isinstance(item, dict) else None for item in items]
    if any(not isinstance(i, str) or not i for i in ids):
        raise ValueError("review.json: every item needs a non-empty string id")
    if len(set(ids)) != len(ids):
        raise ValueError("review.json: item ids must be unique")
    base = base_dir if base_dir is not None else resolve_base_dir()
    allowlist = build_allowlist(review_data["items"], base)
    token = secrets.token_urlsafe(16)
    server_ref: list = [None]
    # bind に失敗する起動 (ポート使用中等) が前回 results を消さないよう、書き戻しより先に構築する
    httpd = HTTPServer(
        (host, port),
        make_handler(review_data, review_path, server_ref, token, allowlist),
    )
    server_ref[0] = httpd
    if "results" in review_data:
        # 前回の結果が今回の結果として読まれないよう、起動時に消してファイルにも反映する
        review_data.pop("results")
        try:
            review_path.write_text(
                json.dumps(review_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
        except OSError:
            httpd.server_close()
            raise
    return httpd, token


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <review.json> [port]", file=sys.stderr)
        sys.exit(1)

    review_path = Path(sys.argv[1])
    host = os.environ.get("UI_APPROVAL_HOST", "0.0.0.0")

    try:
        port = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.environ.get("UI_APPROVAL_PORT", "8786"))
        httpd, token = build_server(review_path, host, port)
    except (OSError, ValueError) as e:
        print(f"起動できません: {e}", file=sys.stderr)
        sys.exit(1)

    all_nics = host in ("", "0.0.0.0")
    url_host = get_lan_ip() if all_nics else host
    print(f"UI 承認レビューサーバー起動: http://{url_host}:{httpd.server_address[1]}/?t={token}")
    print(f"レビュー対象: {review_path}")
    bind_note = "全 NIC に bind" if all_nics else f"{host} に bind"
    print(f"  ※ {bind_note} ({host}:{httpd.server_address[1]})。信頼できる LAN でのみ使用してください")
    print("  ※ URL の ?t= トークンが無いと 403 になります。上の URL をそのまま開いてください")
    sys.stdout.flush()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    main()
