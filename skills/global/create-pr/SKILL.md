---
name: create-pr
description: 現在のブランチからプルリクエストを作成します。一時ファイルを使ってPR本文の#行問題を回避。「PR作成して」「PRを作って」のような自然言語で起動します。
allowed-tools: Read, Grep, Glob, Bash, Write
---

# プルリクエスト作成

現在のブランチの変更内容を分析し、PRを作成する。

## 手順

### 1. 状態確認

以下を並列で実行:

```bash
git status
git diff --staged && git diff
git log main..HEAD --oneline
git diff main...HEAD --stat
```

### 2. リモートへプッシュ

ブランチがリモートに存在しない場合:

```bash
gh auth setup-git && git push -u origin <branch>
```

### 3. PR本文の作成

**重要: `gh pr create --body` にヒアドキュメントで直接渡さないこと。**

PR本文に `##` などの `#` で始まる行が含まれると、Claude Codeのセキュリティチェックで許可確認が発生する。
これを回避するため、**必ず一時ファイル経由で `--body-file` を使用する。**

一時ファイルの配置先: `docs/temp/pr-body.md`

```bash
# Writeツールで docs/temp/pr-body.md を作成
# ↓
gh pr create --title "<タイトル>" --body-file docs/temp/pr-body.md
# ↓
rm docs/temp/pr-body.md
```

### 4. PR本文フォーマット

- タイトルは70文字以内

#### 基本フォーマット

```markdown
## Summary
- 変更内容の要約（1〜3行）

## Test plan
- [ ] テスト項目

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

#### Issue対応時の追加ルール

- 本文末尾に `Closes #<issue番号>` を追加
- 成果物にドキュメント（設計資料、仕様書、ADR等）が含まれる場合は「成果物リンク」セクションを追加
  - リンク形式: `https://github.com/<owner>/<repo>/blob/<branch>/<path>`
  - drawioやSVGファイルはMarkdownに埋め込まれているためリンク不要
- 印刷物がある場合は「印刷イメージ」セクションにスクリーンショットを掲載
  - スクリーンショットは `docs/images/` 配下にコミットし、`https://github.com/<owner>/<repo>/blob/<branch>/<path>?raw=true` 形式のURLで参照（プライベートリポジトリ対応）

```markdown
## Summary
- 変更内容のサマリ

## 成果物リンク
（ドキュメント成果物がある場合のみ）

## 印刷イメージ
（印刷するものがある場合のみ）

## Test plan
- テスト内容

Closes #<issue番号>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### 5. クリーンアップ

PR作成後、一時ファイルのみを削除（`docs/temp/` に他のファイルがある場合があるため、ディレクトリごと削除しない）:

```bash
rm docs/temp/pr-body.md
```

## 注意事項

- pushは必ず `gh` コマンド経由で行う（SSH鍵なし）
- `docs/temp/` は `.gitignore` に含まれていないため、削除忘れに注意
- PR本文を `--body` で直接渡す方法は使わない
