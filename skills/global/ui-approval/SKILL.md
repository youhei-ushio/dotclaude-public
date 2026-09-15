---
name: ui-approval
description: |
  ブラウザテストのスクリーンショットを LAN 越しの Web UI で 1 つずつ表示し、
  ユーザーの承認または指摘を収集する。質問票スキルの画像レビュー版。
  「画面承認して」「スクショレビュー」「UI 承認」「画面確認して」
  のような自然言語で起動。
allowed-tools: Read, Bash, Write
---

# UI 承認レビュー (ui-approval)

## 目的

ブラウザテスト完了後のスクリーンショットをユーザーに 1 つずつ提示し、
承認 / 指摘（修正依頼）を収集する。`serve-ui-approval.py` が起動する
LAN 越しの Web UI でブラウザから操作する。

## 手順

### Step 1: レビュー対象の収集

レビュー対象のスクリーンショットを JSON ファイルにまとめる。
`docs/images/` 等にあるブラウザテストのスクショを対象とする。

出力先: 指定ディレクトリ（省略時は `docs/temp/`）

```json
{
  "title": "商品検索画面 UI 承認",
  "items": [
    {
      "id": "screen-1",
      "label": "初期状態（2カラム、空状態）",
      "image_path": "docs/images/product-search-initial.png",
      "description": "検索前の初期表示。左カラムに検索フォーム、右カラムに空状態メッセージ。",
      "design_rationale": "最小限のデザイン: 検索前は不要な情報を表示しない"
    },
    {
      "id": "screen-2",
      "label": "検索後（明細一覧）",
      "image_path": "docs/images/product-search-result.png",
      "description": "検索後、明細一覧が左カラムに表示される。",
      "design_rationale": "連続処理のため一覧を常時表示（記憶より認識）"
    }
  ]
}
```

各項目:
- `id`: 一意の識別子
- `label`: 画面の名前（Web UI のタイトルに表示）
- `image_path`: スクショのファイルパス（リポジトリルートからの相対パス）
- `description`: この画面で何が表示されているかの説明
- `design_rationale`: なぜこのデザインにしたかの根拠

### Step 2: Web 配信

`Bash` の **run_in_background** で起動:

```
python3 ~/.claude/skills/ui-approval/serve-ui-approval.py \
  <review.json のパス> [port]
```

- `port` 省略時は `8786`
- サーバーは `0.0.0.0` に bind し、起動時に LAN アクセス URL を stdout に出力
- ループバックでの表示確認は不要（LAN IP でブラウザから開ければ十分）。
  `curl 127.0.0.1` や Playwright での自己アクセスは試みない

### Step 3: ユーザーレビュー

ユーザーはブラウザで:

1. スクショが 1 つずつカード形式で表示される
2. 各スクショに対して:
   - **承認** ボタン — この画面は OK
   - **指摘** ボタン + テキスト入力 — 修正が必要な点を記入
3. 全項目をレビュー後「送信」ボタン

### Step 4: 結果の取り込み

送信するとサーバーが JSON に結果を書き戻し、終了する。

```json
{
  "items": [
    {
      "id": "screen-1",
      "status": "approved"
    },
    {
      "id": "screen-2",
      "status": "rejected",
      "comment": "明細の品名カラムが狭すぎて見切れている。幅を広げて。"
    }
  ]
}
```

結果に基づいて:
- `approved` → 変更不要
- `rejected` → コメントの内容に従って修正し、修正後に再度スクショを撮って再レビュー

**rejected が 1 件以上ある場合**: 修正 → スクショ更新 → 再度 Step 2 から実行。
全件 approved になるまで繰り返す。

### Step 5: 判断軸の蓄積

PO の UI 承認結果を **feedback 型メモリ** として保存し、将来の自動判断に活かす。

各スクリーンショットの承認/指摘結果について:

1. PO のフィードバック内容から**判断軸**を抽出する:
   - レイアウト: 一覧→詳細のドリルダウン vs モーダル
   - 操作フロー: ステップ数の許容範囲、確認画面の要否
   - 表示密度: 情報量と視認性のバランス
   - エラー表示: inline vs toast vs ページ遷移
   - ボタン配置: 主操作の位置、危険操作の確認
   - レスポンシブ: モバイル対応の要否

2. 以下の形式で**メモリファイルを作成**する:

```markdown
---
name: ui-judgment-{feature-slug}
description: {画面名} の UI 承認判断
metadata:
  type: feedback
---

判断: {approved / rejected}
指摘: {PO フィードバック}
基準: {抽出した判断軸}

**Why:** PO が {理由} を重視した
**How to apply:** 同種の画面設計で適用
```

3. MEMORY.md のインデックスに追加する

**蓄積の成熟パス**:
- **Phase 3a（現在）**: 全 UI 変更に PO 承認を要求。フィードバックを蓄積
- **Phase 3b（10件以上蓄積後）**: 過去の判断パターン合致時は付記して通知。PO の判断コスト低減
- **Phase 3c（パターン安定後）**: 判断軸をリポ内のドキュメント (例: `docs/ui-criteria.md`) に昇格。自動承認可否を判定

## 他スキルからの呼び出し

- **`/resolve-issue` Step 4 (feature + 画面変更あり)**: テスト通過後、PR 作成前にユーザー承認を得る
- 設計段階のワイヤーフレーム承認にも使える（スクショの代わりにワイヤーフレーム画像を渡す）

## 注意事項

- LAN 限定・認証なし。信頼できるネットワークでのみ起動する
- 画像ファイルはサーバーから直接配信する（base64 エンコードではなくファイルパスで参照）
- レビュー結果は JSON で永続化されるため、中断しても再開可能
