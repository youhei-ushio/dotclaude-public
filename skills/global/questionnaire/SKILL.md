---
name: questionnaire
description: |
  issue作成・設計・実装中に不明点が発生したとき、推測や棚上げを防ぐためにHTMLベースの質問票を生成する。
  Claude が不明点を検知したら自動的に起動する。他スキル（create-issue, create-pr 等）からの内部呼び出しも可能。
  「質問票を作って」「不明点を整理して」のような自然言語でも起動。
allowed-tools: Read, Write, Bash
---

# 質問票スキル（Questionnaire / aqod）

不明点を推測で埋めたり棚上げしたまま進めることを防ぐ。
Claude が不明点を構造化し、HTML アンケートを生成。ユーザーがブラウザで回答し、
**確定した質問＋回答を利用リポジトリの `qa/<slug>-questionnaire.md`（永続・git 追跡）に残す**。

## 位置づけ（知識管理の輪との接続）

このスキルは HVE（Hypervelocity Engineering）の **aqod（質問票生成）** に相当する。
知識管理を導入したリポジトリ（例: 利用リポの ADR で knowledge 運用を定義している場合）では、生成した `qa/*.md` が
`original-docs → qa(aqod) → knowledge(akm) → 実装` の輪の qa レイヤーとして機能する。

- **ツール（このスキル）は dotclaude（`~/.claude`）に置く**。利用リポには持ち込まない。
- **知識ストア（`qa/`）は利用リポに生やす**。このスキルは実行時に利用リポのルートへ `qa/` を作って書き込む。
- **今回のスコープは `qa/` のみ**。`original-docs/` / `knowledge/` / ADR の導入は利用リポ側の責務であり、このスキルは行わない。
- 知識管理未導入のリポで使っても、`qa/*.md` は「不明点と確定回答の記録」として単体で有効。

HTML は**回答用の揮発ファイル**（UX のための一時物）、`qa/*.md` が**永続の正**である。

`qa/*.md` は git 追跡下に置かれる。公開リポジトリで使う場合、記録される質問と回答も公開される点に留意し、非公開情報を含む場合は `.gitignore` するか非公開リポで運用する。

## 起動条件

以下のいずれかに該当する場合、このスキルを自動起動する:

1. issue 作成時に要件の解釈が複数あり得る
2. 設計判断で選択肢が複数あり、ユーザーの意図が不明
3. 実装方針でトレードオフがあり、優先順位が不明
4. 既存仕様との整合性が不明確
5. 他スキルの実行中に不明点が蓄積した

**起動しない場合**: 不明点が 1〜2 件で AskUserQuestion で十分な場合はこのスキルを使わない。
3 件以上の不明点がある、または体系的に整理すべき場合に使う。

## 手順

### Step 1: 不明点の洗い出し

会話コンテキスト・コードベース・issue 内容から不明点を網羅的に洗い出す。

- 最大 50 問
- カテゴリに分類する（下記「カテゴリ分類」参照）
- 各質問に対して以下を設定:
  - 質問文（1 文で明確に）
  - 選択肢 2〜4 個
  - デフォルト回答（＝未回答時の既定値候補。必ず 1 つ選択状態にする）
  - デフォルト選択の理由（なぜその選択肢を推奨するか）
  - 「その他」入力欄（全問に自動付与）
  - **HVE メタ**（`qa/*.md` に載せるため。分かる範囲で埋め、不明なら省略可）:
    - `対象ドキュメント`（この不明点が属するファイル/仕様）
    - `該当箇所`（原本や仕様の具体箇所）
    - `問題種別`（データ整合性 / 一貫性欠落 / 不明瞭 / 重大な欠落 等）
    - `重大度`（critical / major / minor）
    - `未回答のまま進めた場合の影響`

### Step 2: 質問データの JSON 生成

以下の形式で JSON を構築する（`scope` / `targetDocs` / `relatedScope` / `inferencePolicy` と各質問の HVE メタは任意。分かる範囲で埋める）。
なお `targetDocs`（トップレベル・配列）は**票全体の対象スコープ**、各質問の `targetDoc`（単数）は**その質問が該当する具体ドキュメント**で、別物として使い分ける:

**必須制約:**

- **`id` は票全体で一意にする**（カテゴリを跨いでも重複させない。`q1`〜`qN` の通し番号でよい）。回答自体は出現順で管理されるため重複しても失われず、テンプレートは重複を検知して画面に警告を出すが、エクスポート JSON の `id` が重複してデータの追跡が困難になる。
- **`isDefault: true` は 1 問につき 1 つだけ**にする。複数指定した場合は先頭のみが既定値として扱われる。
- **`value` は同一設問内で一意にする**（型は文字列を推奨）。選択の同一性は選択肢の出現順で判定されるため重複しても誤記録は起きないが、`selectedOption` から選択肢を逆引きできなくなる。

```json
{
  "title": "【質問票タイトル】",
  "description": "この質問票の目的・背景の説明",
  "phase": "issue-creation | design | implementation",
  "scope": "対象スコープ（例: original-docs/<機能名>/ や 実装対象の説明）",
  "targetDocs": ["対象ドキュメント/ファイル1", "対象ドキュメント/ファイル2"],
  "relatedScope": "関連スコープ（エピック/チケット等）",
  "inferencePolicy": "推論許可の方針（例: 一部は人間判断、残りは既定値候補を承認）",
  "categories": [
    {
      "name": "カテゴリ名",
      "questions": [
        {
          "id": "q1",
          "question": "質問文をここに記載",
          "context": "質問の背景・補足情報（任意）",
          "targetDoc": "対象ドキュメント（任意）",
          "location": "該当箇所（任意）",
          "problemType": "問題種別（任意）",
          "severity": "critical | major | minor（任意）",
          "impact": "未回答のまま進めた場合の影響（任意）",
          "options": [
            {
              "value": "option_a",
              "label": "選択肢のラベル",
              "isDefault": true,
              "defaultReason": "この選択肢をデフォルト（既定値候補）にした理由"
            },
            {
              "value": "option_b",
              "label": "別の選択肢",
              "isDefault": false,
              "defaultReason": null
            }
          ]
        }
      ]
    }
  ]
}
```

### Step 3: HTML 生成（回答用の揮発ファイル）

1. 出力先ディレクトリを確認: `mkdir -p docs/temp`（存在しなければ作成。揮発なので `qa/` には置かない）
2. **Step 2 の JSON を `docs/temp/questionnaire-data.json` に Write する**（Step 7 で突き合わせる元データ。理由は下記）
3. テンプレートを読み込む: `~/.claude/skills/questionnaire/assets/questionnaire-template.html`
4. テンプレート内の `const QUESTIONS_DATA = [];` を Step 2 の JSON で置換する。**埋め込む前に JSON 中の `<` をすべて `\u003c` にエスケープする**（JSON 文字列としては等価なので値は変わらない。エスケープしないと、質問文や `location` に `</script>` が含まれたとき inline script が早期終了して画面が壊れる）
5. 置換後の HTML を `docs/temp/questionnaire.html` に Write
6. 生成物を検証する（不正なリテラルを埋め込むと inline script が parse エラーになり、白画面のまま原因が分からなくなるため）。**画面上の警告は人間にしか届かないので、契約違反はここで機械的に検出する**:

   ```bash
   # JSON の妥当性 + 上記「必須制約」の充足を一括で検証する
   python3 - <<'PY'
   import json, sys
   d = json.load(open('docs/temp/questionnaire-data.json'))
   qs = [q for c in d.get('categories', []) for q in c.get('questions', [])]
   ids = [q.get('id') for q in qs]
   dup = {i for i in ids if ids.count(i) > 1}
   bad = [q.get('id') for q in qs if sum(1 for o in q.get('options', []) if o.get('isDefault')) != 1]
   if dup: sys.exit(f'id が重複: {sorted(dup)}')
   if bad: sys.exit(f'isDefault が 1 つでない設問: {bad}')
   print(f'OK: {len(qs)} 問')
   PY
   ```

   - `docs/temp/questionnaire.html` に `const QUESTIONS_DATA = [];` が残っていないこと（置換漏れ検出）
   - `docs/temp/questionnaire.html` に `</script>` が 1 個だけであること（breakout 検出）

```
テンプレート内の置換対象（この 1 行を丸ごと置換）:
const QUESTIONS_DATA = [];
↓
const QUESTIONS_DATA = { ... Step 2 の JSON（`<` は \u003c にエスケープ済み） ... };
```

**Step 2 の JSON は必ずファイル（`docs/temp/questionnaire-data.json`）に書く。** 会話コンテキストに保持するだけにしてはならない。回答待ちは人間の作業時間を挟むため長時間・大量トークンを跨ぐ工程であり、context 圧縮で揮発すると Step 6 のサマリーも Step 7 の永続化も再現不能になる（Step 8 で HTML も消えるため元データが完全に失われる）。永続の正は `qa/*.md`、その生成元の正はこの JSON ファイルである。

### Step 4: ブラウザで開く

```bash
open docs/temp/questionnaire.html
```

ユーザーに以下を伝える:
「質問票をブラウザで開きました。回答後、画面下部の「回答をエクスポート」ボタンをクリックしてください。完了したらお知らせください。」

### Step 5: 回答の読み取り

ユーザーが「回答しました」「完了」等と伝えたら:

1. エクスポートされたファイルを特定する。ファイル名は `questionnaire-answers-<ローカル日時>.json` 形式（例: `questionnaire-answers-20260804-161530.json`）で毎回一意になる:

   ```bash
   ANSWERS=$(ls -t ~/Downloads/questionnaire-answers-*.json 2>/dev/null | head -1)
   ```

   見つからない場合はブラウザのダウンロード先設定をユーザーに確認する。

2. Read する前に**その回答が今回の票のものであることを検証する**（古い回答をそのまま `qa/*.md` に確定記録しないため）:

   ```bash
   # 回答ファイルが HTML より新しいこと。mtime 同士の比較なのでタイムゾーンに依存しない。
   # JSON の exportedAt は UTC の ISO8601 なので、ローカル時刻と直接比較してはいけない。
   [ "$ANSWERS" -nt docs/temp/questionnaire.html ] && echo fresh || echo stale
   ```

   さらに Read 後、`title` が `docs/temp/questionnaire-data.json` の `title` と一致し、`totalQuestions` が今回の設問数と一致することを確認する。

   いずれかが合わなければ別の票／古い回答なので、ユーザーに再エクスポートを依頼する。

3. 各回答を解釈:
   - `isAnswered` が `false` (`selectedOption` が `null`) → 未回答扱い。ユーザーに再確認する
   - `selectedOption` が `"custom"` かつ `customInput` が空文字 → 「その他」選択だが自由記述無し。ユーザーに再確認する
   - `selectedOption` が `"custom"` かつ `customInput` に内容がある → `customInput` を採用
   - それ以外 → `selectedLabel` を採用
4. デフォルトから変更された回答を特に注目して報告

### Step 6: 回答サマリーの提示

回答結果を以下の形式でユーザーに提示:

```
## 回答サマリー

### デフォルトから変更された項目（要注目）
- Q03: 【質問】 → 【選択された回答】（デフォルト: 【元のデフォルト】）

### デフォルトのまま確定した項目
- Q01: 【質問】 → 【回答】
- Q02: 【質問】 → 【回答】

### 「その他」で自由記述された項目
- Q07: 【質問】 → 【入力内容】
```

番号は Step 7 の `qa/*.md`（`Q01` ゼロ埋め2桁）と揃える。HTML 上の表示は `Q1`（非ゼロ埋め）だが、報告・永続ファイルではゼロ埋めに統一する。

### Step 7: qa アーティファクトの永続化

**Step 5 の読み取り・Step 6 のサマリー提示が成功した場合のみ実行する。**

`docs/temp/questionnaire-data.json`（Step 3 で書いた質問 JSON）を Read し、Step 5 の回答と突き合わせ、
**利用リポジトリのルートに `qa/<slug>-questionnaire.md` を書く**（HVE aqod 形式）。
会話コンテキストの記憶ではなくこのファイルを正として読むこと（記憶と食い違う場合はファイルが正）。

1. `mkdir -p qa`（利用リポのルート。冪等）
2. `<slug>` は `title`（無ければ `scope`）の主題を kebab-case にした英字（例: `search-filter-spec`）。ファイル名は `<slug>-questionnaire.md`
3. 作成日・回答確定日は `date +%Y-%m-%d` で取得（学習データの日付に頼らない）
4. **質問番号と突き合わせキー**: 質問は出現順に `Q01` / `Q02` … と**ゼロ埋め2桁で採番**する（`[Q0x]` ブロックと回答表の `No.` は同じ採番に揃える）。
   - **突き合わせにはエクスポート JSON の `index`（1 始まりの出現順）を使う。`id` は突き合わせキーにしない**。`id` は票データ側の値をそのまま返す参考情報で、一意性が保証されないため、キーに使うと別の設問の回答を取り違えて確定記録しうる。
   - `Q01` は `index: 1` に対応する。`questionnaire-data.json` の `categories[].questions[]` を平坦化した出現順とも一致する。
5. 以下のテンプレートで Write（`{...}` は `docs/temp/questionnaire-data.json` と回答から埋める。可変長フィールドは全要素を展開する）:

```markdown
# {title}

- 対象スコープ: {scope}
- 対象ドキュメント:
  - `{targetDocs の各要素を 1 行ずつ列挙}`
- 関連スコープ: {relatedScope}
- 生成: aqod（{description の主旨}）
- 状態: 回答済み
- 推論許可: {inferencePolicy}
- 作成日: {作成日 YYYY-MM-DD}
- 回答確定日: {回答確定日 YYYY-MM-DD}

## サマリー

{description / この質問票が扱う論点の背景}

---

[Q01]
- 対象ドキュメント: {targetDoc}
- 該当箇所: {location}
- 問題種別: {problemType}
- 重大度: {severity}
- 質問内容: {question}
- 選択肢: {全 options を A) B) C)… の順で label を列挙}
- 未回答時の既定値候補: {isDefault の option.label}
- 既定値候補の理由: {isDefault の defaultReason}
- 未回答のまま進めた場合の影響: {impact}

[Q02]
...

---

## 回答（確定 {回答確定日 YYYY-MM-DD}）

| No. | 回答 | 判断 | 根拠 |
|---|---|---|---|
| Q01 | **{選択された label または「その他」の記述}** | {既定値承認 / 人間判断} | {根拠（defaultReason・customInput・確定時の判断理由）} |
| Q02 | ... | ... | ... |
```

- `判断` 列: エクスポート JSON の `isModified` が `false`（既定値のまま）→ `既定値承認`、`true`（デフォルトから変更）→ `人間判断`。
  - ただし `isAnswered` が `false`（未回答）の行は `既定値承認` に含めない。未回答は Step 5 で再確認し、確定値を得てから記録する（未回答を承認扱いにしない）。
- `回答` 列・`根拠` 列の対応:
  - `既定値承認` → `回答` は選択された label、`根拠` は `既定値候補の理由`（defaultReason）
  - `人間判断`（別の選択肢を選択）→ `回答` は選択された label、`根拠` は確定時の判断理由
  - `人間判断`（「その他」= custom を選択。`isModified` は常に `true`）→ `回答` は `customInput` の本文、`根拠` も同記述
- HVE メタ（対象ドキュメント/該当箇所/問題種別/重大度/影響）が未設定の質問は、その行を省略してよい（無理に埋めない）。
- 任意メタ（scope/targetDocs/relatedScope/inferencePolicy）が無い場合は該当ヘッダ行を省略する。

### Step 8: クリーンアップ

**Step 7 の永続化が成功した場合のみ実行する:**

```bash
rm -f docs/temp/questionnaire.html docs/temp/questionnaire-data.json
```

- 削除するのは**回答用の揮発 HTML と、その元データ JSON のみ**。`qa/<slug>-questionnaire.md` は永続の正として残す。
- Step 5 で読み取り失敗 (ファイル未 DL・パス違い・JSON パース失敗など) の場合は両ファイルを残し、ユーザーに再エクスポートを依頼する。再エクスポートの導線 (ブラウザで開いたままの HTML) と、Step 7 に必要な元データを守るため。
- **注意**: `docs/temp/` は `.gitignore` 対象外である。上記の失敗パスで意図的にファイルを残した場合、質問票には未公開の設計情報が含まれうるため、**コミット・PR 作成の前に必ず削除する**（削除忘れに注意）。
- **注意**: `~/Downloads/questionnaire-answers-*.json` はユーザーのダウンロードフォルダのファイルであるため、自動削除しない。

### Step 9: 作業の継続

回答内容を前提条件として確定し、元の作業（issue 作成・設計・実装等）を継続する。
知識管理を導入したリポでは、生成した `qa/*.md` を akm（knowledge 生成）の入力として引き渡せる。

## カテゴリ分類

質問を以下のカテゴリに分類する（該当するもののみ使用）:

| カテゴリ | 説明 |
|---------|------|
| 要件定義 | 機能要件・非機能要件の明確化 |
| 仕様確認 | 既存仕様との整合性・仕様解釈 |
| 設計判断 | アーキテクチャ・技術選択・パターン |
| UI/UX | 画面設計・操作フロー・表示仕様 |
| データ設計 | DB スキーマ・データフロー・入出力 |
| エラー処理 | 異常系の振る舞い・エラーメッセージ |
| パフォーマンス | 性能要件・最適化方針 |
| セキュリティ | 認証・認可・データ保護 |
| 運用 | デプロイ・監視・移行手順 |
| スコープ | 今回対応する/しないの境界線 |

## 質問設計の指針

- **1 質問 1 論点**: 複合的な質問は分割する
- **具体的に**: 「どうしますか」ではなく「A と B のどちらにしますか」
- **選択肢にトレードオフを明記**: 各選択肢のメリット・デメリットを label に含める
- **デフォルトには根拠を**: コードベースの既存パターン、一般的なベストプラクティス、シンプルさ等を理由にする
- **独立性**: 他の質問の回答に依存しない質問設計にする（依存する場合は context で前提を明記）
- **推測で埋めない**: 一次ソースに事実が無い項目を根拠なく既定値化しない（＝捏造にあたる）。事実が足りなければ「確認が必要」を選択肢に含める
