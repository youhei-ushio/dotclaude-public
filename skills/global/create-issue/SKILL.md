---
name: create-issue
description: GitHub Issueを作成します。一時ファイルを使ってIssue本文の#行問題を回避。「issue作成して」「issueを追加して」のような自然言語で起動します。gh issue createコマンドを直接使わず、自発的にIssue作成する場合も必ずこのスキルを使用すること。
allowed-tools: Read, Grep, Glob, Bash, Write
---

# GitHub Issue作成

会話の内容を分析し、GitHub Issueを作成する。

## 手順

### 1. Issue内容の整理

会話の文脈から以下を整理する:
- タイトル（簡潔に、70文字以内目安）
- 本文（概要、要件、背景など）

### 2. Issue本文の作成

**重要: `gh issue create --body` にヒアドキュメントで直接渡さないこと。**

Issue本文に `##` などの `#` で始まる行が含まれると、Claude Codeのセキュリティチェックで許可確認が発生する。
これを回避するため、**必ず一時ファイル経由で `--body-file` を使用する。**

一時ファイルの配置先: `docs/temp/issue-body.md`

```bash
# Writeツールで docs/temp/issue-body.md を作成
# ↓
gh issue create --repo <owner>/<repo> --title "<タイトル>" --body-file docs/temp/issue-body.md
# ↓
rm docs/temp/issue-body.md
```

### 3. Issue本文フォーマット

```markdown
## 概要
背景・目的の説明

## 要件
- 要件1
- 要件2

## 補足
（必要に応じて）
```

### 4. クリーンアップ

Issue作成後、一時ファイルを削除:

```bash
rm docs/temp/issue-body.md
```

### 5. 完了報告

作成したIssueのURLを報告する。

## 注意事項

- `docs/temp/` は `.gitignore` に含まれていないため、削除忘れに注意
- Issue本文を `--body` で直接渡す方法は使わない
- 関連するIssueやPRがある場合は本文内でリンクする
- ラベルやアサインが必要な場合は `--label` `--assignee` オプションを使用する
