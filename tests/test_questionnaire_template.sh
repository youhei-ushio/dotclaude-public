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

// 質問データ側の契約違反 (id 重複 / isDefault 複数) に対する防御を検証するための票。
// どちらも「回答が黙って消える」「画面と記録が食い違う」形で qa/*.md に誤内容が
// 確定記録されるため、テンプレート側の耐性を回帰対象にする。
const SAMPLE_EDGE = {
  title: '契約違反サンプル',
  phase: 'design',
  categories: [
    {
      name: 'カテゴリA',
      questions: [
        {
          id: 'dup',
          question: 'カテゴリA の設問',
          options: [
            { value: 'a', label: 'A-1', isDefault: true, defaultReason: null },
            { value: 'b', label: 'A-2', isDefault: false, defaultReason: null },
          ],
        },
      ],
    },
    {
      name: 'カテゴリB',
      questions: [
        {
          // 別カテゴリで同じ id (契約違反)
          id: 'dup',
          question: 'カテゴリB の設問',
          options: [
            { value: 'a', label: 'B-1', isDefault: true, defaultReason: null },
            { value: 'b', label: 'B-2', isDefault: false, defaultReason: null },
          ],
        },
        {
          id: 'multi',
          question: 'isDefault が複数ある設問',
          options: [
            { value: 'a', label: 'M-1', isDefault: true, defaultReason: null },
            { value: 'b', label: 'M-2', isDefault: true, defaultReason: null },
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
const edge = join(WORK, 'edge.html');
writeFileSync(filled, tpl.replace(PLACEHOLDER, `const QUESTIONS_DATA = ${JSON.stringify(SAMPLE)};`));
writeFileSync(pristine, tpl);
writeFileSync(edge, tpl.replace(PLACEHOLDER, `const QUESTIONS_DATA = ${JSON.stringify(SAMPLE_EDGE)};`));

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
    (await s.eval('document.querySelectorAll(\'.question-card\')[0].querySelector(\'input[value="a"]\').checked && !!document.querySelector(".default-badge")')) === true);
  check('defaultReason を表示',
    (await s.eval('document.querySelector(".default-reason").textContent')) === 'A を推奨する理由');

  // label は原本 (issue 本文・コードベース) 由来の文字列が入りうるため、esc() の回帰は必須。
  check('label がエスケープされ script 要素が注入されない (XSS 防止)',
    (await s.eval(`(() => {
      const card = document.querySelectorAll('.question-card')[1];
      const span = card.querySelector('input[value="b"]').nextElementSibling;
      return span.textContent === '選択肢B<script>'
        && span.children.length === 0
        && card.querySelectorAll('script').length === 0;
    })()`)) === true);

  check('初期進捗テキスト', (await s.eval('document.getElementById("progress-text").textContent')) === '0 / 3 問を変更');
  check('初期サマリー', (await s.eval('document.getElementById("summary-text").textContent')) === 'すべてデフォルトのまま');

  // --- 操作: デフォルト以外を選択 ---
  await s.eval('document.querySelectorAll(\'.question-card\')[1].querySelector(\'input[value="b"]\').click()');
  await sleep(100);
  check('変更した設問カードに .modified が付く',
    (await s.eval('document.querySelectorAll(\'.question-card\')[1].classList.contains("modified")')) === true);
  check('未変更の設問カードは .modified なし',
    (await s.eval('document.querySelectorAll(\'.question-card\')[0].classList.contains("modified")')) === false);
  check('進捗テキストが 1 件変更に更新',
    (await s.eval('document.getElementById("progress-text").textContent')) === '1 / 3 問を変更');

  // --- 操作: 「その他」+ 自由記述 ---
  check('「その他」入力欄は初期状態で disabled',
    (await s.eval('document.querySelectorAll(\'.question-card\')[2].querySelector(\'.custom-input\').disabled')) === true);
  await s.eval('document.querySelectorAll(\'.question-card\')[2].querySelector(\'input[value="__custom__"]\').click()');
  await sleep(100);
  check('「その他」選択で入力欄が有効化',
    (await s.eval('document.querySelectorAll(\'.question-card\')[2].querySelector(\'.custom-input\').disabled')) === false);
  check('「その他」選択で wrapper に .selected',
    (await s.eval('document.querySelectorAll(\'.question-card\')[2].querySelector(\'.custom-input-wrapper\').classList.contains("selected")')) === true);
  await s.eval(`(() => {
    const el = document.querySelectorAll('.question-card')[2].querySelector('.custom-input');
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

  // 固定名だと既存ファイル存在時にブラウザが "(1)" 付きで保存し、読み取り側が
  // 古い回答を掴む。エクスポート時刻入りの一意名であることを固定する。
  const downloadName = await s.eval('window.__downloadName');
  check('ダウンロードファイル名がエクスポート時刻入りで一意',
    /^questionnaire-answers-\d{8}-\d{6}\.json$/.test(downloadName), downloadName);

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
  // 内部キーは出現順だが、エクスポートの id は質問データ側の id を返す (Step 7 の突き合わせ用)
  check('エクスポートの id が元の q.id',
    a1.id === 'q1' && a2.id === 'q2' && a3.id === 'q3',
    JSON.stringify([a1.id, a2.id, a3.id]));
  check('トーストが表示される',
    (await s.eval('document.getElementById("toast").classList.contains("show")')) === true);
  check('操作中に JS エラーなし', errors.length === 0, errors.join(' | '));

  s.close();

  // --- 質問データ側の契約違反に対する防御 ---
  {
    const { s: e, errors: eErrors } = await newPage('file://' + edge);

    check('id 重複でも設問が 3 件描画される',
      (await e.eval('document.querySelectorAll(".question-card").length')) === 3);
    check('id 重複を画面で警告する',
      (await e.eval('!!document.querySelector(".dup-warning") && document.querySelector(".dup-warning").textContent.includes("dup")')) === true);
    check('id 重複でも radio グループが独立している',
      (await e.eval(`(() => {
        const names = [...document.querySelectorAll('.question-card')]
          .map(c => c.querySelector('input[type=radio]').name);
        return new Set(names).size === names.length;
      })()`)) === true);

    // カテゴリA を A-2 に変更しても、カテゴリB の既定選択が解除されないこと
    await e.eval(`(() => {
      const cards = [...document.querySelectorAll('.question-card')];
      cards[0].querySelector('input[data-optlabel="A-2"]').click();
    })()`);
    await sleep(100);
    check('id 重複時に片方の選択がもう片方を解除しない',
      (await e.eval('document.querySelector(\'input[data-optlabel="B-1"]\').checked')) === true);

    check('isDefault が複数でも checked は先頭のみ',
      (await e.eval(`(() => {
        const card = [...document.querySelectorAll('.question-card')][2];
        const checked = [...card.querySelectorAll('input[type=radio]')].filter(r => r.checked);
        return checked.length === 1 && checked[0].dataset.optlabel === 'M-1';
      })()`)) === true);
    check('isDefault が複数でも推奨バッジは先頭のみ',
      (await e.eval(`(() => {
        const card = [...document.querySelectorAll('.question-card')][2];
        return card.querySelectorAll('.default-badge').length === 1;
      })()`)) === true);

    // 表示 (DOM) と内部 state の一致: 未操作の multi 設問が「既定値のまま」で出ること
    await e.eval(`(() => {
      URL.createObjectURL = (b) => { window.__blob = b; return 'blob:stub'; };
      HTMLAnchorElement.prototype.click = function () { window.__downloadName = this.download; };
    })()`);
    await e.eval('document.getElementById("btn-export").click()');
    await sleep(200);
    const edgeExport = JSON.parse(await e.eval('window.__blob.text()', true));
    check('id 重複でも回答が失われない (3 件エクスポートされる)',
      edgeExport.totalQuestions === 3 && edgeExport.answers.length === 3,
      JSON.stringify(edgeExport.totalQuestions));
    const multi = edgeExport.answers[2];
    check('isDefault 複数時、画面の選択と記録が一致する (M-1 が既定値承認)',
      multi.selectedLabel === 'M-1' && multi.isModified === false,
      JSON.stringify(multi));
    check('id 重複時も両設問がそれぞれの回答を保持する',
      edgeExport.answers[0].selectedLabel === 'A-2' && edgeExport.answers[1].selectedLabel === 'B-1',
      JSON.stringify(edgeExport.answers.slice(0, 2)));
    check('契約違反サンプルでも JS エラーなし', eErrors.length === 0, eErrors.join(' | '));

    e.close();
  }

  // --- SKILL.md Step 3 のエスケープ手順が実際に効くこと ---
  // 質問文は issue 本文やコードベース由来なので `</script>` を含みうる。素の
  // JSON.stringify は `<` をエスケープしないため inline script が早期終了する。
  // Step 3 が要求する「`<` を < に置換してから埋め込む」が有効であることを固定する。
  {
    const XSS = {
      title: 'エスケープ検証',
      phase: 'design',
      categories: [{
        name: '仕様確認',
        questions: [{
          id: 'x1',
          question: 'テンプレートの </script> タグをどう扱うか',
          options: [
            { value: 'a', label: 'そのまま', isDefault: true, defaultReason: null },
            { value: 'b', label: '除去する', isDefault: false, defaultReason: null },
          ],
        }],
      }],
    };
    const raw = JSON.stringify(XSS);
    const escaped = raw.replace(/</g, '\\u003c');

    // エスケープ済みでも JSON としては等価であること (値が変わらないこと)
    check('\\u003c エスケープは JSON として等価',
      JSON.stringify(JSON.parse(escaped)) === raw);

    const okPath = join(WORK, 'escaped.html');
    const ngPath = join(WORK, 'unescaped.html');
    writeFileSync(okPath, tpl.replace(PLACEHOLDER, `const QUESTIONS_DATA = ${escaped};`));
    writeFileSync(ngPath, tpl.replace(PLACEHOLDER, `const QUESTIONS_DATA = ${raw};`));

    const { s: ok } = await newPage('file://' + okPath);
    check('エスケープすれば </script> を含む質問文が壊れずに描画される',
      (await ok.eval('document.querySelectorAll(".question-card").length')) === 1
      && (await ok.eval('document.querySelector(".question-text").textContent'))
        === 'テンプレートの </script> タグをどう扱うか');
    ok.close();

    // 未エスケープ時は script が早期終了し、init が走らず設問が 0 件になる。
    // これが「エスケープが必須」である理由の実証。
    const { s: ng } = await newPage('file://' + ngPath);
    check('未エスケープだと script が早期終了して描画されない (エスケープ必須の根拠)',
      (await ng.eval('document.querySelectorAll(".question-card").length')) === 0);
    ng.close();
  }
} finally {
  chrome.kill();
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n=== ${results.length - failed} passed / ${failed} failed ===`);
process.exit(failed ? 1 : 0);
NODE_EOF

exit $?
