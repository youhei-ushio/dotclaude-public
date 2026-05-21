---
name: debug-bar-investigation
description: |
  Laravel Debug Bar でデータ取得問題を調査するとき。
  「データが0件になる」「フィルタが意図と違う動作」「数値が合わない」等の症状の原因究明時に参照。
---

# Laravel Debug Bar によるデータ問題調査

## 調査の3段階

### STEP 1: 問題再現

Playwright MCP で問題のある条件を入力して送信:
```
mcp__playwright__browser_type: 問題のキー（ID・コード等）を入力
mcp__playwright__browser_click: 該当ボタンをクリック
```

### STEP 2: Messages タブの確認

`mcp__playwright__browser_click` で Messages タブをクリック。

注目すべきログキーワード（例 — 自プロジェクトで意味のあるキーに置き換える）:
- "condition (filtered)": フィルタ条件の適用状況
- "Query Time": SQL 実行とパフォーマンス
- ドメイン固有の判定ロジック（例: 種別判定 / 権限判定 / 状態遷移ログ等）

`Log::debug(...)` / `Log::info(...)` 等で要所に痕跡を残しておき、Debug Bar
からその文字列を辿るのが基本パターン。

### STEP 3: Queries タブの確認

実行された SQL の WHERE 条件、JOIN 条件、バインドパラメータを確認。

## 判定基準

- 想定と違う条件分岐に入っている（例: 不要なフィルタ適用） → ロジック修正
- SQL WHERE 条件が過度に限定的 → 条件緩和を検討
- バインドパラメータが想定外の値 → データ型・変換処理を確認

## 調査時の禁則

- ログを見ずに推測で修正を開始しない
- 「動いてるから OK」で済ませない
- 修正後も同じ手順でログ変化を確認する
- Messages タブの情報ログとエラーログを区別する
