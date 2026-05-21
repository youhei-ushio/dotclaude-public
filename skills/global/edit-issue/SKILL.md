# GitHub Issue 編集

既存の GitHub Issue の本文を編集、またはコメントを追記する。一時ファイル経由で `--body-file` を使い、`#` 行による許可確認を回避する。

## 起動トリガー

- 「issue を編集して」
- 「issue 本文を更新して」
- 「issue NNNN を更新して」
- 「issue 本文に追記して」
- 「issue にコメントして」
- 「issue NNNN にコメント追加して」
- 「issue に方針を追記」（コメントとして追記する場合）

## 一時ファイル置き場

本文・コメント本文を直接 `--body` に渡すと `#` 行が許可確認を引き起こすため、必ず一時ファイルに書き出して `--body-file` で渡す。

- 一時ファイルは **`docs/temp/`** 配下に置く（`Write(docs/**/*.md)` で許可済みのため追加設定不要）
- `/tmp/` への書き込みは CWD 相対展開の都合で許可パターンが効きづらく、毎回プロンプトが出る
- 使い終わったら必ず `rm` で削除する（`docs/temp/` は `.gitignore` 対象外）

## 手順

### 本文を編集する場合

#### 1. 現在の Issue 本文を取得

ラッパースクリプト経由で本文を一時ファイルに保存（`>` リダイレクトを許可パターンに合致させるため）:

```bash
~/.claude/skills/edit-issue/fetch-body.sh <issue-number>
```

- 既定の出力先: `docs/temp/issue-body.md`（カレントディレクトリ相対）
- 出力先を変えたい場合は第2引数で指定
- スキル本体はユーザーレベル配置のため、すべてのプロジェクトで利用可能

#### 2. 本文を編集

Edit ツールで `docs/temp/issue-body.md` の必要箇所を変更する。

- 元の構造・section を可能な限り保つ
- 追記の場合: 追記する位置を明確にして Edit で部分更新
- 全面書き換えの場合: Write で上書き

#### 3. 編集後の本文を Issue に反映

```bash
gh issue edit <issue-number> --body-file docs/temp/issue-body.md
```

#### 4. 一時ファイルを削除

```bash
rm docs/temp/issue-body.md
```

#### 5. 完了報告

更新した Issue の URL と変更点の要約を伝える。

---

### コメントを追記する場合

#### 1. コメント本文を一時ファイルに書く

Write ツールで `docs/temp/issue-<番号>-comment.md` を作成する。

- ファイル名に Issue 番号を含めると、複数 Issue 並行作業時に衝突しない
- 本文に `## 見出し` や `# 行` を含めても問題ない（`--body-file` で渡すため）

#### 2. コメントを投稿

```bash
gh issue comment <issue-number> --body-file docs/temp/issue-<番号>-comment.md
```

成功すると、追記したコメントの URL が返る。

#### 3. 一時ファイルを削除

```bash
rm docs/temp/issue-<番号>-comment.md
```

#### 4. 完了報告

返ってきたコメント URL と追記内容の要約を伝える。

## 注意事項

- 本文に `##` などの `#` 行が含まれるため、`gh issue edit --body` / `gh issue comment --body` には直接渡さない（許可確認が出る）。**必ず `--body-file` を使う**
- 一時ファイルは `docs/temp/` 配下に置く（許可済みパスのため確認プロンプトが出ない）
- `docs/temp/` は `.gitignore` 対象外のため、削除忘れに注意（PR 作成前に必ずクリーンアップ）
- ラベル変更は `gh issue edit <num> --add-label / --remove-label` を別途使用
- タイトル変更は `gh issue edit <num> --title "新タイトル"` を別途使用
- 並行で複数Issueを編集する場合は出力先ファイル名を分ける（`fetch-body.sh N file.md`）

## 関連スキル

- `create-issue`: Issue を新規作成（同様に temp file + body-file パターン）
- `create-pr`: PR を新規作成
