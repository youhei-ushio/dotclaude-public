#!/bin/bash
# skills/global/ui-approval/serve-ui-approval.py の回帰テスト。
#
# 実行: bash tests/test_ui_approval_server.sh
# 前提: python3 のみ (stdlib で完結。venv 不要)。google-chrome があれば描画・操作の検査も走る (無ければ SKIP)
#
# 検査の要点:
#   1. GET / がトークン付きで描画される (CSS の {} と .format の衝突で KeyError にならない)
#   2. GET / と POST /submit はトークン無しで 403 (非 ASCII トークンも 403、例外にしない)
#   3. /image は allowlist 完全一致のみ配信。絶対パス・.. traversal は 404 (base 外の実在ファイルで確認)
#   4. /submit は id 集合・status・型を検証し不正は 400。正常時は results を書き戻して停止する
#   5. [chrome] 実クリックで承認 / 指摘 / コメント入力が results に反映され、進捗と送信ボタンが更新される。
#      画像が実際にロードされる (inline handler の引用符崩れで操作不能になる退行の防止)
#   6. [chrome] 送信ボタンの実クリック → 送信完了画面 → review.json に results → サーバー停止。
#      同一オリジンで POST を通すため tests/ui_approval/inject_proxy.py を挟む

HERE="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$HERE/skills/global/ui-approval/serve-ui-approval.py"
PROXY="$HERE/tests/ui_approval/inject_proxy.py"
FAIL=0

# --- 1-4: unittest ---
# 期待するテスト数の下限。テストファイルが丸ごと消えて 0 件 PASS になるのを緑にしない
MIN_TESTS=24
OUT="$(cd "$HERE" && python3 -m unittest -v tests.ui_approval.test_serve_ui_approval 2>&1)"
RC=$?
echo "$OUT" | tail -5
RAN="$(echo "$OUT" | grep -Eo '^Ran [0-9]+ test' | grep -Eo '[0-9]+')"
if [ "$RC" -ne 0 ]; then
    echo "[FAIL] unittest rc=$RC"
    FAIL=$((FAIL + 1))
elif [ -z "$RAN" ] || [ "$RAN" -lt "$MIN_TESTS" ]; then
    echo "[FAIL] ran=${RAN:-0} < MIN_TESTS=$MIN_TESTS"
    FAIL=$((FAIL + 1))
else
    echo "[PASS] unittest: $RAN tests"
fi

CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
if [ -z "$CHROME" ]; then
    echo "[SKIP] chrome: google-chrome / chromium が無い"
    if [ "$FAIL" -eq 0 ]; then echo "PASS: all"; exit 0; else echo "FAIL: $FAIL"; exit 1; fi
fi

WORK="$(mktemp -d)"
SERVER_PID=""
PROXY_PID=""
trap '[ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null; [ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/repo/docs/images"
git init -q "$WORK/repo"
# 1x1 の実 PNG (naturalWidth > 0 を見るため)
python3 - "$WORK/repo/docs/images/a.png" <<'PY'
import sys, zlib, struct
def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
raw = b"\x00\xff\x00\x00\xff"
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
open(sys.argv[1], "wb").write(png)
PY
cp "$WORK/repo/docs/images/a.png" "$WORK/repo/docs/images/b.png"
cp "$WORK/repo/docs/images/a.png" "$WORK/repo/docs/images/c.png"
python3 - "$WORK/repo/review.json" <<'PY'
import sys, json
json.dump({"title": "chrome <b>", "items": [
    {"id": "s1", "label": 'L1" data-x="pwn', "image_path": "docs/images/a.png", "description": "d1</script>", "design_rationale": "r1"},
    {"id": "s2", "label": "L2", "image_path": "docs/images/b.png", "description": "d2"},
    {"id": "s3", "label": "L3", "image_path": "docs/images/c.png", "description": "d3"},
]}, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
PY
cp "$WORK/repo/review.json" "$WORK/repo/review6.json"

free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'; }
# start_server <review.json 名> <port> <log> → SERVER_PID と URL_OUT を設定する
# ($(...) で呼ぶと subshell になり SERVER_PID が親に残らないので、必ず直接呼ぶ)
start_server() {
    (cd "$WORK/repo" && exec env UI_APPROVAL_HOST=127.0.0.1 python3 "$SCRIPT" "$1" "$2" > "$3" 2>&1) &
    SERVER_PID=$!
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do grep -q '?t=' "$3" 2>/dev/null && break; sleep 0.3; done
    URL_OUT="$(grep -o 'http://[^ ]*' "$3" | head -1)"
}
# dom_state <dom.html> → <title> に書かれた JSON を stdout へ (無ければ空)
dom_state() {
    python3 - "$1" <<'PY'
import sys, re, html
d = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"<title>(.*?)</title>", d, re.S)
print(html.unescape(m.group(1)) if m else "")
PY
}

# --- 5: 描画と操作 (file:// + <base> でサーバーの画像を参照) ---
PORT=$(free_port)
start_server review.json "$PORT" "$WORK/server.log"; URL="$URL_OUT"
if [ -z "$URL" ]; then
    echo "[FAIL] chrome: サーバーが起動しない"; cat "$WORK/server.log"; FAIL=$((FAIL + 1))
else
    case "$URL" in http://127.0.0.1:*) echo "[PASS] chrome: stdout URL が bind host を使う";;
        *) echo "[FAIL] chrome: stdout URL が bind host と違う: $URL"; FAIL=$((FAIL + 1));; esac
    curl -s "$URL" > "$WORK/page.html"
    python3 - "$WORK/page.html" "http://127.0.0.1:$PORT/" <<'PY'
import sys
path, base = sys.argv[1], sys.argv[2]
h = open(path, encoding="utf-8").read()
h = h.replace("<head>", f'<head><base href="{base}">', 1)
scenario = """
<script>
(function () {
  const q = (id, sel) => document.getElementById('card-' + id).querySelector(sel);
  const btnState = () => document.getElementById('submitBtn').textContent.trim();
  const summary = () => document.getElementById('summary').textContent;
  q('s1', '.btn-approve').click();
  const midText = btnState();                      // 途中: 残り 2 件
  q('s2', '.btn-reject').click();
  q('s3', '.btn-reject').click();
  const gateText = btnState();                     // 全件済みだが s2/s3 のコメント未記入 → 送信不可
  const ta3 = q('s3', 'textarea'); ta3.value = '   '; ta3.dispatchEvent(new Event('input'));
  const gateTextWs = btnState();                   // 空白のみは未記入扱い
  const ta = q('s2', 'textarea'); ta.value = 'コメント<b>'; ta.dispatchEvent(new Event('input'));
  const summaryRejected = summary();
  q('s3', '.btn-approve').click();                 // 取消: s3 は approved に戻る
  q('s2', '.btn-approve').click();                 // 取消→再指摘でコメントが残るか
  q('s2', '.btn-reject').click();
  const img = document.querySelector('#card-s1 img');
  const imgs = Array.from(document.querySelectorAll('.card img'));
  const done = () => {
    document.title = JSON.stringify({
      imgSrcs: imgs.map(i => i.getAttribute('src').split('?')[0]),
      allImgsLoaded: imgs.every(i => i.complete && i.naturalWidth > 0),
      rationaleS1: !!document.querySelector('#card-s1 .rationale'),
      rationaleS2: !!document.querySelector('#card-s2 .rationale'),
      results, progress: document.getElementById('progress').textContent,
      gateText, gateTextWs, midText, summaryRejected, summaryFinal: summary(),
      btnDisabled: document.getElementById('submitBtn').disabled,
      btnText: btnState(),
      s2box: q('s2', '.comment-box').className, s3box: q('s3', '.comment-box').className,
      s2text: q('s2', 'textarea').value,
      imgLoaded: img.complete && img.naturalWidth > 0,
      imgSrcHasToken: img.getAttribute('src').includes('?t='),
      altBreakout: img.hasAttribute('data-x'),
      altValue: img.getAttribute('alt'),
      desc: q('s1', '.desc').textContent,
    });
  };
  const pending = imgs.filter(i => !i.complete);
  if (pending.length === 0) done(); else { let n = pending.length; pending.forEach(i => { i.onload = i.onerror = () => { if (--n === 0) done(); }; }); }
})();
</script>
"""
h = h.replace("</body>", scenario + "</body>", 1)
open(path, "w", encoding="utf-8").write(h)
PY
    timeout 60 "$CHROME" --headless=new --disable-gpu --no-sandbox --virtual-time-budget=5000 \
        --dump-dom "file://$WORK/page.html" > "$WORK/dom.html" 2>/dev/null
    dom_state "$WORK/dom.html" > "$WORK/state5.json"
    if python3 - "$WORK/state5.json" "$WORK/dom.html" <<'PY'
import sys, json
raw = open(sys.argv[1], encoding="utf-8").read().strip()
d = open(sys.argv[2], encoding="utf-8").read()
try:
    state = json.loads(raw)
except Exception:
    print("NG: シナリオが最後まで走っていない (title が JSON でない):", repr(raw)[:80]); sys.exit(1)
# results はブラウザ内の状態。s3 は取消後もコメント (空白) を保持するが、送信 payload には status が rejected のときだけ付く (シナリオ 6 で確認)
exp = {"s1": {"status": "approved"},
       "s2": {"status": "rejected", "comment": "コメント<b>"},
       "s3": {"status": "approved", "comment": "   "}}
checks = {
  "results": state["results"] == exp,
  "progress 3/3": state["progress"] == "3 / 3 件レビュー済み",
  "gate blocks missing comments": state["gateText"] == "指摘のコメント未記入が 2 件あります",
  "whitespace-only comment still missing": state["gateTextWs"] == "指摘のコメント未記入が 2 件あります",
  "mid progress text": state["midText"] == "全項目レビュー後に送信可能（残り 2 件）",
  "summary with rejected": state["summaryRejected"] == "指摘がある項目は修正後に再レビューされます",
  "summary final (1 rejected)": state["summaryFinal"] == "指摘がある項目は修正後に再レビューされます",
  "submit enabled": state["btnDisabled"] is False,
  "submit text": state["btnText"] == "送信（承認: 2 件 / 指摘: 1 件）",
  "s2 comment box shown": "hidden" not in state["s2box"],
  "s3 comment box hidden": "hidden" in state["s3box"],
  "s2 comment kept after re-reject": state["s2text"] == "コメント<b>",
  "img loaded": state["imgLoaded"] is True,
  "each card has its own image": state["imgSrcs"] == ["/image/docs%2Fimages%2Fa.png", "/image/docs%2Fimages%2Fb.png", "/image/docs%2Fimages%2Fc.png"],
  "all images loaded": state["allImgsLoaded"] is True,
  "rationale shown only when present": state["rationaleS1"] is True and state["rationaleS2"] is False,
  "img src has token": state["imgSrcHasToken"] is True,
  "alt not broken out": state["altBreakout"] is False and state["altValue"] == 'L1" data-x="pwn',
  "desc escaped": state["desc"] == "d1</script>",
  "no inline handler": 'onclick="setStatus(' not in d,
}
bad = [k for k, v in checks.items() if not v]
if bad:
    print("NG:", bad); print(json.dumps(state, ensure_ascii=False)); sys.exit(1)
PY
    then echo "[PASS] chrome: クリック操作・進捗・画像ロード"
    else echo "[FAIL] chrome: 操作シナリオ"; FAIL=$((FAIL + 1))
    fi
    kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; SERVER_PID=""
fi

# --- 6: 送信実クリック (注入プロキシで同一オリジン化) ---
PORT6=$(free_port)
PPORT=$(free_port)
start_server review6.json "$PORT6" "$WORK/server6.log"; URL6="$URL_OUT"
if [ -z "$URL6" ]; then
    echo "[FAIL] chrome: サーバー (6) が起動しない"; cat "$WORK/server6.log"; FAIL=$((FAIL + 1))
else
    TOKEN6="${URL6#*t=}"
    python3 - "$WORK/scenario6.html" <<'PY'
import sys
open(sys.argv[1], "w", encoding="utf-8").write("""
<script>
(function () {
  const q = (id, sel) => document.getElementById('card-' + id).querySelector(sel);
  q('s1', '.btn-approve').click();
  q('s2', '.btn-reject').click();
  const ta = q('s2', 'textarea'); ta.value = ' 直して '; ta.dispatchEvent(new Event('input'));
  q('s3', '.btn-approve').click();
  const btn = document.getElementById('submitBtn');
  btn.click();
  const disabledRightAfter = btn.disabled;
  btn.click();   // 二重クリックは無視される
  const wait = () => {
    if (document.body.textContent.includes('送信完了')) {
      document.title = JSON.stringify({ done: true, disabledRightAfter });
    } else { setTimeout(wait, 50); }
  };
  wait();
})();
</script>
""")
PY
    python3 "$PROXY" "$PPORT" "$PORT6" "$WORK/scenario6.html" > "$WORK/proxy.log" 2>&1 &
    PROXY_PID=$!
    for _ in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null "http://127.0.0.1:$PPORT/?t=x" && break; sleep 0.3; done
    timeout 60 "$CHROME" --headless=new --disable-gpu --no-sandbox --virtual-time-budget=10000 \
        --dump-dom "http://127.0.0.1:$PPORT/?t=$TOKEN6" > "$WORK/dom6.html" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$SERVER_PID" 2>/dev/null || break; sleep 0.3; done
    dom_state "$WORK/dom6.html" > "$WORK/state6.json"
    if python3 - "$WORK/state6.json" "$WORK/repo/review6.json" "$WORK/server6.log" <<'PY'
import sys, json
raw = open(sys.argv[1], encoding="utf-8").read().strip()
try:
    state = json.loads(raw)
except Exception:
    print("NG: 送信完了まで到達していない:", repr(raw)[:80]); sys.exit(1)
written = json.load(open(sys.argv[2], encoding="utf-8"))
log = open(sys.argv[3], encoding="utf-8").read()
checks = {
  "送信完了画面": state.get("done") is True,
  "クリック直後に disabled": state.get("disabledRightAfter") is True,
  "results 書き戻し (trim 済コメント)": written.get("results") == [
      {"id": "s1", "status": "approved"},
      {"id": "s2", "status": "rejected", "comment": "直して"},
      {"id": "s3", "status": "approved"}],
  "SUBMITTED は 1 行": log.count("SUBMITTED:") == 1,
}
bad = [k for k, v in checks.items() if not v]
if bad:
    print("NG:", bad, json.dumps(state, ensure_ascii=False), written.get("results")); sys.exit(1)
PY
    then echo "[PASS] chrome: 送信実クリック → 送信完了 → results 書き戻し"
    else echo "[FAIL] chrome: 送信実クリック"; FAIL=$((FAIL + 1))
    fi
    if [ -z "$SERVER_PID" ]; then
        echo "[FAIL] chrome: SERVER_PID が空 (テスト側の不備)"; FAIL=$((FAIL + 1))
    elif kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "[FAIL] chrome: 送信後にサーバーが停止していない"; FAIL=$((FAIL + 1)); kill "$SERVER_PID" 2>/dev/null
    else
        echo "[PASS] chrome: 送信後にサーバーが停止 (pid $SERVER_PID)"
    fi
    SERVER_PID=""
    kill "$PROXY_PID" 2>/dev/null; PROXY_PID=""
fi

if [ "$FAIL" -eq 0 ]; then echo "PASS: all"; exit 0; else echo "FAIL: $FAIL"; exit 1; fi
