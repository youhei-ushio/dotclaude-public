# review-only モード: GitHub 投稿手順

本ファイルは `review-pr` skill の Step 6.6 (review-only モードのみ) の詳細手順。
SKILL.md のループ後処理から参照される。**fix モードでは本ファイルを読む必要はない**。

---

## Step 6.6: GitHub に summary review コメントを投稿 (review-only モードのみ)

**fix モード時は本 Step 全体を skip して Step 7 へ**。

review-only モードで Step 3 の `report` バケットに振り分けた findings を集約
して、`gh pr review --comment --body-file` で投稿する。投稿前に必ず
**ユーザー承認** を取る (`gh pr review --comment` は collaborator に通知が
飛び、PR レビュー履歴に永続記録される。API での削除は技術的には可能だが、
UI からは手動操作が必要で、いったん見た / 通知を受け取った相手の印象を
取り消すことはできない)。

### 6.6.1 コメント markdown の生成

書き出し先ディレクトリは Step 0.2 で `mkdir -p "$REPO_ROOT/docs/temp"` 済み。

`$REPO_ROOT/docs/temp/pr${N}-review-comment.md` に書き出す (ファイル名の `${N}` は
親エージェントが PR 番号に展開してから Write する。以下テンプレート内の
`{N}` / `{BASE}` 等の **波括弧プレースホルダ** も同様に展開してから書き出す
こと。GitHub Markdown で `<...>` を使うと未知 HTML タグとして strip される
可能性があるため、テンプレでは `<N>` ではなく `{N}` 形式を使う):

```markdown
## レビュー結果

PR #{N} を読みました。

### Must-fix (X 件)
- `{file}:{line}` — {内容} — {推奨アクション}
- ...

### Should-fix (X 件)
- `{file}:{line}` — {内容} — {推奨アクション}
- ...

### Nice-to-have (X 件)
- ...

### 質問 / 要確認 (X 件)
- `{file}:{line}` — {内容} (主マーク {Must-fix/Should-fix/...} + 単独票・要事実確認 / 付加マーク [Tradeoff]) — {推奨アクション}
- ...

### 補足
- レビュー方式: {DEPTH} ({起動ロール名}) + Analyst、worktree 隔離
- 内部 silent-reject: {N} 件 (内訳: false-claim {N} 件 / parent-rejected {N} 件 / その他 {N} 件)
- base ({BASE}) 比 BEHIND: {N} コミット (rebase は author 側で対応をお願いします)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

**section 振分の規約** (主マーク = 1 個必須、付加マーク = 0 以上):

- **主マーク section** (`Must-fix` / `Should-fix` / `Nice-to-have`):
  各 finding は **主マーク 1 個に応じた section** に入れる。
  付加マークの `[Security]` は **行内に明示** (例: `[Security] パスワードが
  ログ出力されている` の prefix を付ける)。`[Tradeoff]` 付き finding は
  **「質問 / 要確認」section に振替** (主マーク section には載せない)。
- **「質問 / 要確認」section**:
  以下の 2 種を集約する:
  - Step 3 review-only 分類で `[Question]` 振替された finding
    (単独票 [Must-fix] + factcheck unverified)
  - 付加マーク `[Tradeoff]` 付きの finding (主マーク不問)

件数 0 の section は省略する。各 finding は元の `R-<id>` を保持しなくて
よい (内部 ID なので external には意味がない)。「単独票 [Must-fix] の保留」
は前述の [Question] 振替により review-only では原則発生しないので、補足の
silent-reject 内訳には載せない (false-claim / parent-rejected が主因)。

### 6.6.2 ユーザー承認

集約 markdown の全文を表示してから、承認を求める。**確認文には必ず以下の
ガード文言を含める**: 「**投稿すると collaborator に通知が飛び、PR レビュー
履歴に永続記録されます (API での削除は技術的には可能ですが、UI からは手動操作が
必要で、いったん見た / 通知を受け取った相手の印象は取り消せません)。本文に
問題ないか最終確認をお願いします**」。

初回 AskUserQuestion 呼び出し例 (options に必ず (a)(b)(c) 3 つを提示):

```text
AskUserQuestion({
    questions: [{
        question: "投稿すると collaborator に通知が飛び、PR レビュー履歴に永続記録されます...本文に問題ないか最終確認をお願いします。",
        header: "投稿確認",
        multiSelect: false,
        options: [
            {label: "投稿する",                  description: "そのまま gh pr review --comment で投稿"},
            {label: "markdown を編集してから投稿", description: "ファイルを手で編集後、再度確認"},
            {label: "投稿せず終了",                description: "Step 7 へ進み、markdown は残置"},
        ]
    }]
})
```

回答ごとの遷移:

- (a) 投稿する → 6.6.3 へ
- (b) markdown を編集してから投稿 → 以下のループを実行:
    ```text
    EDIT_LOOP_MAX = 3   # 連続 (b) 選択の上限。到達したら (c) 扱いで終了
    edit_loop_count = 0
    while True:
        edit_loop_count += 1
        if edit_loop_count > EDIT_LOOP_MAX:
            echo "[review-pr] 編集ループが ${EDIT_LOOP_MAX} 回連続したため (c) 投稿せず終了として扱います"
            POSTED_TO_GITHUB = False
            break    # 6.6.3 を skip して Step 7 へ
        ユーザーに「`docs/temp/pr${N}-review-comment.md` を手で編集して
        完了したら教えてください」と伝えて待機 (会話上の自然な往復)
        ユーザーから完了報告を受領
        編集後の markdown 全文を再表示
        AskUserQuestion で (a)(b)(c) を再提示 (同じ options 構成)
        if 回答 == (a): break    # 6.6.3 へ
        if 回答 == (c):
            POSTED_TO_GITHUB = False
            break    # 6.6.3 を skip して Step 7 へ
        if 回答 == (b): continue    # ループ継続 (上の count++ で増える)
    ```
- (c) 投稿せず終了 → `POSTED_TO_GITHUB` は False のまま 6.6.3 を skip
    (Step 7 へ、markdown ファイルは Step 8 で残置されユーザーが手で
    投稿 / 編集 / 破棄)

### 6.6.3 投稿

承認後に投稿し、成功可否を `POSTED_TO_GITHUB` に反映する:

```bash
if gh pr review "$N" --repo "$OWNER_REPO" --comment --body-file "$REPO_ROOT/docs/temp/pr${N}-review-comment.md"; then
    POSTED_TO_GITHUB=True
    echo "[review-pr] PR #$N に review コメントを投稿しました"
else
    POSTED_TO_GITHUB=False
    echo "[review-pr] gh pr review が失敗しました。markdown は残置するので手動で投稿してください: docs/temp/pr${N}-review-comment.md"
    # ESCALATE_REASON は立てない (投稿失敗を escalate に格上げする運用はせず、
    # Step 7 で投稿失敗ステータスをそのまま報告する)
fi
```

**`--repo "$OWNER_REPO"` の必須化**: 本 skill は **レビュー対象 PR のリポの
clone 内 (cwd) から呼ぶ前提** で、Step 0.2 は `$OWNER_REPO` を cwd の origin
remote から導出する (別リポの PR を cwd 外から扱う経路は無い)。それでも
`gh pr <subcommand> "$N"` を `--repo` 無しで呼ぶと、gh は cwd の remote 設定
(upstream / 複数 remote / fork 元) から PR を独自に解決するため、Step 0.2 の
`$OWNER_REPO` と食い違って別リポの PR に投稿する事故が起きうる。全 MODE の
`gh pr` 系コマンドは Step 0.2 で確定した `--repo "$OWNER_REPO"` を明示する規約
(fix モードの Step 0.3 / 6.5 も同じ)。

`--comment` は中立コメント (Approve / Request changes ではない)。投稿成功
(`POSTED_TO_GITHUB=True`) なら Step 8 で markdown を削除、失敗
(`POSTED_TO_GITHUB=False`) なら残置してユーザーに手動投稿を促す。
いずれの分岐でも Step 7 → Step 8 へ進む。
