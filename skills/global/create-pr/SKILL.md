---
name: create-pr
description: 現在のブランチから PR を作成し、base 同期・ブラウザテスト・PR 本文初期化を行ったあと `review-pr` skill にセルフレビュー (--depth で Correctness/Security/Impact + Analyst、フラグなしで Reviewer A/B + Fact-checker) を委譲し、最後に awaiting 化する。「PR作成して」「PRを作って」のような自然言語で起動。一時ファイル経由で PR 本文の # 行問題を回避。
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, Agent, mcp__playwright__browser_navigate, mcp__playwright__browser_click, mcp__playwright__browser_type, mcp__playwright__browser_evaluate, mcp__playwright__browser_resize, mcp__playwright__browser_take_screenshot, mcp__playwright__browser_snapshot, mcp__playwright__browser_tab_select, mcp__playwright__browser_console_messages
---

# プルリクエスト作成

「PR 作って」と言われたら、その PR を **「独立セルフレビューで指摘が無くなった (= auto-fix が 0 件) 状態」** にして戻す。巡数上限 (ITER_MAX) は `--depth` で決まる (lightweight 1 / full 3 / 指定なし 5) の範囲で自動で回す。

途中で人間の判断が必要なのは:

- コンフリクトの意味的解消が必要なとき
- レビュー指摘がブロッカー (Must-fix) / セキュリティ影響 / トレードオフ / 仕様判断のとき
- ブラウザテストが 3 回連続で失敗したとき
- ブラウザテストで回帰が出たとき

それ以外は全自動で進める。**「指摘 0 件で自然終了」が基本ゴール、ITER_MAX 到達は警戒シグナル** (修正が新たな問題を呼んでいる / レビュアーが新しい観点を毎巡見つけて収束しない可能性。lightweight は 1 巡固定なので該当しない)。

## 短縮禁止

Step 5 で委譲する `review-pr` skill のレビュー構成 (`--depth` 指定時: Correctness / Security / Impact + Analyst、フラグなし: Reviewer A / B 2 名並列 + Fact-checker 1 名) と巡数上限を、create-pr 呼び出し側から独断で短縮してはならない (例: 「小さい修正だから 1 名で」「diff が少ないから 1 巡で」等)。

短縮禁止の **正本・理由・実例・具体的に禁止される行動** は `skills/global/review-pr/SKILL.md` の「短縮禁止」セクション参照。create-pr 側は委譲時に短縮指示を渡さず、review-pr の判定に任せる。

例外: `--depth` フラグによる ITER_MAX・観点の変更は「独断での短縮」に該当しない。これは workflow 設計レベルの決定（Issue の種別に基づくパス分岐）であり、実行時の ad-hoc 判断ではないため。`--depth` フラグは resolve-issue skill が Issue の種別から決定し、create-pr 経由で review-pr に転送する。

---

## 手順

### Step 0: 引数の解析 (`--depth` の受け取り)

本 skill の **`args` パラメータ (Skill ツール)** を解析する。受け取るのは
`--depth lightweight` / `--depth full` のみで、resolve-issue skill が Issue の
種別から決めて渡す (`/create-pr --depth lightweight` 等)。create-pr 単独起動では
指定なし = legacy (全観点、最大 5 巡):

```text
DEPTH_FLAG=""            # Step 5 で /review-pr にそのまま転送する文字列
EXPECT_DEPTH_VALUE=False
for tok in $args:        # 擬似コード: $args を空白区切りでトークン化したものを順に処理
    if EXPECT_DEPTH_VALUE:
        if tok not in ("lightweight", "full"):
            echo "[create-pr] --depth の値が不正です: ${tok} (lightweight | full)"
            中断 (skill return)
        DEPTH_FLAG = "--depth " + tok
        EXPECT_DEPTH_VALUE = False
    elif tok == "--depth":
        if DEPTH_FLAG != "":
            echo "[create-pr] --depth が重複しています"
            中断 (skill return)
        EXPECT_DEPTH_VALUE = True
    elif tok starts with "-":
        echo "[create-pr] 未知のフラグです: ${tok}"
        中断 (skill return)
    else:
        pass   # フラグ以外のトークン (自然言語の補足) は無視する
if EXPECT_DEPTH_VALUE:
    echo "[create-pr] --depth に値がありません (lightweight | full)"
    中断 (skill return)
```

**depth 独自付与の禁止**: create-pr が PR の内容・規模・難易度・変更ファイル種別を
判断して独自に `--depth` を決めることは**禁止**する (短縮禁止セクション参照)。
`DEPTH_FLAG` は `args` から受け取った値だけを持つ。

### Step 1: 状態確認

最初にリポジトリルートと base ブランチ名を変数化 (以降の全 Step で `$REPO_ROOT` / `$BASE` を使う):

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -z "$REPO_ROOT" ]; then
    echo "[create-pr] リポジトリルートを解決できません。git 管理下で実行してください"
    中断 (skill return)
fi

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

# 一時ファイル用ディレクトリを確保 (review-pr Step 0.2 でも作るが、
# create-pr 単独起動時にも必要。冪等なので重複しても問題ない)
mkdir -p "$REPO_ROOT/docs/temp"
```

以下を並列で実行:

```bash
git status
git diff --staged && git diff
git log "$BASE"..HEAD --oneline
git diff "$BASE"...HEAD --stat
```

### Step 2: base 同期 + コンフリクト解消

push 前に base との乖離を解消する。**本 Step では push しない** (push は Step 7 で最終 1 回)。

```bash
git fetch origin "$BASE"
BEHIND=$(git rev-list --count HEAD.."origin/$BASE")
if [ "$BEHIND" -gt 0 ]; then
    if git rebase "origin/$BASE"; then
        :   # 成功
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

### Step 3: PR 本文の作成

**重要: `gh pr create --body` にヒアドキュメントで直接渡さないこと。**

PR 本文に `##` などの `#` で始まる行が含まれると、Claude Code のセキュリティチェックで許可確認が発生する。
これを回避するため、**必ず一時ファイル経由で `--body-file` を使用する。**

一時ファイルの配置先: `$REPO_ROOT/docs/temp/pr-body.md`

**この時点で `gh pr create` は実行しない。** PR 本文をローカルに作成し、レビュー完了後の
Step 7 で `gh pr create --body-file` に渡す。

```bash
# Write ツールで $REPO_ROOT/docs/temp/pr-body.md を作成 (Critical Decisions 込み)
# ↓
# 所有権 sidecar を書き出す (中身はブランチ名)。
# review-pr Step 0.3 が本 sidecar のブランチ名と比較して「経路 A 引き継ぎ」と
# 判定する (= OWNED_BODY_FILE=False)。両 skill 共通フォーマット
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "$BRANCH" > "$REPO_ROOT/docs/temp/.pr-body.owner"
# ↓
# 注意: ここで pr-body.md / sidecar を rm しない。Step 5 で review-pr が
# 本ファイルを引き継いで毎巡「対応履歴」を追記する。最終 rm は Step 9 で
# 両ファイルを `rm -f` する
```

#### PR 本文フォーマット

- タイトルは 70 文字以内

##### 基本フォーマット

```markdown
## Summary
- 変更内容の要約（1〜3行）

## Critical Decisions
（Step 3 で分析した結果を記載。省略不可）

## Test plan
- [ ] テスト項目

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

##### Issue 対応時の追加ルール

- 本文の `🤖 Generated with...` 行の **直前** に `Closes #<issue 番号>` を追加
- 成果物にドキュメント（設計資料、仕様書、ADR 等）が含まれる場合は「成果物リンク」セクションを追加
  - リンク形式: `https://github.com/<owner>/<repo>/blob/<branch>/<path>`
  - drawio や SVG ファイルは Markdown に埋め込まれているためリンク不要
- 「ブラウザテスト」セクションは **Step 4 実施後に自動追記される** (Step 3 時点では書かない。skip 時は追記されないのが正しい挙動)

```markdown
## Summary
- 変更内容のサマリ

## Critical Decisions
（Step 3 で分析した結果を記載。省略不可）

## 成果物リンク
（ドキュメント成果物がある場合のみ）

## Test plan
- テスト内容

Closes #<issue 番号>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

##### Step 3 時点で書かないセクション

- `## ブラウザテスト`: **Step 4 実施後に自動追記される** (Step 4 の 8 参照)。見出しは
  `## ブラウザテスト` リテラルで固定 (review-pr Step 0.4 の `BROWSER_TEST_DONE` 判定キー)。
  Step 3 時点でこの見出しを書くと、Step 4 を skip したときも True になるので書かない
- `## 対応履歴`: Step 5 のセルフレビューで毎巡 review-pr Step 4.5 が追加・更新する。
  テンプレートと挿入位置は `skills/global/review-pr/references/fix-steps.md` の Step 4.5 が正本
  (本 skill では別途定義しない)

#### Critical Decisions 分析

PR 本文作成時に、変更がもたらす影響について **4 軸の明示的宣言** を行う。
notApplicable でも省略不可 — 「考えたことを証明させる」仕組み。

diff を分析し、以下の各軸について該当/非該当を判定する:

| 軸 | チェック内容 | 判定ガイドライン |
|----|-------------|-----------------|
| backwardCompatibility | 後方互換性への影響。既存 API・DB カラム・画面操作の互換を壊さないか | public メソッドのシグネチャ変更、API レスポンス構造の変更、画面の操作フロー変更 |
| securityTradeoff | セキュリティ上のトレードオフ。認証・権限・データ露出の変更 | Policy/Gate/Middleware の変更、認証ロジックの変更、データ公開範囲の変更 |
| irreversibleAction | 不可逆な操作の有無。DB マイグレーション・データ削除・外部 API 呼び出し | マイグレーションファイル、`DELETE` / `TRUNCATE`、外部 API 呼び出しの追加・変更 |
| dataModelChange | データモデル変更の有無。テーブル追加・カラム変更・リレーション変更 | マイグレーションファイルの存在、Model の `$fillable` / `$casts` / リレーション変更 |

**分析手順**:

1. `git diff "origin/$BASE"...HEAD` の diff を確認
2. 各軸について該当/非該当を判定（複数軸に該当する場合あり。例: マイグレーション → dataModelChange: yes + irreversibleAction: yes）
3. 該当する場合は具体的な影響と対策を記述
4. PR 本文の `## Critical Decisions` セクションに以下の形式で記載:

```markdown
## Critical Decisions

| 軸 | 該当 | 影響・対策 |
|----|------|-----------|
| backwardCompatibility | notApplicable | — |
| securityTradeoff | notApplicable | — |
| irreversibleAction | yes | マイグレーションで orders テーブルに NOT NULL カラム追加。既存レコードにはデフォルト値 0 を設定 |
| dataModelChange | yes | orders テーブルに priority カラム追加。Model の $fillable に追加済み |
```

**review-pr 側での検証**: Analyst ロールが Critical Decisions の宣言と実際の diff を照合し、以下を検出する:
- 宣言漏れ（マイグレーションファイルがあるのに dataModelChange: notApplicable）
- 過小宣言（影響範囲が宣言より広い）

### Step 4: ブラウザテスト実施 (条件付き)

#### 実施判定 (OR 条件)

以下のいずれかに該当すれば **必ず実施** (判定の skip は禁止):

1. **test plan / PR 本文素案にブラウザ系キーワード**: `ブラウザ` / `画面` / `UI` / `Playwright` / `Livewire` / `画面遷移` / `ボタン` / `表示`
2. **diff に画面ファイル**:
   - `*.blade.php`, `resources/views/**`, `resources/js/**`, `*.vue`, `*.tsx`, `*.jsx`
   - Livewire: `app/Http/Livewire/**`, `app/Livewire/**`

判定は以下で機械的に行う:

```bash
# diff 解析
git diff --name-only "origin/$BASE"...HEAD | grep -E '\.(blade\.php|vue|tsx|jsx)$|^(resources/views|resources/js|app/(Http/)?Livewire)/'
```

#### 実行

1. **dev server 起動確認**: 多くは `./vendor/bin/sail` で稼働中。プロジェクト固有の起動コマンドは CLAUDE.md / `.env` / `docker-compose.yml` を確認して判断。停止していたら起動する
   - 起動コマンドが特定できない / 3 回試行しても URL に到達できない場合は、**Step 4 全体を skip し、その旨を Step 8 の最終報告で明示**。skill 全体は escalate せず通常フローを継続
2. **URL 推測 → 検証**: test plan 項目 + 変更画面 (route から逆引き) で `mcp__playwright__browser_navigate`
3. **操作・検証**: 必要に応じて `mcp__playwright__browser_click` / `browser_type` / `browser_snapshot`
4. **テストデータ作成は確認不要で自律実行**: 検証に必要なら artisan tinker / factory / 直接 DB 投入で作成して良い。ユーザーに「作ってよいか」を確認する必要はない — 実装内容を網羅的にテストするために必要なデータは自分で判断して作る。**ただし本番系 / 破壊的操作 (truncate / drop / migrate:fresh 等) は禁止**。ローカル DB はテスト用なのでデータ更新は自由
5. **全操作パスを実行する**: 実装した機能の**全ての操作パス**をブラウザで実行する。
   「テストデータが無い」「DB を変更してしまう」は理由にならない（項番 4 で作る）。
   特に以下を飛ばさない:
   - **主要フロー（CRUD の全操作）**: 作成・表示・更新・削除がある機能なら全て実行
   - **状態遷移の全パス**: 予約→確認→完了、取消、エラー復帰など
   - **バリデーション**: 必須項目の空送信、不正値、境界値
   - **エッジケース**: 0 件時の表示、重複操作の防止
   テスト完了報告時に「未実行のパスは無い」ことを確認する。
   やむを得ず実行できないパスがある場合は理由と共に明示する（「やらなかった」ではなく「できない理由」を具体的に）
6. **失敗時のリトライ**:
   - 1 件でも失敗したら **修正してリトライ**
   - **同一ケースが** 3 回連続失敗したら、`rm -f "$REPO_ROOT/docs/temp/pr-body.md" "$REPO_ROOT/docs/temp/.pr-body.owner" "$REPO_ROOT/docs/temp/review-"*.diff` で中間ファイルを掃除してから **ユーザーに報告して停止** (別ケースの失敗とは合算しない)
7. **テスト網羅性の敵対的レビュー**: ブラウザテスト完了後、独立エージェントで
   テストの網羅性を検証する。テスト実行者自身は「やった」バイアスがかかるため、
   別の視点で「本当に全パスを通したか」を突く。

   親が diff ファイルを書き出す:

   ```bash
   git diff "origin/$BASE"...HEAD > "$REPO_ROOT/docs/temp/review-browser.diff"
   ```

   ```text
   Agent(
       description = "ブラウザテスト網羅性の敵対的レビュー",
       subagent_type = "general-purpose",
       isolation = "worktree",   # 親の作業ツリーを守る (review-pr 重要原則 4 と同じ二重防御)
       prompt = """
       対象ブランチのブラウザテスト結果を敵対的にレビューしてください。

       1. `<REPO_ROOT を展開した絶対パス>/docs/temp/review-browser.diff` を Read して実装内容を把握
          (親が `$REPO_ROOT` を展開してから prompt に埋め込む。subagent 側では変数が未定義)
       2. 実装から導かれる「テストすべき全操作パス」を列挙
       3. 以下を指摘:
          - 実装にあるのにテストされていない操作パス
          - 状態遷移で通っていないパス（特に異常系・取消・復元）
          - エッジケース（0件、上限、重複操作、同時操作）
          - テストデータ不足で本来のロジックを通っていない可能性

       read-only。Edit / Write 禁止。git checkout / switch / gh pr checkout で作業ツリーを
       変更しない。remote への書き込み (git push / gh pr edit|review|merge / gh api の非 GET) も禁止。
       """
   )
   ```

   **最大 5 巡ループする**:
   1. 敵対的レビューで指摘を受ける
   2. **指摘の妥当性を検証する** — 言われるがままに従わない。各指摘について:
      - 実装コードを読んで指摘が事実に基づいているか確認
      - テスト不要と判断できる正当な理由があれば反論する
        （例: 「このパスは UI 上到達不能」「このバリデーションはサーバー側で担保済み」）
      - 反論が通らない指摘のみテストを追加実行する
      - **どうしても決着がつかない指摘はユーザーに判断を仰ぐ**
   3. 再度敵対的レビューを起動（新しい独立エージェント）
   4. 指摘 0 件（または全指摘に正当な反論済み）で収束、または 5 巡到達で終了

   5 巡到達時に未解消の指摘が残っている場合は、Step 8 の最終報告で明示する。

8. **ブラウザテスト結果を PR 本文に書き戻す**: ブラウザテストを実施した場合、
   `docs/temp/pr-body.md` の `## Test plan` より前に `## ブラウザテスト` セクションを
   追記する。**skip した場合は追記しない** (判定が False になるのが正しい挙動)。
   見出しは `## ブラウザテスト` リテラルで固定 (review-pr Step 0.4 の
   `BROWSER_TEST_DONE` 判定キーとして使われるため、文言を変えると Step 5
   再走査がスキップされる)。実施した操作パスの一覧を簡潔に記載する。
   スクリーンショットの添付は不要。

### Step 5: セルフレビュー (`review-pr` skill に委譲)

ブラウザテスト後（または判定により skip 後）、セルフレビューに入る。**レビュー本体は
`review-pr` skill に委譲する**。本 step はその起動と結果受領を担当する。

#### 委譲前の前提条件

- Step 3 で `docs/temp/pr-body.md` と sidecar `docs/temp/.pr-body.owner`
  (中身はブランチ名) を作成済みであること。`review-pr` Step 0.3 は sidecar の
  ブランチ名とカレントブランチを照合して所有権フラグを `OWNED_BODY_FILE=False`
  にセットする (= **create-pr が作ったファイルなので削除責務は create-pr 側
  にあり**、review-pr は触らない)。review-pr は毎巡「対応履歴」セクションを
  `docs/temp/pr-body.md` に追記する
- **この時点で PR はまだ存在しない** (経路 A)。`review-pr` には PR 番号を渡さない

#### 起動方法

Skill ツール経由で呼び出す:

```text
/review-pr --fix {depth_flag}
```

経路 A では PR が未作成のため `gh pr view` による author 自動判定が効かず、
`--fix` を明示しないと review-only にフォールバックする。

`{depth_flag}` は Step 0 で `args` から受け取った `DEPTH_FLAG` をそのまま入れる
(空なら `/review-pr --fix`)。指定がある場合:
- `--depth lightweight` — バグ修正パス: Correctness + Security のみ、1 巡
- `--depth full` — 機能追加パス: Correctness + Security + Impact、最大 3 巡

create-pr 単独起動時（resolve-issue skill 経由でない場合）は `DEPTH_FLAG` なし = 現行動作（全観点、最大 5 巡）。

**depth 独自付与の禁止**: create-pr が PR の内容・規模・難易度・変更ファイル種別を
判断して独自に `--depth` を付与することは**禁止**する (Step 0 参照)。
「skill ファイルだけの変更だから lightweight でよい」「diff が小さいから lightweight」
等の ad-hoc 判断は短縮禁止ルールの適用対象。

`review-pr` は内部で以下を全自動で実行する (詳細は
`skills/global/review-pr/SKILL.md` 参照):

- 毎巡先頭で base 再同期 (rebase)
- 毎巡 `git diff "origin/$BASE"...HEAD` を diff ファイルに書き出し、レビュアーに渡す
- `--depth` 指定時: Correctness / Security / Impact + Analyst の並列レビュー、
  フラグなし: Reviewer A / B + Fact-checker の 3 エージェント並列レビュー (worktree
  分離)
- 指摘の分類 (silent-reject / escalate / auto-fix)
- auto-fix の Edit/Write 実装 + commit
- `docs/temp/pr-body.md`「対応履歴」セクション追記
- UI 影響時はブラウザテスト再走査
- 巡数上限は depth 依存 (lightweight 1 / full 3 / legacy 5)。`auto-fix = 0` または
  fix-stable 収束で自然終了 / escalate / ブラウザ回帰で中断
- 3 巡目以降は各ロールのプロンプトを「マージブロッカー級のみ」に
  自動制約

#### 委譲時の制約

- **短縮指示を渡さない**: 「小さいから 1 名で」「1 巡で」等は禁止
  (詳細は上の「短縮禁止」セクション)
- **`docs/temp/pr-body.md` を委譲前に削除しない**: `review-pr` が
  引き継いで使う。`review-pr` 内部では本ファイルを **削除しない**
  ので、本 skill の Step 9 で rm する

#### 委譲後の処理

`review-pr` が return したら、その出力 (巡数 / 各巡の件数推移 /
escalate 内容 / silent-reject 件数等) を保持して Step 5.5 (リモートブランチ判定) に進む。

**escalate 時も PR は作る**: `review-pr` 内で escalate された場合も、
Step 5.5 (リモートブランチ判定) → Step 6 (squash) → Step 7 (push + PR 作成) →
Step 8 (最終報告) → Step 9 (クリーンアップ) → Step 10 (awaiting 化) の順に
**全 Step を実施する**。
escalate は「人間の判断が要る」であって「成果物を捨てる」ではない。
PR があればユーザーはブラウザで diff を見て判断でき、判断後に続きを再開できる。
Step 8 の最終報告で escalate 内容と「ユーザー判断待ちである」ことを明記する。
Step 10 の `AskUserQuestion` で escalate 内容を提示する。

**採らない案**: 「escalate 時は push せず cleanup も skip する」案は採らない。
理由: escalate 時も PR を作ることでユーザーが diff を確認でき、判断後に
続きを再開できる。

Step 9 に到達しない中断経路は 5 つあり、`docs/temp/` の扱いは経路ごとに違う:

| 中断経路 | `docs/temp/` の扱い | 理由 |
|---|---|---|
| Step 1: `REPO_ROOT` が解決できない | 何もしない | Step 3 より前で、`mkdir -p` にも到達しない |
| Step 2: rebase コンフリクトでユーザーが中止 | 何もしない | Step 3 より前なので pr-body.md はまだ無い |
| Step 4: ブラウザテスト 3 回連続失敗 | 中断箇所で `rm -f` | レビュー前なので対応履歴は無く、再実行は Step 3 の Write で作り直せる |
| Step 5: 委譲先 `review-pr` が Step 0 で中断して戻る (Step 0.2 の `REPO_ROOT` 解決不能 / Step 0.2.5 の `gh api user` と author 取得の両方失敗。後者は create-pr が `--fix` を渡すので経路 A では到達しない) | **残す** | 委譲先が `中断 (skill return)` で戻った場合、create-pr も Step 5.5 以降に進まず**そこで中断する**。pr-body.md は Step 3 の作成物でレビュー前なので、残しても再実行時に Step 3 の Write が上書きする。消す処理を足す価値が無い |
| Step 7 (経路 B): remote-tracking ref 不在で force push 不可 | **残す** | レビュー後で、pr-body.md に N 巡分の対応履歴がある。案内先の手動 PR 作成にこのファイルが要り、PR 未作成なので消すと復元できない |

(`review-pr` 内の escalate / base-conflict / browser-regression は create-pr を
中断せず Step 5.5 以降に進むので、ここには含めない。`review-pr` が中断で戻るのは
上表 Step 5 の行の 2 経路だけで、いずれも Step 1 (レビュー本体) より前に起きる)

#### Skill 委譲と subagent 独立性の整理

`review-pr` を Skill ツールで呼び出すと、`review-pr` 本体は **親
(create-pr) と同一コンテキストで走る**。これがバイアスにならないのは、
セルフレビューにおける「コードを書いた本人による評価」を禁じている
真の対象は **レビュー subagent** (`--depth` 指定時: Correctness / Security /
Impact + Analyst、フラグなし: Reviewer A/B + Fact-checker) であり、
orchestration 層 (= `review-pr` 本体) の独立性ではないため。`review-pr` の
Step 2 で必ず Agent ツール経由 (`isolation: "worktree"`) で subagent を
spawn することで、レビュー評価の独立性は構造的に担保される。

### Step 5.5: リモートブランチ判定 (Step 6・7 共通)

**Step 6・7 の前に必ず実行する。** Step 6 (squash) と Step 7 (push) の
両方がこの判定結果を使う。独立 Step にすることで、Step 6 を飛ばしても
判定は済んでいる構造にする。

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
# リモートの実体で判定する (ローカルの tracking 設定に依存しない)。
# git ls-remote はネットワークを使う。オフラインワーカー構成では
# push 可否の判定は台帳側 (push を行う側) の責務になる。
# **安全側に倒す**: ls-remote が失敗した場合は「公開済み」とみなす。
# 理由: 誤って「未公開」→ 公開済み履歴を squash で破壊 (回復に手作業)。
#        誤って「公開済み」→ squash されないだけ (壊れない)。
if LS_REMOTE_OUT=$(git ls-remote --heads origin "$BRANCH" 2>/dev/null); then
    REMOTE_BRANCH_EXISTS=$(printf '%s' "$LS_REMOTE_OUT" | grep -c . || true)
else
    echo "[create-pr] リモートを参照できません。公開済みとみなし squash をスキップします"
    REMOTE_BRANCH_EXISTS=1
fi
```

### Step 6: squash

**squash は経路 A (まだ push されていないブランチ) のときだけ行う。**
経路の判定は Step 5.5 が行うので、**Step 6 自体は必ず実行する**
(Step 7 が Step 5.5 の判定結果を使うため)。

```bash
if [ "$REMOTE_BRANCH_EXISTS" -eq 0 ]; then
    # リモートに無い → squash してよい

    # squash 前に畳むコミットを記録
    git log "origin/$BASE"..HEAD --oneline

    git reset --soft "origin/$BASE"
    # コミットメッセージを組み立てて commit
    # - commit-workflow skill の規約に従う
    # - Closes #<issue番号> トレーラーを含める (Issue 対応時)
    # - 🤖 Generated with [Claude Code] トレーラーを含める
    git commit -m "<タイトル>

<本文>

Closes #<issue番号>

Co-Authored-By: ...
🤖 Generated with [Claude Code](https://claude.com/claude-code)"
else
    # 既に remote にある → squash しない (force-push を避けるため)
    :
fi
```

- `rebase -i` は使わない。`reset --soft` + `commit` の方が非対話で失敗モードが少ない
- **トレーラーを明示的に組み立てること**: `Closes #<issue番号>` と
  `🤖 Generated with [Claude Code]` は巡ごとのコミットには無いので、
  squash 時のメッセージ生成で必ず含める
- コミットメッセージは `commit-workflow` skill の規約に従う

### Step 7: push + PR 作成

3 つの小節に分かれる。**経路 B (force push) だけを独立した見出しにしてある**のは、
「fix 経路に lease 付き force push が現れないこと」を固定する静的検査を置く場合に、
「経路 B: force push」見出しの節だけを除外できるようにするため。経路 A の通常 push
(7-1) と PR 作成 (7-2) は検査対象に残り、「経路 A は force を使わない」が検査で担保される。
この小節の外に当該コマンド名を書くと検査が落ちる (意図どおり)。

#### Step 7-1: push

```bash
# BRANCH / REMOTE_BRANCH_EXISTS は Step 5.5 で判定済み
gh auth setup-git
if [ "$REMOTE_BRANCH_EXISTS" -eq 0 ]; then
    # 経路 A: リモートに無い (squash 済み) → 通常 push。force は使わない
    git push -u origin "$BRANCH"
else
    # 経路 B: リモートに存在する既存ブランチ → 下の「経路 B: force push」を実行
    :
fi
```

#### 経路 B: force push (リモートに存在する既存ブランチ)

**経路 B の force push は `--force-with-lease` のみ。`--force` は禁止。**
fetch 前に SHA を捕まえてリースを固定する。fetch 後に expect 値なしで
`--force-with-lease` を使うと、他人の新規コミットも黙って吹き飛ばす。

```bash
EXPECTED=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
git fetch origin "$BRANCH"
LOCAL_AHEAD=$(git rev-list --count "origin/$BRANCH"..HEAD 2>/dev/null || echo 0)
REMOTE_AHEAD=$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)
if [ "$REMOTE_AHEAD" -gt 0 ] && [ "$LOCAL_AHEAD" -gt 0 ]; then
    # 分岐している = rebase で書き換わった
    if [ -n "$EXPECTED" ]; then
        git push --force-with-lease="refs/heads/$BRANCH:$EXPECTED"
    else
        # ローカルに remote-tracking ref が無い → リースを張れない
        echo "[create-pr] remote-tracking ref が無いため force push できません"
        echo "手動で git push --force-with-lease を実行してください"
        # docs/temp/ は消さない: 上の案内どおり手動で PR を作るのに pr-body.md
        # (レビュー N 巡分の対応履歴を含む) が要る。PR 未作成なので消すと復元手段が無い
        中断 (skill return)
    fi
else
    git push
fi
```

#### Step 7-2: PR 作成 or 更新

```bash
# push 済みだが PR が無いブランチ (中断の残骸、閉じた PR の後) に対応するため
# upstream の有無ではなく PR の存在で分岐する
EXISTING_PR=$(gh pr view --json number -q .number 2>/dev/null || echo "")
if [ -z "$EXISTING_PR" ]; then
    gh pr create --title "<タイトル>" --body-file "$REPO_ROOT/docs/temp/pr-body.md"
else
    gh pr edit "$EXISTING_PR" --body-file "$REPO_ROOT/docs/temp/pr-body.md"
fi
```

### Step 8: 最終報告

以下をまとめて報告:

- PR の URL
- セルフレビュー巡数 (1-5)
- 各巡の auto-fix 件数
- ブラウザテストの実施状況と最終結果
- escalate された指摘 (あれば内容と該当指摘箇所)
- 残コミット履歴の概要

### Step 9: クリーンアップ

```bash
rm -f "$REPO_ROOT/docs/temp/pr-body.md" "$REPO_ROOT/docs/temp/.pr-body.owner" "$REPO_ROOT/docs/temp/review-"*.diff
# -f で冪等性確保 (review-pr 経路 B 起動時など別 skill が先に消すケースに
# 耐える)。sidecar (.pr-body.owner) も同時に消すことで、次回 PR 作成時の
# 所有権判定が確実に「経路 A の新規作成」として始まる。
# review-*.diff はレビュー各巡で生成された diff ファイル。
```

`docs/temp/` に他のファイルがある場合があるため、**ディレクトリごと削除しない**。

### Step 10: 完了の宣言

**全ての副作用処理 (Step 9 のクリーンアップ等) を完了させた後** に実行する。

順序が重要: 本 Step を **最後** に置き、副作用処理を全て先に完了させる規約
(`AskUserQuestion` はブロッキング呼び出しで、応答後の skill フロー保証が無いため
Step 9 クリーンアップを skip するリスクがある)。

`AskUserQuestion` を呼んで PR 完了報告を **明示的なユーザー判断待ち状態**
として declare する。

> **本 skill 自体は視覚的な通知機構を持たない**。応答待ちの可視化は環境側
> (statusline / hook / 外部オーケストレータ) に委ね、それらが無い環境では
> `AskUserQuestion` による停止そのものが合図になる。
> 同じ注記が `create-issue` にもある。

呼び出し例 (`AskUserQuestion` の正しい schema = `questions: [...]` リスト形式):

```text
AskUserQuestion({
    questions: [
        {
            question: "PR が完成しました。マージ判断をお願いします。",
            header: "PR完了",
            multiSelect: false,
            options: [
                {label: "確認する", description: "PR 内容を確認する"},
                {label: "すでにマージ済み", description: "別タブで既にマージした"}
            ]
        }
    ]
})
```

ユーザーが「Other」で自由入力すれば skill のフローから自然に抜けられる。
どの選択肢を選んでも `UserPromptSubmit` が発火し、awaiting 表示は解除される
(選択肢の違いは Claude 側の次アクションの参考情報であり、awaiting 解除自体は
ユーザーが何か入力した時点で共通に起きる)。

**実装メモ**: 本 Step は `create-pr` skill 固有の挙動。他 skill で「ユーザー
判断待ち」を declare したい場合も同様に「全副作用完了後の最終ステップ」で
宣言すること (PermissionRequest 経路を統一シグナルとして扱う)。

---

## エスカレーション基準

skill が「ユーザー確認を取って停止する」のは以下のときのみ:

1. **コンフリクトの意味的解消** (Step 2、および `review-pr` 内の base 再同期時)
   - 同じ関数や条件分岐を両側で別の意図に変更している
   - 何を残すかは仕様判断
2. **レビュー指摘のブロッカー / トレードオフ判定** (`review-pr` 内の指摘分類)
   - 詳細な分類基準は `skills/global/review-pr/SKILL.md` の Step 3 参照
3. **ブラウザテストの 3 回連続失敗** (Step 4 のリトライ条項)
   - 修正で直らない深い問題の可能性
4. **ブラウザテストの回帰** (`review-pr` 内の再走査)
   - 修正で動いていた機能が壊れた

それ以外 (lint 違反 / 命名 / 不要 import / typo / 軽微なリファクタ提案等) は **すべて自動修正する** (`review-pr` 側で実施)。

---

## ブラウザテスト実施判定基準

以下のいずれかが true なら **必ず実施**:

- PR 本文 (素案でも可) / test plan / 変更ファイル名・パス に画面系キーワード (`ブラウザ` / `画面` / `UI` / `Playwright` / `Livewire` / `画面遷移` / `ボタン` / `表示`) が出現
- diff にビュー / コンポーネントファイル (`.blade.php`, `.vue`, `.tsx`, `.jsx`, `resources/views/**`, `resources/js/**`, `app/(Http/)?Livewire/**`) が含まれる

判定の skip 判断は不要。両条件が false でも実施したほうが安心な場合は実施して構わない。

---

## 注意事項

- push は必ず `gh` 経由 (SSH 鍵なし)。`gh auth setup-git` を先に走らせる
- `docs/temp/` は `.gitignore` 対象外なので Step 9 で必ず掃除
- PR 本文を `--body` で直接渡す方法は使わない (`#` 行問題)
- セルフレビューループ中の commit message・PR 本文の毎巡更新方針は `review-pr` 側に集約 (本 skill では別途定義しない)
- **指摘 0 件で自然終了 = 基本ゴール / ITER_MAX 到達 = 警戒シグナル または収束** (詳細解釈は `skills/global/review-pr/SKILL.md` 冒頭参照)。Step 8 の報告では ITER_MAX 到達ケースの「巡ごとの auto-fix 件数推移」と「収束 / 警戒の判定」を明記すること (`review-pr` から受領した出力をそのまま転載でよい)
- **Critical Decisions は省略不可**: Step 3 の 4 軸分析は全 PR で必ず実施する。notApplicable でも明示的に宣言すること。省略は許容しない
