---
name: create-issue
description: GitHub Issueを作成します。一時ファイルを使ってIssue本文の#行問題を回避。「issue作成して」「issueを追加して」のような自然言語で起動します。gh issue createコマンドを直接使わず、自発的にIssue作成する場合も必ずこのスキルを使用すること。
allowed-tools: Read, Grep, Glob, Bash, Write, mcp__claude_ai_Gmail__search_threads
---

# GitHub Issue作成

会話の内容を分析し、GitHub Issueを作成する。

## 手順

### 1. Issue内容の整理 + 種別判定

会話の文脈から以下を整理する:
- タイトル（簡潔に、70文字以内目安）
- **種別（bug / feature / ops）**
- 本文（種別に応じたテンプレートで構成 — Step 3 参照）

#### 種別判定ロジック

上から順に評価し、最初に該当したものを採用する:

1. **ラベル指定がある場合** → そのまま使用
2. **メール分類からの引き継ぎがある場合** (メールから Issue を起こす skill を併用しているとき) → その分類を使用:
   - 障害報告 → `bug`
   - 要望 → `feature`
   - 問い合わせ → 内容により `bug` or `feature`
3. **本文キーワード判定**:
   - `bug` の兆候: 「動かない」「エラー」「不具合」「表示されない」「おかしい」「出ない」「できない」「落ちる」「止まる」
   - `feature` の兆候: 「してほしい」「追加」「変更」「新しく」「改善」「対応してほしい」「機能」
   - `ops` の兆候: 「データ更新」「移行」「一括処理」「実行して」「処理して」「修正して」（データ修正の文脈）
4. **判定不能** → `AskUserQuestion` で PO に確認する:

```text
AskUserQuestion({
    questions: [{
        question: "Issue の種別を選択してください",
        header: "種別",
        multiSelect: false,
        options: [
            {label: "bug", description: "不具合報告・エラー・想定外の動作"},
            {label: "feature", description: "機能追加・改善要望・画面変更"},
            {label: "ops", description: "処理依頼・データ修正・一括操作"}
        ]
    }]
})
```

種別は Issue のラベル (`bug` / `enhancement` / `ops`) としても付与する（Step 2 参照）。

### 1.5. 質問票ゲート（要否判定 → ユーザー承認）

Step 1 で整理した内容をもとに、**質問票で不確定点を潰す必要があるか**を判定する。

#### 判定基準

**種別による初期判定**:
- `bug`: 通常はスキップ。ただし「バグか要件不足か」が不明な場合は必要
- `feature`: デフォルトで「必要」寄りに判定
- `ops`: 通常はスキップ（処理内容が明確なため）

**質問票が必要な兆候** (いずれか該当で「必要」判定):
- 要件が曖昧で「何を」「どこまで」が特定できない
- 複数の解釈が可能で、どれを採るかで実装が大きく変わる
- 業務フロー・運用ルールなど、コードからは読み取れない前提が欠けている
- 対象ユーザー・頻度・優先度など、判断材料が不足している

**スキップできる兆候** (いずれか該当で「不要」判定):
- 要件が具体的で実装方針が一意に決まる
- バグ報告で再現手順が明確
- 単純なタスク（typo 修正、設定変更など）
- 既に十分なヒアリング済み（会話やメールで詳細確認済み）

**優先ルール**: 両方に該当する場合は「必要」側が優先。判断に迷ったら「必要」寄りに倒す（ユーザーがスキップを選べるため）。

#### 実行フロー

1. 判定結果と根拠を 2-3 行で提示
2. ユーザー承認を得る (`AskUserQuestion`):

```text
AskUserQuestion({
    questions: [{
        question: "質問票: 必要と判定しました（理由: 要件に「画面の使いやすさを改善」とあり、対象画面・改善指標が未特定です）。質問票をどうしますか？",
        header: "質問票",
        multiSelect: false,
        options: [
            {label: "スキップ", description: "このまま issue を作成する"},
            {label: "質問票を実施", description: "/questionnaire で不確定点を整理してから issue 作成"}
        ]
    }]
})
```

> **注:** AskUserQuestion の allowed-tools 非列挙については Step 6 の注記を参照。

3. 「質問票を実施」→ 質問票生成前に以下の順序で既知回答を探索する
   (`knowledge/` は利用リポ側の資産。無ければ手順 1 と永続化を skip する。
   ナレッジファイルの形式は resolve-issue skill Step 2 [feature] に定義):
   1. `knowledge/<domain>/` を検索（利用リポにある場合。domain は Issue の業務領域から判定）。
      既知の Q&A で回答できる質問は質問票から除外する。
      `last_verified` が 6 ヶ月以上前のナレッジは「要再確認」として除外せず質問票に含める
      （resolve-issue skill Step 2 と同一の陳腐化チェック規約）
   2. Gmail MCP で未解決の質問を検索（スコープ制限・PII 除去は resolve-issue skill Step 2 と同一規約）。
      発見した回答は `knowledge/<domain>/` に永続化する
   3. 残った未解決の質問のみ `/questionnaire` スキルで PO に質問する
   4. PO 回答を `knowledge/<domain>/` に永続化する
   回答を受領後、回答内容をもとに Step 1 の要件・背景セクションを具体化して Step 2 へ
4. 「スキップ」→ そのまま Step 2 へ

### 2. Issue本文の作成

**重要: `gh issue create --body` にヒアドキュメントで直接渡さないこと。**

Issue本文に `##` などの `#` で始まる行が含まれると、Claude Codeのセキュリティチェックで許可確認が発生する。
これを回避するため、**必ず一時ファイル経由で `--body-file` を使用する。**

一時ファイルの配置先: `docs/temp/issue-body.md`

種別に応じたラベルを `--label` で付与する:

```bash
# Writeツールで docs/temp/issue-body.md を作成（Step 3 のテンプレートを使用）
# ↓
# bug の場合:
gh issue create --repo <owner>/<repo> --title "<タイトル>" --body-file docs/temp/issue-body.md --label bug
# feature の場合:
gh issue create --repo <owner>/<repo> --title "<タイトル>" --body-file docs/temp/issue-body.md --label enhancement
# ops の場合: ops ラベルは GitHub 既定ラベルではないので、無いリポでは先に作る
# (bug / enhancement は既定で存在する。無いラベルを --label に渡すと作成全体が失敗する。
#  gh label list の既定 --limit は 30 なので上限を上げて取りこぼしを防ぐ)
gh label list --repo <owner>/<repo> --limit 1000 --json name -q '.[].name' | grep -qx ops \
  || gh label create ops --repo <owner>/<repo> --color 0E8A16 --description "処理依頼・データ修正"
gh issue create --repo <owner>/<repo> --title "<タイトル>" --body-file docs/temp/issue-body.md --label ops
# ↓
rm docs/temp/issue-body.md
```

### 3. Issue本文フォーマット（種別別テンプレート）

Step 1 で判定した種別に応じたテンプレートを使用する。
テンプレートの各セクションは、会話の文脈・メール内容・既知のコンテキストから
**可能な限り埋める**。不明な箇所は「不明（要確認: {どう確かめるか}）」と明記する（CLAUDE.md TBD 規約）。

Issue は今後 **別エージェントが対応する前提** で作成する。
セッションのメモリに依存せず、Issue 本文だけで対応に必要な情報が揃っている状態にすること。

#### Bug テンプレート（種別: bug → 軽量パス）

```markdown
## メタ情報
- 種別: bug
- 報告元: {送信者名} ({メールアドレス or 「会話」})
- 起票日: {YYYY-MM-DD}
- 対応パス: 軽量

## 症状
{何が起きているか — 事実のみ。「○○すると○○になる」の形式}

## 期待動作
{本来どうあるべきか}

## 再現コンテキスト
- 発生環境: 本番
- 発生日時: {判明していれば}
- 影響範囲: {影響ユーザー・影響業務}
- 再現手順: (判明している場合)
  1. ...
- 関連データ: {対象データの ID 等。判明していれば}

## 一次情報
{メール本文の要約 / スクリーンショットの説明。クレデンシャルは [REDACTED]}

## 業務フロー上の位置
{業務フローのどのフェーズで発生しているか}

## 成功条件
- [ ] {バグが再現しなくなる条件}
- [ ] {データの正しい状態}

## 対応方針の制約
{なければ「特になし」。「別テーブルを触るな」「この時間帯は避けろ」等}
```

#### Feature テンプレート（種別: feature → フルパス）

```markdown
## メタ情報
- 種別: feature
- 要望元: {送信者名} ({メールアドレス or 「会話」})
- 起票日: {YYYY-MM-DD}
- 対応パス: フル

## 背景・目的
{なぜこの機能が必要か。現状の課題}

## 要件
- {要件 1}
- {要件 2}

## 業務フロー上の位置
{この機能が業務フローのどこに入るか。前後のステップとの関係}

## 対象画面・機能
{既存画面の改修 or 新規画面。対象の特定}

## 成功条件
- [ ] {この機能が完了したとき、何がどうなっていれば成功か}

## 質問票結果
{質問票を実施した場合はリンクまたは要約。未実施なら「未実施」}

## UI 要件
{画面変更の要否と概要。不明なら「不明（要確認: PO に画面変更の要否を確認）」}

## 対応方針の制約
{パフォーマンス要件、互換性要件など。なければ「特になし」}
```

#### Ops テンプレート（種別: ops → 自動化パス）

```markdown
## メタ情報
- 種別: ops
- 依頼者: {送信者名} ({メールアドレス or 「会話」})
- 起票日: {YYYY-MM-DD}
- 対応パス: 自動化

## 処理内容
{何をするか。具体的な操作}

## 対象データ
{対象テーブル・レコード範囲・条件}

## 実行条件
{前提条件、タイミング制約。なければ「特になし」}

## 完了条件
- [ ] {処理完了の確認方法}

## ロールバック手順
{必要な場合の戻し方。不要なら「不要」}
```

### 4. クリーンアップ

Issue作成後、一時ファイルを削除:

```bash
rm docs/temp/issue-body.md
```

### 5. 完了報告

作成したIssueのURLを報告する。

### 6. ユーザー判断待ちを宣言 (AskUserQuestion)

**クリーンアップ (Step 4) と完了報告 (Step 5) を終えた後、最終ステップとして**
`AskUserQuestion` を呼び、PermissionRequest event を発火させて完了報告を
**明示的なユーザー判断待ち状態** として declare する。

> **注:** `AskUserQuestion` を frontmatter の `allowed-tools` に列挙する必要は無い
> (列挙しないこと)。公式 docs によれば `allowed-tools` は pre-approval (列挙ツールを
> 確認 prompt 無しで使う許可) であって利用可能ツールの制限ではないため、未列挙でも
> `AskUserQuestion` は呼べる。むしろ awaiting 化は AskUserQuestion 由来の
> PermissionRequest event に依拠するため、pre-approve すると当該 event が抑制され
> awaiting が働かなくなる懸念がある。create-pr skill も同様に未列挙。

これにより `PermissionRequest` event が発火する。**本 skill 自体は視覚的な通知機構を
持たない**。応答待ちの可視化は環境側 (statusline / hook / 外部オーケストレータ) に
委ね、それらが無い環境では `AskUserQuestion` による停止そのものが合図になる。

呼び出し例:

```text
AskUserQuestion({
    questions: [
        {
            question: "issue #<番号> を作成しました。確認しますか?",
            header: "issue完了",
            multiSelect: false,
            options: [
                {label: "確認する", description: "issue 内容を確認する"},
                {label: "後で", description: "他作業を続ける"}
            ]
        }
    ]
})
```

ユーザーが「Other」で自由入力すれば skill のフローから自然に抜けられる。どの選択肢を
選んでも `UserPromptSubmit` が発火し、awaiting 表示は解除される (選択肢の違いは Claude
側の次アクションの参考情報であり、awaiting 解除自体はユーザーが何か入力した時点で共通に
起きる)。

## 注意事項

- `docs/temp/` は `.gitignore` に含まれていないため、削除忘れに注意
- Issue本文を `--body` で直接渡す方法は使わない
- 関連するIssueやPRがある場合は本文内でリンクする
- **種別ラベル (`bug` / `enhancement` / `ops`) は Step 2 で必ず付与する**（手動で `--label` を追加する必要はない）
- 追加のラベルやアサインが必要な場合は `--label` `--assignee` オプションを併用する
- **Issue は別エージェントが対応する前提で作成する**: テンプレートの各セクションを可能な限り埋め、セッションメモリに依存しない自己完結した Issue にすること
