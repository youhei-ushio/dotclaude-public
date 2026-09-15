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

送信後、review.json に results を書き戻して exit 0 する。
"""

from __future__ import annotations

import json
import os
import socket
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.parse import unquote

def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
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
<h1>{title}</h1>
<div class="progress" id="progress"></div>

<div id="cards"></div>

<div class="summary" id="summary"></div>
<div class="submit-bar">
  <button class="btn btn-submit" id="submitBtn" disabled onclick="submitResults()">
    全項目レビュー後に送信可能
  </button>
</div>

<script>
const items = {items_json};
const results = {{}};

function renderCards() {{
  const container = document.getElementById('cards');
  container.innerHTML = '';
  items.forEach((item, idx) => {{
    const card = document.createElement('div');
    card.className = 'card';
    card.id = 'card-' + item.id;

    const statusBadge = results[item.id]
      ? `<span class="status-badge ${{results[item.id].status === 'approved' ? 'status-approved' : 'status-rejected'}}">${{results[item.id].status === 'approved' ? '✓ 承認' : '✎ 指摘あり'}}</span>`
      : '';

    card.innerHTML = `
      <div class="card-header">
        <h2>${{idx + 1}}. ${{item.label}} ${{statusBadge}}</h2>
        <div class="desc">${{item.description}}</div>
        ${{item.design_rationale ? `<div class="rationale">設計根拠: ${{item.design_rationale}}</div>` : ''}}
      </div>
      <div class="card-image">
        <img src="/image/${{encodeURIComponent(item.image_path)}}" alt="${{item.label}}" loading="lazy">
      </div>
      <div class="card-actions">
        <button class="btn btn-approve ${{results[item.id]?.status === 'approved' ? 'active' : ''}}"
                onclick="setStatus('${{item.id}}', 'approved')">✓ 承認</button>
        <button class="btn btn-reject ${{results[item.id]?.status === 'rejected' ? 'active' : ''}}"
                onclick="setStatus('${{item.id}}', 'rejected')">✎ 指摘</button>
        <div class="comment-box ${{results[item.id]?.status === 'rejected' ? '' : 'hidden'}}" id="comment-${{item.id}}">
          <textarea placeholder="修正内容を記入..."
                    oninput="updateComment('${{item.id}}', this.value)"
          >${{results[item.id]?.comment || ''}}</textarea>
        </div>
      </div>
    `;
    container.appendChild(card);
  }});
  updateProgress();
}}

function setStatus(id, status) {{
  if (!results[id]) results[id] = {{}};
  results[id].status = status;
  const commentBox = document.getElementById('comment-' + id);
  if (status === 'rejected') {{
    commentBox.classList.remove('hidden');
    commentBox.querySelector('textarea').focus();
  }} else {{
    commentBox.classList.add('hidden');
    results[id].comment = '';
  }}
  renderCards();
}}

function updateComment(id, value) {{
  if (!results[id]) results[id] = {{}};
  results[id].comment = value;
}}

function updateProgress() {{
  const total = items.length;
  const done = Object.keys(results).length;
  const approved = Object.values(results).filter(r => r.status === 'approved').length;
  const rejected = Object.values(results).filter(r => r.status === 'rejected').length;

  document.getElementById('progress').textContent =
    `${{done}} / ${{total}} 件レビュー済み`;

  const btn = document.getElementById('submitBtn');
  if (done === total) {{
    btn.disabled = false;
    btn.textContent = `送信（承認: ${{approved}} 件 / 指摘: ${{rejected}} 件）`;
  }} else {{
    btn.disabled = true;
    btn.textContent = `全項目レビュー後に送信可能（残り ${{total - done}} 件）`;
  }}

  document.getElementById('summary').textContent =
    done === total ? (rejected > 0 ? '指摘がある項目は修正後に再レビューされます' : '全件承認です') : '';
}}

async function submitResults() {{
  const payload = items.map(item => ({{
    id: item.id,
    status: results[item.id].status,
    ...(results[item.id].comment ? {{ comment: results[item.id].comment }} : {{}})
  }}));

  const res = await fetch('/submit', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ items: payload }})
  }});

  if (res.ok) {{
    document.body.innerHTML = '<h1 style="text-align:center;margin-top:40vh;color:#4caf50">送信完了 ✓</h1><p style="text-align:center;color:#666">このタブを閉じてください</p>';
  }}
}}

renderCards();
</script>
</body>
</html>"""


def make_handler(review_data: dict, review_path: Path, server_ref: list):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                html = HTML_TEMPLATE.format(
                    title=review_data.get("title", "UI 承認レビュー"),
                    items_json=json.dumps(review_data["items"], ensure_ascii=False),
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode())
            elif self.path.startswith("/image/"):
                img_path = unquote(self.path[7:])
                full_path = Path(img_path)
                if not full_path.is_absolute():
                    full_path = Path.cwd() / full_path
                if full_path.is_file():
                    ext = full_path.suffix.lower()
                    ct = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                        ".svg": "image/svg+xml",
                    }.get(ext, "application/octet-stream")
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.end_headers()
                    self.wfile.write(full_path.read_bytes())
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(f"Not found: {img_path}".encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/submit":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))

                review_data["results"] = body["items"]
                review_path.write_text(
                    json.dumps(review_data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

                approved = sum(1 for r in body["items"] if r["status"] == "approved")
                rejected = sum(1 for r in body["items"] if r["status"] == "rejected")
                print(f"SUBMITTED: {review_path} (approved={approved}, rejected={rejected})")
                sys.stdout.flush()

                Thread(target=lambda: server_ref[0].shutdown(), daemon=True).start()
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <review.json> [port]", file=sys.stderr)
        sys.exit(1)

    review_path = Path(sys.argv[1])
    port = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.environ.get("UI_APPROVAL_PORT", "8786"))

    review_data = json.loads(review_path.read_text(encoding="utf-8"))

    host = os.environ.get("UI_APPROVAL_HOST", "0.0.0.0")
    server_ref: list = [None]
    httpd = HTTPServer((host, port), make_handler(review_data, review_path, server_ref))
    server_ref[0] = httpd

    lan_ip = get_lan_ip()
    print(f"UI 承認レビューサーバー起動: http://{lan_ip}:{port}/")
    print(f"レビュー対象: {review_path}")
    print(f"  ※ 全 NIC に bind ({host}:{port})。信頼できる LAN でのみ使用してください")
    sys.stdout.flush()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    main()
