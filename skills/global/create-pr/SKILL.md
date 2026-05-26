---
name: create-pr
description: 現在のブランチから PR を作成し、base 同期・ブラウザテスト・別エージェントによるセルフレビューを「指摘が無くなるまで (最大 5 巡)」自己完結で実行する。「PR作成して」「PRを作って」のような自然言語で起動。一時ファイル経由で PR 本文の # 行問題を回避。
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, Agent, mcp__playwright__browser_navigate, mcp__playwright__browser_click, mcp__playwright__browser_type, mcp__playwright__browser_evaluate, mcp__playwright__browser_resize, mcp__playwright__browser_take_screenshot, mcp__playwright__browser_snapshot, mcp__playwright__browser_tab_select, mcp__playwright__browser_console_messages
---

# プルリクエスト作成

「PR 作って」と言われたら、その PR を **「独立セルフレビューで指摘が無くなった (= auto-fix が 0 件) 状態」** にして戻す。最大 5 巡まで自動で回す。

途中で人間の判断が必要なのは:

- コンフリクトの意味的解消が必要なとき
- レビュー指摘がブロッカー (Must-fix) / セキュリティ影響 / トレードオフ / 仕様判断のとき
- ブラウザテストが 3 回連続で失敗したとき
- ブラウザテストで回帰が出たとき

それ以外は全自動で進める。**「指摘 0 件で自然終了」が基本ゴール、5 巡到達は警戒シグナル** (修正が新たな問題を呼んでいる / レビュアーが新しい観点を毎巡見つけて収束しない可能性)。

## 短縮禁止

**「小さい修正だから」「diff が少ないから」という理由で、Step 6 のレビュー構成 (Reviewer A / B 2 名並列 + Fact-checker 1 名) や巡数上限 (5 巡) を独断で短縮することは禁止する**。

### 適用範囲

本ルールが禁止対象とするのは **Step 6 のレビュー構成と巡数上限の独断短縮のみ**。skill 内に明記された条件付き skip パス (Step 3 のブラウザテスト起動失敗時 skip、Step 6.4 の escalate 検出時中断等) は本ルールの対象外であり、明記された条件で正規に skip / 中断する。

「短縮」とは構成や上限の **下振れ方向** (削減方向) を指す。上振れ (レビュアーを 3 名以上に増やす等) は本ルールの対象外だが、想定外の挙動を生むので推奨もしない。

### 理由

- 修正のコード量と影響範囲は比例しない。1 行の変更でも race condition / セキュリティ脆弱性を生むことはある (実例: わずか 1 行の変更で 2 巡目に `os.replace` の inode race を独立レビュアーが発見したケース、1 行の修正に 1 巡目で shell injection が見つかったケースがある)
- 「簡素な修正は本当に簡素なら自然に 1-2 巡で収束する」のがこの skill の終了条件 (auto-fix 0 件で break) の意図。短縮判断を呼び出し側に持ち込むと、その判定基準自体がブレて一貫性が損なわれる (撤回後 2 巡で自然終了した実証例がある)
- 過剰な巡数を恐れて短縮するくらいなら、終了条件を信じて回す方が安全

### 具体的に禁止される行動

- Reviewer A / B 2 名並列起動を 1 名に減らす (常に 2 名 + Fact-checker 1 名 = 3 エージェント並列で起動)
- Fact-checker subagent を「面倒だから」省略する (Step 6.2.3 の parent pre-classification は **前段処理として常に実施した上で**、Step 6.2.4 の Fact-checker subagent も **残指摘について必ず起動** する。parent 処理は subagent の代替ではない)
- 「1 巡で終わらせる前提」で 2 巡目以降のレビュー実施判断をスキップする (auto-fix 0 件で自然 break するまで毎巡レビューを起動する)
- 「これは些細だから」と escalate 候補を勝手に auto-fix 扱いに格下げ
- 逆方向 (短縮の対称) として **「auto-fix 可能な指摘を不必要に escalate に格上げして 2 巡目以降を打ち切る」のも禁止**。Step 6.3 の分類基準に厳密に従う

例外: **無し**。skill の流れ通りに必ず実施する。

---

## 手順

### Step 1: 状態確認

最初に base ブランチ名を変数化 (以降の全 Step で `$BASE` を使う):

```bash
BASE=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's@^origin/@@')
if [ -z "$BASE" ]; then
    # origin/HEAD が無い場合、main / master の順で remote 上の存在を確認
    if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then
        BASE=main
    elif git ls-remote --exit-code --heads origin master >/dev/null 2>&1; then
        BASE=master
    else
        BASE=main   # 最終フォールバック
    fi
fi
```

以下を並列で実行:

```bash
git status
git diff --staged && git diff
git log "$BASE"..HEAD --oneline
git diff "$BASE"...HEAD --stat
```

### Step 2: base 同期 + コンフリクト解消

PR を立てた後にコンフリクトで CI が落ちるのを防ぐため、push 前に必ず確認する。

```bash
git fetch origin "$BASE"
BEHIND=$(git rev-list --count HEAD.."origin/$BASE")
REBASED_THIS_STEP=false
if [ "$BEHIND" -gt 0 ]; then
    if git rebase "origin/$BASE"; then
        REBASED_THIS_STEP=true   # 成功
    else
        # コンフリクト検出。続きの分岐は下の「コンフリクト時の対処」へ。
        # スクリプトを盲目的に続行させない。
        :
    fi
fi
```

**コンフリクト時の対処:**

- **自動解消できるケース** (lock ファイル / 自動生成物 / インポート順序のみ / 自分の変更だけが残せば良い等):
  - 解消して `git add <file>` + `git rebase --continue`
- **意味的解消が必要なケース** (同じ関数を両側で別意図に変更等):
  - 解消案を提示して **ユーザー確認を取る** (skill 内で唯一の停止許容ポイント)
  - ユーザーが **続行**: 解消後 `git rebase --continue`
  - ユーザーが **中止**: `git rebase --abort` で安全に元の HEAD に戻し、skill 全体を停止して報告

rebase 後の push は Step 4 で `--force-with-lease` を使う。

### Step 3: ブラウザテスト実施 (条件付き)

#### 実施判定 (OR 条件)

以下のいずれかに該当すれば **必ず実施** (判定の skip は禁止):

1. **test plan / PR 本文素案にブラウザ系キーワード**: `ブラウザ` / `画面` / `UI` / `Playwright` / `画面遷移` / `ボタン` / `表示` (使用フレームワーク名があれば併せて加える)
2. **diff に画面ファイル**: ビュー / フロントエンドコンポーネントの変更
   - 例 (自プロジェクトの構成に読み替え): `*.vue`, `*.tsx`, `*.jsx`, `*.svelte`, `resources/views/**`, `resources/js/**`, `src/**` のコンポーネント、テンプレートエンジンのビューファイル等

判定は以下で機械的に行う (パターンは自プロジェクトのビュー / コンポーネント拡張子・配置に読み替える):

```bash
# diff 解析 (例。プロジェクトのビュー/コンポーネントのパターンに調整する)
git diff --name-only "$BASE"...HEAD | grep -E '\.(vue|tsx|jsx|svelte)$|^(resources/views|resources/js|src/.*components?)/'
```

#### 実行

1. **dev server 起動確認**: プロジェクト固有の起動コマンドは CLAUDE.md / `.env` / `docker-compose.yml` / `package.json` 等を確認して判断。停止していたら起動する
   - 起動コマンドが特定できない / 3 回試行しても URL に到達できない場合は、**Step 3 全体を skip し、その旨を Step 7 の最終報告で明示**。skill 全体は escalate せず通常フローを継続
2. **URL 推測 → 検証**: test plan 項目 + 変更画面 (ルーティング定義から逆引き) で `mcp__playwright__browser_navigate`
3. **操作・検証**: 必要に応じて `mcp__playwright__browser_click` / `browser_type` / `browser_snapshot`
4. **テストデータ作成も OK**: 検証に必要ならプロジェクトの seeder / factory / 直接 DB 投入で作成して良い。**ただし本番系 / 破壊的操作 (truncate / drop / DB 全リセット等) は禁止**
5. **失敗時のリトライ**:
   - 1 件でも失敗したら **修正してリトライ**
   - **同一ケースが** 3 回連続失敗したら **ユーザーに報告して停止** (別ケースの失敗とは合算しない)
6. **証跡の保存**:
   - 全成功したらスクリーンショットを `docs/images/` に保存
   - PR 本文の「動作確認スクリーンショット」セクションに自動引用 (`?raw=true` 形式)

### Step 4: リモートへプッシュ

3 ケースを **排他的に** 分岐する (上から順に判定):

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
HAS_UPSTREAM=$(git rev-parse --abbrev-ref "$BRANCH@{u}" 2>/dev/null || echo "")

if [ -z "$HAS_UPSTREAM" ]; then
    # ケース A: 新規ブランチ (upstream 未設定)
    # rebase 済みでも未済でも -u で初回 push が必要。force-with-lease は
    # upstream が無い状態では意味を持たないので使わない。
    gh auth setup-git && git push -u origin "$BRANCH"
elif [ "$REBASED_THIS_STEP" = true ]; then
    # ケース B: 既存ブランチ + Step 2 で rebase 済み
    git push --force-with-lease
else
    # ケース C: 既存ブランチ + rebase 不要
    git push
fi
```

### Step 5: PR 本文の作成

**重要: `gh pr create --body` にヒアドキュメントで直接渡さないこと。**

PR 本文に `##` などの `#` で始まる行が含まれると、Claude Code のセキュリティチェックで許可確認が発生する。
これを回避するため、**必ず一時ファイル経由で `--body-file` を使用する。**

一時ファイルの配置先: `docs/temp/pr-body.md`

```bash
# Write ツールで docs/temp/pr-body.md を作成
# ↓
gh pr create --title "<タイトル>" --body-file docs/temp/pr-body.md
# ↓
rm docs/temp/pr-body.md  # クリーンアップは Step 8
```

#### PR 本文フォーマット

- タイトルは 70 文字以内

##### 基本フォーマット

```markdown
## Summary
- 変更内容の要約（1〜3行）

## Test plan
- [ ] テスト項目

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

##### Issue 対応時の追加ルール

- 本文の `🤖 Generated with...` 行の **直前** に `Closes #<issue 番号>` を追加
- 成果物にドキュメント（設計資料、仕様書、ADR 等）が含まれる場合は「成果物リンク」セクションを追加
  - リンク形式: `https://github.com/<owner>/<repo>/blob/<branch>/<path>`
  - drawio や SVG ファイルは Markdown に埋め込まれているためリンク不要
- 印刷物がある場合は「印刷イメージ」セクションにスクリーンショットを掲載
  - スクリーンショットは `docs/images/` 配下にコミットし、`https://github.com/<owner>/<repo>/blob/<branch>/<path>?raw=true` 形式の URL で参照（`?raw=true` はプライベートリポジトリでの画像直リンクに必須。public repo でも害はないので一律この形式で良い）
- Step 3 でブラウザテストを実施した場合、「動作確認スクリーンショット」セクションに同形式でスクリーンショットを掲載

```markdown
## Summary
- 変更内容のサマリ

## 成果物リンク
（ドキュメント成果物がある場合のみ）

## 印刷イメージ
（印刷するものがある場合のみ）

## 動作確認スクリーンショット
（Step 3 でブラウザテスト実施した場合）

## 対応履歴
（Step 6 セルフレビュー実施後、毎巡 Step 6.4.5 で追加・更新する。実施前は省略）

## Test plan
- テスト内容

Closes #<issue 番号>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

##### 「対応履歴」セクションテンプレート

Step 6.4.5 で巡ごとに追記する。実施しなかった巡は記載しない:

```markdown
## 対応履歴

### 1 巡目 (commit <SHA>)
- レビュアー: 2 名 / Fact-checker: 1 名
- agreement 2/2: <件数> 件
- agreement 1/2: <件数> 件
- 分類: auto-fix <件数> / silent-reject <件数> / escalate <件数>
- 主な auto-fix: <短い箇条書き 2-3 件>
- silent-reject 内訳: <件数> 件 (主な理由: 事実誤認 N 件 / 主観 1 票 N 件)
- escalate (あれば): <内容>

### 2 巡目 (commit <SHA>)
...
```

### Step 6: auto-review/fix ループ (指摘 0 件まで / 最大 5 巡)

PR 作成直後、セルフレビューに入る。**指摘 (auto-fix 対象) が 0 件になる
ことが基本ゴール**。安全弁として最大 5 巡で打ち切る。

**重要原則**:

1. レビューは **必ず別エージェント (Agent ツール経由) で実行する**。
   コードを書いた自分自身でレビューするとバイアスが残るため。
2. レビューは **「2 レビュアー + 1 ファクトチェッカー」の 3 エージェント
   構成** で実行する。役割分離により誤指摘 (subagent が公開ドキュメント
   由来の誤った前提で指摘する等) を systematic に弾ける:
   - **Reviewer A / B**: 並列で独立にレビュー。観点が重なっても OK
     (2/2 一致は高信頼シグナル)
   - **Fact-checker**: A+B の指摘リストを受け取り、各指摘の事実主張
     (関数の存否 / 行番号 / ツール名 / 既出か否か等) を verify。
     誤りと判定したものは silent-reject 候補としてマーク
3. 3 エージェントとも親セッションの文脈を渡さず、PR 番号だけ渡して
   diff から純粋に評価させる。
4. レビュー agent (Reviewer A / B / Fact-checker) は **必ず
   `isolation: "worktree"` で spawn し、かつプロンプトで作業ツリーの
   変更を禁止する (二重防御)**。理由: Agent (subagent) は `isolation`
   を指定しない限り親と cwd / git 作業ツリーを共有する。`~/.claude/*`
   がリポ作業ツリーへの symlink で配布される dotfiles 環境では、
   subagent が「実機テスト」のつもりで `git checkout` /
   `gh pr checkout` すると **ライブ設定 (settings.json / hooks) ごと
   別ブランチ版にリバートされてしまう** (共有作業ツリーでのブランチ
   切替で稼働中の設定が壊れた事例が実際にある)。worktree
   分離で親ツリーを物理的に守り、プロンプト制約で checkout 自体を抑止
   する。レビューは `gh pr diff` / `gh pr view` のみで完結するため、
   作業ツリーの書き換えは本来不要。

```
iteration = 1
while iteration <= 5:
    # 6.1 base 再同期 (他 PR が間に入った場合に対応)
    git fetch origin "$BASE"
    BEHIND=$(git rev-list --count HEAD.."origin/$BASE")
    if [ "$BEHIND" -gt 0 ]:
        git rebase "origin/$BASE"   # コンフリクト時は Step 2 と同じ規則
        # rebase 後はローカルと remote が分岐するので force-with-lease 必須。
        # ただし HEAD と upstream が一致していれば push 不要 (二重 push 防止)。
        if [ "$(git rev-list --count @{u}..HEAD)" -gt 0 ]:
            git push --force-with-lease
        REBASED_THIS_ITERATION = True
    else:
        REBASED_THIS_ITERATION = False

    # 6.2 レビュー実行: 2 レビュアー + 1 ファクトチェッカーの 3 段構成

    事前に owner/repo を取得:
        OWNER_REPO=$(gh repo view --json owner,name -q '.owner.login + "/" + .name')

    ## 6.2.1 Reviewer A と Reviewer B を並列起動
    1 メッセージで Agent ツールを 2 つ並列に呼ぶ (single message, multiple tool calls)。
    両者とも同じプロンプトを与えるが、独立な subagent なので結果は別個に出る:

        Agent(
            description = f"Independent reviewer A of PR #{N}",
            subagent_type = "general-purpose",
            isolation = "worktree",   # 親の作業ツリーを汚さない (重要原則 4)
            prompt = REVIEWER_PROMPT  # 下記 (REVIEWER_PROMPT 参照)
        )
        Agent(
            description = f"Independent reviewer B of PR #{N}",
            subagent_type = "general-purpose",
            isolation = "worktree",   # 親の作業ツリーを汚さない (重要原則 4)
            prompt = REVIEWER_PROMPT
        )

    REVIEWER_PROMPT (f-string で補間してから渡す):
        """
        PR #{N} ({OWNER_REPO}) をコードレビューしてください。
        事前知識・親セッションの議論は一切持っていないものとして、
        純粋に diff と PR 本文だけから判断してください。

        ## 重要な制約 (作業ツリーを変更しないこと)
        レビューは read-only。評価は `gh pr view` / `gh pr diff`
        (必要なら `gh api` での read-only なコード取得) のみで行うこと。
        **`git checkout` / `git switch` / `git branch` 作成 /
        `gh pr checkout` 等で作業ツリーや HEAD を変更してはならない**。
        PR をローカル展開しての「実機テスト」も禁止 (このリポジトリは
        設定ファイルが symlink 配布されており、ブランチ切替が稼働中の
        ライブ環境を破壊する)。diff の評価だけで判断すること。

        1. `gh pr view {N} --repo {OWNER_REPO} --json title,body,additions,deletions`
        2. `gh pr diff {N} --repo {OWNER_REPO}`
        3. 以下の観点で指摘事項を列挙:
           - コード正当性 (バグ / ロジック誤り)
           - セキュリティ (認証認可 / サニタイズ / 秘密漏洩 / 権限昇格)
           - パフォーマンス (N+1 / 不要ループ / メモリ過剰)
           - プロジェクト規約適合
           - テスト網羅
           - 命名 / 可読性 / 不要 import / typo
        4. 各指摘に以下のマークを付ける:
           主マーク (必ず 1 つだけ付与):
             - [Must-fix]: ブロッカー (バグ / 機能不全 / 仕様判断ミス)
             - [Should-fix]: 完成度向上
             - [Nice-to-have]: 任意改善
           付加マーク (主マークに併記可。0 個以上):
             - [Security]: セキュリティ影響あり (重大度問わず付ける)
             - [Tradeoff]: 性能 vs 可読性等の判断を要するもの
           例: "[Should-fix][Security] パスワードがログ出力されている"
               "[Must-fix] N+1 で 1000 件超のクエリが発生"
        5. 報告は「ファイルパス:行番号 — マーク — 内容 — 推奨アクション」
           の形で構造化して返す
        6. 1 つの finding につき 1 行にまとめ、指摘番号 (R-1, R-2, ...) を
           付けて返す。後段のファクトチェック / 集約処理がパースしやすい
           ようにするため
        """

    ## 6.2.2 Reviewer A / B の結果をマージ
    2 レポートを文字列で受け取り、以下を実施:
      - 各 finding をパース → {id, file, line, marks, content, action}
      - file + 近傍行 + 主題 が一致する finding 同士を 1 クラスタにまとめる
      - 各クラスタに agreement = 2 (両者ヒット) または 1 (片方のみ) を付与
      - クラスタごとに代表 finding (より具体的な記述の方) を採用
    結果として、重複排除済みかつ agreement count 付きの finding リスト
    `FINDINGS_RAW` を得る

    ## 6.2.3 Pre-classification by parent (tool-existence claims)

    Fact-checker (subagent) に投げる前に、**親しか確実に検証できない事実
    主張** は親が直接処理する。これは重要な設計原則:

    > Subagent は自分の toolset しか見えず、親の toolset は推測でしか
    > 答えられない。tool-existence 系の主張 ("X ツールは存在しない /
    > 正しい名称は Y" 等) を fact-checker に投げると、subagent が
    > 自分の手元の deferred tool 一覧 (TaskCreate 等) を見て「Agent は
    > 存在しない、Task が正しい」のように confidently false-verify する。

    親による事前処理対象:
    - 「ツール X が存在しない / 別名 Y が正しい」
      → 親は自分の system prompt / 利用可能 tool list を直接観測できる
      → 親が「実在する」と確認できれば即座に silent-reject 候補にマーク
    - 「親が今回のセッションで実際に使ったツール / コマンドが間違い」
      → 親が直近の tool 履歴 / コマンド成功事実から判断、誤指摘なら silent-reject

    残りの事実主張 (diff 内の行番号 / ファイル存否 / PR 本文乖離等) を
    fact-checker subagent に渡す。

    ## 6.2.4 Fact-checker を 1 つ起動 (親 pre-classification 後の残りについて)
    FINDINGS_RAW から「親が処理済み」のものを除いた指摘を渡して verify させる:

        Agent(
            description = f"Fact-check of PR #{N} review findings",
            subagent_type = "general-purpose",
            isolation = "worktree",   # 親の作業ツリーを汚さない (重要原則 4)
            prompt = FACTCHECK_PROMPT
        )

    FACTCHECK_PROMPT (`{N}` 等は実値に置換して prompt 引数に渡す):
        """
        PR #{N} ({OWNER_REPO}) について、レビュアーから得られた
        以下の指摘リストの **事実主張のみ** を検証してください。
        設計判断 / 主観評価は対象外です。

        ## 重要な制約 (作業ツリーを変更しないこと)
        検証は `gh pr view` / `gh pr diff` / `gh api` での read-only な
        取得と Read のみで行うこと。**`git checkout` / `git switch` /
        `git branch` 作成 / `gh pr checkout` で作業ツリーや HEAD を
        変更してはならない** (このリポジトリは設定ファイルが symlink
        配布されており、ブランチ切替が稼働中のライブ環境を破壊する)。
        PR をローカル展開しての検証も禁止。read-only 取得だけで判断する。

        ## 検証する事実主張の例
        - 「関数 / シンボル / ファイル X が無い」
          → gh pr diff の該当箇所を再確認、または gh api でコード取得
        - 「行番号 X の記述が無い / と異なる」
          → diff の該当行を再確認
        - 「PR 本文に X が書かれていない」
          → gh pr view で再取得して確認
        - 「既出 (前巡で対応済)」
          → コミット履歴 / 現状コードを Read で確認

        ## 検証対象外 (NG)
        - 「ツール X は存在しない / Y が正しい名称」のような **subagent の
          手元 toolset から推測する主張** は対象外。あなたの toolset は
          親エージェントと異なるため、結論できません。「n/a」を返す。

        ## 手順
        1. `gh pr view {N} --repo {OWNER_REPO}` / `gh pr diff {N} --repo {OWNER_REPO}`
           で最新情報を取得
        2. 渡された各 finding について:
           - 含まれる事実主張を抜き出す
           - 上記方法で verify
           - "verified" (事実合致) / "false-claim" (事実誤り) / "n/a"
             (事実主張なし / 検証範囲外 / 主観判断のみ) のいずれかでマーク
        3. false-claim の場合、根拠となる現状の事実を 1-2 行で添える

        ## 返答フォーマット
        指摘番号ごとに 1 行:
          F-<id> — <verified|false-claim|n/a> — <根拠 or 補足>

        ## 検証対象の指摘リスト
        {FINDINGS_RAW}   # ← 6.2.2 で得たリストをテキスト化して埋め込む
        """

    ## 6.2.5 Fact-check 結果を FINDINGS_RAW にマージ
    各 finding に factcheck フィールド (verified / false-claim / n/a /
    parent-rejected) を付与。`FINDINGS` という最終リストを得る。これを
    Step 6.3 に渡す。

    重要: Skill ツールで /review を直接呼び出すと同一コンテキスト実行に
    なりバイアスが残るため不可。必ず Agent ツール 3 個 (Reviewer A,
    Reviewer B, Fact-checker) を使う。

    # 6.3 指摘の分類 (FINDINGS = Reviewer A/B 集約 + Pre-class + Fact-check 結果付き)

    各 finding を以下のいずれかに振り分ける:

      ## (i) silent-reject (= 何もしない、Step 7 で件数のみ要約)
        * factcheck == "false-claim"
        * factcheck == "parent-rejected" (6.2.3 で親が tool 実在等を override)
        * agreement == 1 かつ主マーク == [Must-fix] かつ factcheck != "verified"
          (= 単独票の重大主張が事実確認できない = ハルシネーション疑い、保留)

      ## (ii) escalate (= ユーザー確認が必要、真に判断分岐するもの)
        * 修正でユーザーの過去の意図的な選択を覆すおそれ (例: revert)
        * データ整合性 / マイグレーション影響あり
        * アーキテクチャ判断 / 公開 API の breaking change
        * 仕様判断 (要件解釈で複数の正解がありうる)
        * 付加マーク [Tradeoff] 明示あり
        * [Security] かつ修正方針が複数 (例: 「MD5 → bcrypt 移行戦略」)

      ## (iii) auto-fix (= 自動修正対象、上記以外すべて)
        * 主マーク不問。判断分岐しないなら [Must-fix] でも auto-fix。
        * agreement == 2 (2 名一致) は信頼性高、優先的に auto-fix
        * agreement == 1 でも factcheck == "verified" なら auto-fix
        * **agreement == 1 かつ factcheck == "n/a" でも、主マークが
          [Should-fix] または [Nice-to-have] で修正コストが小さいもの
          (typo / 命名 / 不要 import / コメント補足 / 表記揺れ等) は
          auto-fix する**。閾値を過度に厳しくすると有用な提案を取りこぼす
        * 例: typo / 命名 / 不要 import / 検証追加 / コメント補足 /
              ハードコード値の定数化 / 明らかなバグの単純修正 /
              [Security] だが対応方針が一意 (例: 「ハードコード API
              キーを env 変数に移す」)

    silent-reject した指摘は subagent に問い合わせず、Step 7 で
    「false-positive: 件数 + 主な内訳」として要約報告するだけにする。
    1 巡ごとに些末な事実誤認でユーザー判断を仰ぐのは自動化の意味を損なう。

    # 6.4 修正実行
    if escalate が 1 件以上:
        以降のループを中断して Step 7 に進む (escalate の内訳を報告)

    if auto-fix が 0 件:
        break  # レビュー OK、ループ終了

    auto-fix を全件実装 (Edit / Write)
    git add <変更ファイル>
    # commit message はプロジェクトの規約に合わせる
    # (日本語 OK のリポなら日本語、英語規約なら英語)
    git commit -m "chore: <iteration> 巡目レビュー指摘反映"

    # push 種別の分岐:
    if REBASED_THIS_ITERATION:
        git push --force-with-lease
    else:
        git push

    # 6.4.5 PR 本文を最新状態に更新 (毎巡必須)
    # 次巡のレビュアーが古い情報で評価しないようにするため、push と同時に
    # PR 本文も Step 5 のフォーマットに沿って書き直す。
    docs/temp/pr-body.md を最新内容で書き直す:
      - 既存の Summary / 設計判断 / 維持されたノウハウは保持
      - 「対応履歴」セクションを追加または更新し、今巡の auto-fix / escalate /
        silent-reject の件数と主な内訳を 3-5 行で要約
      - Test plan のチェック状態も最新化 (完了項目は [x])
    gh pr edit {N} --body-file docs/temp/pr-body.md
    rm docs/temp/pr-body.md

    # 6.5 ブラウザテストの再走査 (UI 影響のある修正のときのみ)
    # 判定対象は今巡 (= 直近 commit) で変更されたファイルのみ:
    #   git diff HEAD~1 HEAD --name-only
    # UI 影響あり判定 (いずれか満たせば再走査):
    #   (a) パス判定: Step 3 の拡張子/ディレクトリパターンに該当
    #   (b) スタイル系: *.css, *.scss, スタイル設定ファイルに変更あり
    #   (c) ルーティング系: ルーティング定義ファイルに変更あり
    #   (d) コンポーネントの class 属性 / utility class の追加削除を
    #       diff 内で目視確認 (`class=` または ` class:` の変更行あり)
    if Step 3 で実施していた AND (a または b または c または d):
        全ケースを再走査
        失敗したら escalate して Step 7 に進む
    # 以下は完全 skip (= 正常な終了パス、escalate しない):
    # - Step 3 を未実施だった PR (画面変更なし判定)
    # - 今巡の auto-fix が typo / import 整理など UI に無関係なもののみ

    iteration += 1
```

#### ループ終了条件

| 終了原因 | 振る舞い |
|---|---|
| auto-fix が 0 件のレビューが返った | ループを break、Step 7 へ (理想形) |
| 5 巡完了 | ループを抜けて Step 7 へ (警戒シグナル: 指摘が収束していないので、報告で残課題と巡ごとの件数推移を強調) |
| escalate を検出 | 即中断して Step 7 へ |
| ブラウザテスト回帰失敗 | 即中断して Step 7 へ |

### Step 7: 最終報告

以下をまとめて報告:

- PR の URL
- セルフレビュー巡数 (1-5)
- 各巡の auto-fix 件数
- ブラウザテストの実施状況と最終結果
- escalate された指摘 (あれば内容と該当指摘箇所)
- 残コミット履歴の概要

### Step 8: クリーンアップ

```bash
rm docs/temp/pr-body.md
```

`docs/temp/` に他のファイルがある場合があるため、**ディレクトリごと削除しない**。

PR 完成後は Step 7 の最終報告 (PR URL / 巡数 / ブラウザテスト結果 / escalate
内容 / コミット履歴概要) をユーザーに返して終了する。

---

## エスカレーション基準

skill が「ユーザー確認を取って停止する」のは以下のときのみ:

1. **コンフリクトの意味的解消** (Step 2 / Step 6.1)
   - 同じ関数や条件分岐を両側で別の意図に変更している
   - 何を残すかは仕様判断
2. **レビュー指摘のブロッカー / トレードオフ判定** (Step 6.3)
   - 上述の分類表参照
3. **ブラウザテストの 3 回連続失敗** (Step 3 のリトライ条項)
   - 修正で直らない深い問題の可能性
4. **ブラウザテストの回帰** (Step 6.5)
   - 修正で動いていた機能が壊れた

それ以外 (lint 違反 / 命名 / 不要 import / typo / 軽微なリファクタ提案等) は **すべて自動修正する**。

---

## ブラウザテスト実施判定基準

以下のいずれかが true なら **必ず実施**:

- PR 本文 (素案でも可) / test plan / 変更ファイル名・パス に画面系キーワード (`ブラウザ` / `画面` / `UI` / `Playwright` / `画面遷移` / `ボタン` / `表示`、使用フレームワーク名) が出現
- diff にビュー / フロントエンドコンポーネントファイル (例: `.vue`, `.tsx`, `.jsx`, `.svelte`, `resources/views/**`, `resources/js/**`, `src/**` のコンポーネント。自プロジェクトの構成に読み替え) が含まれる

判定の skip 判断は不要。両条件が false でも実施したほうが安心な場合は実施して構わない。

---

## 注意事項

- push は必ず `gh` 経由 (SSH 鍵なし)。`gh auth setup-git` を先に走らせる
- `docs/temp/` は `.gitignore` 対象外なので Step 8 で必ず掃除
- PR 本文を `--body` で直接渡す方法は使わない (`#` 行問題)
- rebase 後の push は `--force-with-lease` (`--force` は禁止)
- セルフレビューループ中の commit message は短くて良い (`chore: <N> 巡目レビュー指摘反映` 等)、プロジェクトの commit 規約 (日本語 / 英語) に合わせる。squash は後で人がやる
- **指摘 0 件で自然終了 = 基本ゴール / 5 巡到達 = 警戒シグナル** (修正が新たな問題を呼んでいる、またはレビュアーが毎巡新しい観点を出し続けて収束しない可能性大)。Step 7 の報告では 5 巡到達ケースの「巡ごとの auto-fix 件数推移」と「残課題」を強調すること
