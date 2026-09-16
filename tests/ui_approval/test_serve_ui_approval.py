"""skills/global/ui-approval/serve-ui-approval.py の回帰テスト。

stdlib のみで動く。127.0.0.1 の空きポートで実サーバーを起動し HTTP で叩く。
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "global" / "ui-approval" / "serve-ui-approval.py"


def load_module():
    spec = importlib.util.spec_from_file_location("serve_ui_approval", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "repo"
        (self.base / "docs" / "images").mkdir(parents=True)
        self.img = self.base / "docs" / "images" / "a.png"
        self.img.write_bytes(b"\x89PNG-fake-a")
        (self.base / "docs" / "images" / "画面 1.png").write_bytes(b"\x89PNG-fake-jp")
        (self.base / "docs" / "images" / "b.png").write_bytes(b"\x89PNG-fake-b")
        # base の外に実在ファイルを置き、traversal で届かないことを確かめる
        self.outside = Path(self.tmp.name) / "secret.txt"
        self.outside.write_text("SECRET", encoding="utf-8")
        self.review = self.base / "review.json"
        self.review.write_text(json.dumps({
            "title": "T <b>x</b>",
            "items": [
                {"id": "s1", "label": "L1", "image_path": "docs/images/a.png",
                 "description": "desc</script><!--<script><img src=x onerror=alert(1)>",
                 "design_rationale": "r"},
                {"id": "s2", "label": "L2", "image_path": "docs/images/b.png",
                 "description": "d2"},
                {"id": "s3", "label": "L3", "image_path": "docs/images/画面 1.png",
                 "description": "d3"},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        self.httpd, self.token = self.mod.build_server(self.review, "127.0.0.1", 0, base_dir=self.base)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    # --- GET / ---
    def test_index_renders_with_token(self):
        status, data = self.req("GET", f"/?t={self.token}")
        self.assertEqual(status, 200)
        page = data.decode("utf-8")
        self.assertIn("<title>T &lt;b&gt;x&lt;/b&gt;</title>", page)
        self.assertIn("box-sizing: border-box", page)          # CSS がそのまま出ている
        self.assertNotIn("__ITEMS_JSON__", page)
        self.assertIn('"id": "s1"', page)
        self.assertIn("desc<\\/script><\\!--<script>", page)     # </script> と <!-- の混入で崩れない
        self.assertNotIn("desc</script>", page)
        self.assertNotIn("<!--<script>", page)

    def test_index_placeholder_strings_in_data_are_not_expanded(self):
        data = {"title": "__ITEMS_JSON__ and __TOKEN_JSON__", "items": [{"id": "a", "image_path": "x"}]}
        page = self.mod.render_html(data, "tok")
        self.assertIn("<title>__ITEMS_JSON__ and __TOKEN_JSON__</title>", page)
        self.assertIn('const token = "tok";', page)

    def test_index_null_title_falls_back(self):
        page = self.mod.render_html({"title": None, "items": []}, "tok")
        self.assertIn("<title>UI 承認レビュー</title>", page)

    def test_responses_carry_cache_and_sniff_headers(self):
        for path in (f"/?t={self.token}", f"/image/docs%2Fimages%2Fa.png?t={self.token}", "/"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse(); resp.read(); conn.close()
            self.assertEqual(resp.getheader("Cache-Control"), "no-store", path)
            self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(resp.getheader("Referrer-Policy"), "no-referrer", path)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", f"/image/docs%2Fimages%2Fa.png?t={self.token}")
        resp = conn.getresponse(); resp.read(); conn.close()
        self.assertEqual(resp.getheader("Content-Security-Policy"), "sandbox")

    def test_index_without_token_is_403(self):
        self.assertEqual(self.req("GET", "/")[0], 403)
        self.assertEqual(self.req("GET", "/?t=wrong")[0], 403)

    def test_non_ascii_token_is_403_not_crash(self):
        self.assertEqual(self.req("GET", "/?t=%E3%81%82")[0], 403)
        status, _ = self.req("POST", "/submit", body=b"{}", headers={"X-Review-Token": "\xe9"})
        self.assertEqual(status, 403)

    def test_inline_handlers_are_not_used(self):
        # onclick="setStatus("s1"...)" のような属性崩れの退行を防ぐ
        status, data = self.req("GET", f"/?t={self.token}")
        page = data.decode("utf-8")
        self.assertNotIn("onclick=\"setStatus", page)
        self.assertNotIn("oninput=", page)
        self.assertIn("addEventListener('click'", page)

    # --- GET /image ---
    def test_image_allowlisted_path_is_served(self):
        status, data = self.req("GET", f"/image/docs%2Fimages%2Fa.png?t={self.token}")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"\x89PNG-fake-a")

    def test_image_without_token_is_403(self):
        self.assertEqual(self.req("GET", "/image/docs%2Fimages%2Fa.png")[0], 403)
        self.assertEqual(self.req("GET", "/image/docs%2Fimages%2Fa.png?t=wrong")[0], 403)

    def test_image_absolute_path_is_404(self):
        self.assertTrue(self.outside.is_file())
        status, data = self.req("GET", "/image/" + str(self.outside) + f"?t={self.token}")
        self.assertEqual(status, 404)
        self.assertNotIn(b"SECRET", data)
        status, data = self.req("GET", f"/image//etc/passwd?t={self.token}")
        self.assertEqual(status, 404)
        self.assertNotIn(b"root:", data)

    def test_image_traversal_is_404(self):
        # base/docs/images/../../../secret.txt は実在するが allowlist に無い
        status, data = self.req("GET", f"/image/docs%2Fimages%2F..%2F..%2F..%2Fsecret.txt?t={self.token}")
        self.assertEqual(status, 404)
        self.assertNotIn(b"SECRET", data)

    def test_image_non_ascii_path_is_served(self):
        status, data = self.req("GET", f"/image/docs%2Fimages%2F%E7%94%BB%E9%9D%A2%201.png?t={self.token}")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"\x89PNG-fake-jp")

    def test_image_deleted_after_startup_is_404(self):
        (self.base / "docs" / "images" / "b.png").unlink()
        self.assertEqual(self.req("GET", f"/image/docs%2Fimages%2Fb.png?t={self.token}")[0], 404)

    # --- POST /submit ---
    def submit(self, payload, token=None, raw=None):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Review-Token"] = token
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        return self.req("POST", "/submit", body=body, headers=headers)

    def valid_payload(self):
        return {"items": [{"id": "s1", "status": "approved", "comment": "stale", "junk": {"z": 1}},
                          {"id": "s2", "status": "rejected", "comment": " 改行\n<b>を含む "},
                          {"id": "s3", "status": "approved"}]}

    def test_submit_without_token_is_403_and_file_unchanged(self):
        before = self.review.read_text(encoding="utf-8")
        status, _ = self.submit(self.valid_payload())
        self.assertEqual(status, 403)
        self.assertEqual(self.review.read_text(encoding="utf-8"), before)
        self.assertNotIn("results", json.loads(before))

    def test_submit_invalid_json_is_400(self):
        status, _ = self.submit(None, token=self.token, raw=b"{not json")
        self.assertEqual(status, 400)

    def test_submit_bad_content_length_is_400(self):
        for cl in ("-1", "abc", str(self.mod.MAX_BODY_BYTES + 1)):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.putrequest("POST", "/submit")
            conn.putheader("X-Review-Token", self.token)
            conn.putheader("Content-Length", cl)
            conn.endheaders()
            resp = conn.getresponse()
            self.assertEqual(resp.status, 400, cl)
            resp.read()
            conn.close()

    def test_submit_id_mismatch_is_400(self):
        cases = [
            {"items": [{"id": "s1", "status": "approved"},
                       {"id": "s2", "status": "approved"}]},                      # s3 欠落
            {"items": [{"id": "s1", "status": "approved"},
                       {"id": "s2", "status": "approved"},
                       {"id": "zzz", "status": "approved"}]},                     # 未知 id
            {"items": [{"id": "s1", "status": "approved"},
                       {"id": "s1", "status": "approved"},
                       {"id": "s3", "status": "approved"}]},                      # 重複
            {"items": [{"id": "s1", "status": "ok"},
                       {"id": "s2", "status": "approved"},
                       {"id": "s3", "status": "approved"}]},                      # 不正 status
            {"items": "approved"},                                                # 型不正
            {"items": []},                                                        # 空
            {"items": [{"id": "s1", "status": "rejected"},
                       {"id": "s2", "status": "approved"},
                       {"id": "s3", "status": "approved"}]},                      # 指摘にコメント無し
            {"items": [{"id": "s1", "status": "rejected", "comment": "  "},
                       {"id": "s2", "status": "approved"},
                       {"id": "s3", "status": "approved"}]},                      # 空白のみ
        ]
        for payload in cases:
            status, _ = self.submit(payload, token=self.token)
            self.assertEqual(status, 400, payload)
        self.assertNotIn("results", json.loads(self.review.read_text(encoding="utf-8")))

    def test_submit_valid_writes_results_and_shuts_down(self):
        status, data = self.submit(self.valid_payload(), token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"ok": True})
        written = json.loads(self.review.read_text(encoding="utf-8"))
        self.assertEqual(written["results"], [                    # 契約どおりのキーに正規化される
            {"id": "s1", "status": "approved"},
            {"id": "s2", "status": "rejected", "comment": "改行\n<b>を含む"},
            {"id": "s3", "status": "approved"}])
        self.assertEqual(len(written["items"]), 3)                # items は温存
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())                  # 送信後にサーバーが止まる
        self.httpd.server_close()                                 # main() と同じく serve_forever 後に閉じる
        with self.assertRaises(ConnectionRefusedError):           # 停止後の再送は接続拒否
            self.submit(self.valid_payload(), token=self.token)

    @unittest.skipIf(os.geteuid() == 0, "root は読み取り専用ファイルにも書けるため検証不能")
    def test_submit_write_failure_is_500_and_server_keeps_running(self):
        self.review.chmod(0o444)
        try:
            status, data = self.submit(self.valid_payload(), token=self.token)
        finally:
            self.review.chmod(0o644)
        self.assertEqual(status, 500)
        self.assertIn(b"Failed to write", data)
        self.assertNotIn(str(self.review).encode(), data)         # パスは本文に出さない
        self.assertNotIn("results", json.loads(self.review.read_text(encoding="utf-8")))
        self.assertTrue(self.thread.is_alive())                   # 止まらず再送を待つ
        status, _ = self.submit(self.valid_payload(), token=self.token)   # 原因解消後の再送で成功
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(self.review.read_text(encoding="utf-8"))["results"]), 3)
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())


class PureFunctionTestCase(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def _build(self, items, top=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "a.png").write_bytes(b"a")
        path = Path(tmp.name) / "review.json"
        path.write_text(json.dumps({"items": items} if top is None else top), encoding="utf-8")
        return self.mod.build_server(path, "127.0.0.1", 0, base_dir=Path(tmp.name))

    def test_build_server_rejects_bad_review_json(self):
        for items in ([], "x", [{"id": "a"}, {"id": "a"}], [{"label": "no id"}], [{"id": ""}]):
            with self.assertRaises(ValueError, msg=repr(items)):
                self._build(items)
        with self.assertRaises(ValueError):
            self._build(None, top=[])          # 最上位が list
        httpd, token = self._build([{"id": "a", "image_path": "a.png"}])
        httpd.server_close()
        self.assertTrue(token)

    def test_build_allowlist_rejects_absolute_missing_and_escaping_paths(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name) / "base"
        base.mkdir()
        (base / "a.png").write_bytes(b"a")
        (base / "b.png").write_bytes(b"b")
        allow = self.mod.build_allowlist([{"image_path": "a.png"}, {"image_path": "./sub/../b.png"}], base)
        self.assertEqual(allow, {"a.png": (base / "a.png").resolve(),
                                 "./sub/../b.png": (base / "b.png").resolve()})
        (Path(tmp.name) / "outside.txt").write_bytes(b"o")
        for bad in ({"id": "x", "image_path": "/etc/passwd"}, {"id": "x", "image_path": 3},
                    {"id": "x"}, {"id": "x", "image_path": ""}, {"id": "x", "image_path": "../outside.txt"},
                    {"id": "x", "image_path": "nope.png"}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.mod.build_allowlist([bad], base)

    def test_build_server_drops_stale_results_from_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "review.json"
        (Path(tmp.name) / "a.png").write_bytes(b"a")
        path.write_text(json.dumps({"items": [{"id": "a", "image_path": "a.png"}],
                                    "results": [{"id": "a", "status": "approved"}]}), encoding="utf-8")
        httpd, _ = self.mod.build_server(path, "127.0.0.1", 0, base_dir=Path(tmp.name))
        httpd.server_close()
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("results", written)
        self.assertEqual(written["items"][0]["id"], "a")

    def test_resolve_base_dir_git_toplevel_and_fallback(self):
        import subprocess
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        repo = Path(tmp.name) / "repo"
        (repo / "sub").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        # TMPDIR がリポ内にある環境でも fallback 側の前提 (git 管理外) が崩れないよう探索の上限を固定
        os.environ["GIT_CEILING_DIRECTORIES"] = tmp.name
        self.addCleanup(os.environ.pop, "GIT_CEILING_DIRECTORIES", None)
        os.chdir(repo / "sub")
        self.assertEqual(self.mod.resolve_base_dir(), repo.resolve())
        plain = Path(tmp.name) / "plain"
        plain.mkdir()
        os.chdir(plain)
        self.assertEqual(self.mod.resolve_base_dir(), plain.resolve())

    def test_validate_submission(self):
        v = self.mod.validate_submission
        self.assertIsNone(v({"items": [{"id": "a", "status": "approved"}]}, {"a"}))
        self.assertIsNone(v({"items": [{"id": "a", "status": "rejected", "comment": "x"}]}, {"a"}))
        self.assertIn("needs a comment", v({"items": [{"id": "a", "status": "rejected"}]}, {"a"}))
        self.assertIn("comment must be a string", v({"items": [{"id": "a", "status": "approved", "comment": 1}]}, {"a"}))
        self.assertIn("ids do not match", v({"items": []}, {"a"}))
        self.assertIn("items must be a list", v([], {"a"}))
        self.assertIn("unknown id", v({"items": [{"id": "zz", "status": "approved"}]}, {"a"}))
        self.assertIn("invalid status", v({"items": [{"id": "a", "status": "ok"}]}, {"a"}))


if __name__ == "__main__":
    unittest.main()
