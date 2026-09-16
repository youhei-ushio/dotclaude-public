#!/usr/bin/env python3
"""テスト用の注入プロキシ (stdlib のみ)。

    python3 inject_proxy.py <listen_port> <upstream_port> <scenario_html_file>

GET / の応答 (serve-ui-approval.py の HTML) の </body> 直前に scenario_html_file の内容を
差し込んで返し、それ以外の要求 (/image, /submit) はそのまま上流へ転送する。
headless Chrome をこのプロキシ経由で開くと、注入したスクリプトと /submit が同一オリジンになり、
送信ボタンの実クリックまで検証できる (file:// 方式では CORS で POST が通らない)。
"""

from __future__ import annotations

import http.client
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LISTEN_PORT = int(sys.argv[1])
UPSTREAM_PORT = int(sys.argv[2])
SCENARIO = open(sys.argv[3], encoding="utf-8").read()

HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-length"}


class Proxy(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _forward(self, method: str):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length > 0 else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        conn = http.client.HTTPConnection("127.0.0.1", UPSTREAM_PORT, timeout=10)
        conn.request(method, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        ctype = resp.getheader("Content-Type", "")
        if method == "GET" and self.path.split("?")[0] == "/" and resp.status == 200 and "text/html" in ctype:
            data = data.decode("utf-8").replace("</body>", SCENARIO + "</body>", 1).encode("utf-8")
        self.send_response(resp.status)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", LISTEN_PORT), Proxy).serve_forever()
