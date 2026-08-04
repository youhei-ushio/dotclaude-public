#!/bin/bash
# Regression tests for skills/global/questionnaire/assets/questionnaire-template.html
#
# 実行: bash tests/test_questionnaire_template.sh
#
# テンプレートは「Claude が QUESTIONS_DATA を差し込んで生成 → 人がブラウザで回答 →
# エクスポート JSON を Claude が読み戻す」という契約を持つ。この契約 (エクスポート
# JSON のフィールドと値) が壊れると SKILL.md Step 5 / Step 7 の解釈規則が黙って
# 誤動作し、誤った内容が qa/*.md に「確定回答」として永続化される。したがって
# DOM の実挙動とエクスポート JSON を実ブラウザで検証する。
#
# headless Chrome を CDP (DevTools Protocol) で駆動する。npm 依存は使わない
# (Node 22+ 組み込みの WebSocket / fetch のみ)。node または Chrome が無い環境では
# SKIP して exit 0 (このリポは公開配布物であり、全環境で Chrome を要求しない)。
#
# 終了コード: 0 = 全 PASS または SKIP / 1 = 1 件以上 FAIL

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO_ROOT/skills/global/questionnaire/assets/questionnaire-template.html"

if [ ! -f "$TEMPLATE" ]; then
    echo "[FAIL] テンプレートが見つからない: $TEMPLATE"
    exit 1
fi

# --- 前提コマンドの解決 (無ければ SKIP) ---
if ! command -v node >/dev/null 2>&1; then
    echo "[SKIP] node が無いため headless ブラウザテストを実施しない"
    exit 0
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "$NODE_MAJOR" -lt 22 ]; then
    echo "[SKIP] node ${NODE_MAJOR}.x では組み込み WebSocket が使えない (要 22+)"
    exit 0
fi

# CHROME 環境変数で明示指定可。未指定なら既知のパスを順に探す。
if [ -z "$CHROME" ]; then
    for candidate in \
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        "/Applications/Chromium.app/Contents/MacOS/Chromium" \
        "$(command -v google-chrome 2>/dev/null)" \
        "$(command -v google-chrome-stable 2>/dev/null)" \
        "$(command -v chromium 2>/dev/null)" \
        "$(command -v chromium-browser 2>/dev/null)"
    do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            CHROME="$candidate"
            break
        fi
    done
fi

# 明示指定された CHROME が実行不能な場合もここで SKIP に落とす
if [ -z "$CHROME" ] || [ ! -x "$CHROME" ]; then
    echo "[SKIP] Chrome / Chromium が見つからないため headless ブラウザテストを実施しない"
    echo "       (CHROME=/path/to/chrome bash tests/test_questionnaire_template.sh で明示指定可)"
    exit 0
fi

CDP_PORT="${CDP_PORT:-9333}"
WORK="$(mktemp -d)"
# Chrome の終了直後はプロファイルへの書き込みが残っていて rm が競合するため、
# 少し待ってから消し、それでも残るケースは無視する (一時ディレクトリなので実害なし)。
trap 'sleep 0.5; rm -rf "$WORK" 2>/dev/null' EXIT

TEMPLATE="$TEMPLATE" WORK="$WORK" CHROME="$CHROME" CDP_PORT="$CDP_PORT" node --input-type=module <<'NODE_EOF'
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const { TEMPLATE, WORK, CHROME, CDP_PORT } = process.env;
const PORT = Number(CDP_PORT);

// 検証用のサンプル票。既定値のまま / 別選択肢 / その他 の 3 パターンと、
// カテゴリ跨ぎの連番・メタ表示・XSS を 1 票で網羅する。
const SAMPLE = {
  title: 'サンプル質問票',
  description: 'テンプレート検証用のサンプル',
  phase: 'design',
  categories: [
    {
      name: '設計判断',
      questions: [
        {
          id: 'q1',
          question: 'デフォルトのまま確定する設問',
          severity: 'major',
          problemType: '不明瞭',
          targetDoc: 'SKILL.md',
          location: 'Step 3',
          options: [
            { value: 'a', label: '選択肢A', isDefault: true, defaultReason: 'A を推奨する理由' },
            { value: 'b', label: '選択肢B', isDefault: false, defaultReason: null },
          ],
        },
        {
          id: 'q2',
          question: 'デフォルトから変更する設問',
          severity: 'critical',
          options: [
            { value: 'a', label: '選択肢A', isDefault: true, defaultReason: 'A を推奨する理由' },
            // label に生の HTML を入れ、esc() が効いていることを検証する
            { value: 'b', label: '選択肢B<script>', isDefault: false, defaultReason: null },
          ],
        },
      ],
    },
    {
      name: 'スコープ',
      questions: [
        {
          id: 'q3',
          question: '「その他」で自由記述する設問',
          options: [
            { value: 'a', label: '選択肢A', isDefault: true, defaultReason: 'A を推奨する理由' },
            { value: 'b', label: '選択肢B', isDefault: false, defaultReason: null },
          ],
        },
      ],
    },
  ],
};

const PLACEHOLDER = 'const QUESTIONS_DATA = [];';
const tpl = readFileSync(TEMPLATE, 'utf8');

const results = [];
function check(name, ok, detail = '') {
  results.push(ok);
  console.log(`${ok ? '[PASS]' : '[FAIL]'} ${name}${ok || !detail ? '' : '  -- ' + detail}`);
}

// SKILL.md Step 3 は「この 1 行を丸ごと置換」と定めるため、ちょうど 1 箇所であることが契約。
check('置換ターゲットがちょうど 1 箇所', tpl.split(PLACEHOLDER).length === 2);

const filled = join(WORK, 'filled.html');
const pristine = join(WORK, 'pristine.html');
writeFileSync(filled, tpl.replace(PLACEHOLDER, `const QUESTIONS_DATA = ${JSON.stringify(SAMPLE)};`));
writeFileSync(pristine, tpl);

const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${join(WORK, 'profile')}`,
  '--no-first-run',
  '--no-default-browser-check',
  '--allow-file-access-from-files',
  'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForChrome() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) return;
    } catch { /* 起動待ち */ }
    await sleep(250);
  }
  throw new Error('Chrome の CDP エンドポイントに接続できない');
}

class Session {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }

  static async open(wsUrl) {
    const ws = new WebSocket(wsUrl);
    const s = new Session(ws);
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      const p = s.pending.get(msg.id);
      if (!p) return;
      s.pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    });
    await new Promise((res, rej) => {
      ws.addEventListener('open', res);
      ws.addEventListener('error', rej);
    });
    return s;
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression, awaitPromise = false) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true });
    if (r.exceptionDetails) throw new Error('page error: ' + JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }

  close() { this.ws.close(); }
}

async function newPage(fileUrl) {
  const r = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(fileUrl)}`, { method: 'PUT' });
  const target = await r.json();
  const s = await Session.open(target.webSocketDebuggerUrl);
  const errors = [];
  s.ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text);
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(JSON.stringify(m.params.args));
  });
  await s.send('Runtime.enable');
  await s.send('Page.enable');
  for (let i = 0; i < 40; i++) {
    if (await s.eval('document.readyState === "complete"')) break;
    await sleep(150);
  }
  await sleep(200);
  return { s, errors };
}

try {
  await waitForChrome();

  // --- 未設定テンプレート: フォールバック ---
  {
    const { s, errors } = await newPage('file://' + pristine);
    check('未設定時にフォールバック文言を表示',
      (await s.eval('document.getElementById("questions-container").textContent')).includes('データが読み込まれていません'));
    check('未設定時にエクスポートボタンが disabled',
      (await s.eval('document.getElementById("btn-export").disabled')) === true);
    check('未設定時に JS エラーなし', errors.length === 0, errors.join(' | '));
    s.close();
  }

  // --- サンプル JSON 差し込み: 描画 ---
  const { s, errors } = await newPage('file://' + filled);

  check('タイトル描画', (await s.eval('document.getElementById("title").textContent')) === SAMPLE.title);
  check('phase バッジが日本語ラベル', (await s.eval('document.getElementById("phase-badge").textContent')) === '設計');
  check('カテゴリ数 2', (await s.eval('document.querySelectorAll(".category-section").length')) === 2);
  check('設問数 3', (await s.eval('document.querySelectorAll(".question-card").length')) === 3);
  check('質問番号がカテゴリを跨いで連番',
    (await s.eval('[...document.querySelectorAll(".q-number")].map(e=>e.textContent).join(",")')) === 'Q1,Q2,Q3');
  check('severity バッジに sev-* クラス',
    (await s.eval('!!document.querySelector(".q-badge.sev-major") && !!document.querySelector(".q-badge.sev-critical")')) === true);
  check('targetDoc / location を「該当:」行に表示',
    (await s.eval('document.querySelector(".q-location").textContent')).includes('SKILL.md — Step 3'));
  check('デフォルト選択肢が checked + 推奨バッジ',
    (await s.eval('document.querySelector(\'input[name="q1"][value="a"]\').checked && !!document.querySelector(".default-badge")')) === true);
  check('defaultReason を表示',
    (await s.eval('document.querySelector(".default-reason").textContent')) === 'A を推奨する理由');

  // label は原本 (issue 本文・コードベース) 由来の文字列が入りうるため、esc() の回帰は必須。
  check('label がエスケープされ script 要素が注入されない (XSS 防止)',
    (await s.eval(`(() => {
      const card = document.querySelector('[data-qid="q2"]');
      const span = card.querySelector('input[value="b"]').nextElementSibling;
      return span.textContent === '選択肢B<script>'
        && span.children.length === 0
        && card.querySelectorAll('script').length === 0;
    })()`)) === true);

  check('初期進捗テキスト', (await s.eval('document.getElementById("progress-text").textContent')) === '0 / 3 問を変更');
  check('初期サマリー', (await s.eval('document.getElementById("summary-text").textContent')) === 'すべてデフォルトのまま');

  // --- 操作: デフォルト以外を選択 ---
  await s.eval('document.querySelector(\'input[name="q2"][value="b"]\').click()');
  await sleep(100);
  check('変更した設問カードに .modified が付く',
    (await s.eval('document.querySelector(\'[data-qid="q2"]\').classList.contains("modified")')) === true);
  check('未変更の設問カードは .modified なし',
    (await s.eval('document.querySelector(\'[data-qid="q1"]\').classList.contains("modified")')) === false);
  check('進捗テキストが 1 件変更に更新',
    (await s.eval('document.getElementById("progress-text").textContent')) === '1 / 3 問を変更');

  // --- 操作: 「その他」+ 自由記述 ---
  check('「その他」入力欄は初期状態で disabled',
    (await s.eval('document.querySelector(\'[data-qid="q3"] .custom-input\').disabled')) === true);
  await s.eval('document.querySelector(\'[data-qid="q3"] input[value="__custom__"]\').click()');
  await sleep(100);
  check('「その他」選択で入力欄が有効化',
    (await s.eval('document.querySelector(\'[data-qid="q3"] .custom-input\').disabled')) === false);
  check('「その他」選択で wrapper に .selected',
    (await s.eval('document.querySelector(\'[data-qid="q3"] .custom-input-wrapper\').classList.contains("selected")')) === true);
  await s.eval(`(() => {
    const el = document.querySelector('[data-qid="q3"] .custom-input');
    el.value = '両方を段階的に導入する';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(100);
  check('進捗テキストが 2 件変更に更新',
    (await s.eval('document.getElementById("progress-text").textContent')) === '2 / 3 問を変更');
  check('サマリーが変更件数を表示',
    (await s.eval('document.getElementById("summary-text").textContent')) === '2 件をデフォルトから変更');
  check('進捗バーが 67%', (await s.eval('document.getElementById("progress-bar").style.width')) === '67%');

  // --- エクスポート契約 (SKILL.md Step 5 / Step 7 が依存する部分) ---
  // ダウンロードを発火させずに Blob を捕捉する。
  await s.eval(`(() => {
    URL.createObjectURL = (b) => { window.__blob = b; return 'blob:stub'; };
    HTMLAnchorElement.prototype.click = function () { window.__downloadName = this.download; };
  })()`);
  await s.eval('document.getElementById("btn-export").click()');
  await sleep(200);

  check('ダウンロードファイル名', (await s.eval('window.__downloadName')) === 'questionnaire-answers.json');

  const exported = JSON.parse(await s.eval('window.__blob.text()', true));
  check('エクスポート: totalQuestions=3', exported.totalQuestions === 3);
  check('エクスポート: answeredCount=3', exported.answeredCount === 3);
  check('エクスポート: modifiedCount=2', exported.modifiedCount === 2);

  const [a1, a2, a3] = exported.answers;
  check('Q1 = 既定値のまま (isModified:false / customInput:null)',
    a1.isAnswered === true && a1.isModified === false && a1.selectedLabel === '選択肢A' && a1.customInput === null,
    JSON.stringify(a1));
  check('Q2 = 別選択肢 (isModified:true / selectedLabel は生の値)',
    a2.isModified === true && a2.selectedOption === 'b' && a2.selectedLabel === '選択肢B<script>',
    JSON.stringify(a2));
  check('Q3 = その他 (selectedOption:custom / customInput に本文)',
    a3.isModified === true && a3.selectedOption === 'custom' && a3.selectedLabel === '(その他)'
      && a3.customInput === '両方を段階的に導入する',
    JSON.stringify(a3));
  check('エクスポートに category / question が入る',
    a1.category === '設計判断' && a3.category === 'スコープ' && a1.question === 'デフォルトのまま確定する設問');
  check('トーストが表示される',
    (await s.eval('document.getElementById("toast").classList.contains("show")')) === true);
  check('操作中に JS エラーなし', errors.length === 0, errors.join(' | '));

  s.close();
} finally {
  chrome.kill();
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n=== ${results.length - failed} passed / ${failed} failed ===`);
process.exit(failed ? 1 : 0);
NODE_EOF

exit $?
