---
name: review-pr
description: 指定 PR (引数なしならカレントブランチの PR) をセルフレビューする。ポジションロール方式 (Correctness / Security / Impact + Analyst 裁定者) の並列構成 (worktree 分離)。--depth lightweight (bug 修正向け、1 巡) / --depth full (機能追加向け、最大 3 巡) / フラグなし (後方互換、最大 5 巡) で観点と巡数を制御。自分の PR は auto-fix モード、collaborator の PR は review-only モード (--review-only / --fix で明示 override 可)。「/review-pr 123」「PR レビューして」「指摘消して」「セルフレビュー」のような自然言語で起動。create-pr Step 5 からも内部呼び出しされる。
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, Agent, mcp__playwright__browser_navigate, mcp__playwright__browser_click, mcp__playwright__browser_type, mcp__playwright__browser_evaluate, mcp__playwright__browser_resize, mcp__playwright__browser_take_screenshot, mcp__playwright__browser_snapshot, mcp__playwright__browser_tab_select, mcp__playwright__browser_console_messages
---

# PR セルフレビュー (auto-review/fix ループ)

「PR レビューして」と言われたら、指定 PR を独立セルフレビューする。
**2 つの動作モード** と **3 段階のレビュー深度** がある:

| MODE | 想定対象 | 挙動 |
|---|---|---|
| **fix** | 自分が author の PR | 「独立セルフレビューで指摘が無くなった (= auto-fix が 0 件) 状態」にして戻す。auto-fix + commit + PR 本文「対応履歴」追記まで自動 |
| **review-only** | 他者 (collaborator) が author の PR | レビューのみ実施し、findings を summary review コメントとして GitHub PR に投稿 (ユーザー承認後)。collaborator のブランチ・PR 本文には一切書き込まない |

| DEPTH | 起動ロール | ITER_MAX (fix) | 想定用途 |
|---|---|---|---|
| **lightweight** | Correctness + Security + Analyst | 1 | バグ修正の軽量パス |
| **full** | Correctness + Security + Impact + Analyst | 3 | 機能追加のフルパス |
| **(なし)** | Reviewer A / B + Fact-checker (後方互換) | 5 | 従来方式 |

### MODE 決定ロジック (Step 0.2.5 で確定)

| 入力 | 結果 MODE |
|---|---|
| `/review-pr 5 --review-only` (明示) | review-only |
| `/review-pr 5 --fix` (明示) | fix |
| `/review-pr 5` フラグなし + PR author == 自分 | fix |
| `/review-pr 5` フラグなし + PR author != 自分 | review-only (auto 切替、Step 0.2.5 でユーザーに通知) |
| 自動検出失敗 (gh api user エラー等) | review-only (safer default) |

create-pr Step 5 からの内部呼び出しは作りたての自分の PR が対象なので、`--fix` フラグ付きで起動される (経路 A では PR が未作成のため author 自動判定が効かないため)。

### DEPTH 決定ロジック (Step 0.1 で確定)

| 入力 | 結果 DEPTH |
|---|---|
| `--depth lightweight` | lightweight (Correctness + Security、ITER_MAX=1) |
| `--depth full` | full (Correctness + Security + Impact、ITER_MAX=3) |
| フラグなし | legacy (後方互換: Reviewer A/B + Fact-checker、ITER_MAX=5) |

create-pr Step 5 からの内部呼び出しで depth フラグが渡された場合はそれを採用。

以下、fix モードの挙動を基本系として記述し、review-only モードは各 Step で **差分** を明示する。

途中で人間の判断が必要なのは:

- レビュー指摘がブロッカー (Must-fix) / セキュリティ影響 / トレードオフ / 仕様判断のとき
- base 同期で意味的コンフリクトが発生したとき
- ブラウザテスト再走査で回帰が出たとき

それ以外は全自動で進める。**「指摘 0 件で自然終了」が基本ゴール、5 巡到達は警戒シグナル** (修正が新たな問題を呼んでいる / レビュアーが新しい観点を毎巡見つけて収束しない可能性)。

5 巡到達の解釈:

- **5 巡到達 + 後半巡が Nice-to-have のみ** → 正常な収束、機能的にはマージ可。Step 7 報告で「警戒」ではなく「収束」として記述
- **5 巡到達 + 後半巡に Must-fix / Should-fix が出続ける** → 真の警戒シグナル。修正が新たな問題を呼んでいる / 観点が収束しない可能性が高い。Step 7 報告で巡ごとの件数推移と残課題を強調

## 短縮禁止

**「小さい修正だから」「diff が少ないから」という理由で、Step 2 のレビュー構成や巡数上限を独断で短縮することは禁止する**。

### 適用範囲

本ルールが禁止対象とするのは **Step 2 のレビュー構成と巡数上限の独断短縮のみ**。skill 内に明記された条件付き skip パス (Step 5 のブラウザテスト未実施時 skip、Step 4 先頭の early-break による escalate / auto-fix=0 中断等) は本ルールの対象外であり、明記された条件で正規に skip / 中断する。

**review-only モードの ITER_MAX=1 は本ルールの「短縮」に該当しない**: Step 0.4 の説明 (line 「review-only モードの ITER_MAX が 1 である理由」参照) のとおり、修正をかけずに reviewer を再起動しても新しい情報が得られない構造的理由による設計上の正規値。fix モードの「5 巡」と同列の規範であり、「独断で減らした」ものではない。

**`--depth` フラグによる ITER_MAX / ロール構成の変更は本ルールの「独断での短縮」に該当しない**: `--depth` は workflow 設計レベルの決定（resolve-issue skill がパスに応じて指定）であり、実行時の ad-hoc 判断ではない。設計段階でバグを潰す前提でレビュー範囲を再定義したもの。

「短縮」とは構成や上限の **下振れ方向** (削減方向) を指す。上振れ (レビュアーを増やす等) は本ルールの対象外だが、想定外の挙動を生むので推奨もしない。

### 理由

- 修正のコード量と影響範囲は比例しない。1 行の変更でも race condition / セキュリティ脆弱性を生むことはある (実例: わずか 1 行の変更で 2 巡目に `os.replace` の inode race を独立レビュアーが発見したケース、1 行の修正に 1 巡目で shell injection が見つかったケースがある)
- 「簡素な修正は本当に簡素なら自然に 1-2 巡で収束する」のがこの skill の終了条件 (auto-fix 0 件で break) の意図。短縮判断を呼び出し側に持ち込むと、その判定基準自体がブレて一貫性が損なわれる (撤回後 2 巡で自然終了した実証例がある)
- 過剰な巡数を恐れて短縮するくらいなら、終了条件を信じて回す方が安全

### 具体的に禁止される行動

- `--depth` で指定されたロール構成を勝手に減らす（lightweight で Correctness のみにする等）
- Analyst（裁定者）/ Fact-checker（legacy モード）を「面倒だから」省略する（Analyst / Fact-checker は全ロールの指摘を統合・事実検証する必須ロール）
- legacy モード（--depth なし）で Reviewer A / B 2 名並列を 1 名に減らす
- 「1 巡で終わらせる前提」で 2 巡目以降のレビュー実施判断をスキップする (auto-fix 0 件で自然 break するまで毎巡レビューを起動する)
- 「これは些細だから」と escalate 候補を勝手に auto-fix 扱いに格下げ
- 逆方向 (短縮の対称) として **「auto-fix 可能な指摘を不必要に escalate に格上げして 2 巡目以降を打ち切る」のも禁止**。Step 3 の分類基準に厳密に従う

例外: **無し**。skill の流れ通りに必ず実施する。

## 重要原則

1. レビューは **必ず別エージェント (Agent ツール経由) で実行する**。
   コードを書いた自分自身でレビューするとバイアスが残るため。
2. レビューは **ポジションロール方式** で実行する (`--depth` で構成が変わる):
   - **`--depth lightweight`**: Correctness + Security + Analyst (3 エージェント)
   - **`--depth full`**: Correctness + Security + Impact + Analyst (4 エージェント)
   - **フラグなし (legacy)**: Reviewer A / B + Fact-checker (3 エージェント、後方互換)
   各ロールは「バランスを取る」必要なく**最大限主張する**設計。中立の Analyst が
   全ロールの指摘を統合・事実検証・重複排除・最終判定する:
   - **Correctness**: バグ・ロジック誤り・回帰・型不整合に特化
   - **Security**: セキュリティ影響・インジェクション・権限漏れに特化
   - **Impact** (full のみ): 共有部品波及・データ整合性・業務フロー影響に特化
   - **Analyst（裁定者）**: 全ロールの指摘をマージし `silent-reject` / `escalate` / `auto-fix` に分類。事実検証も担当（旧 Fact-checker の役割を統合）
   - **全レビュアーロール (Correctness / Security / Impact) は read-only**:
     プロンプトで Edit / Write・作業ツリーの変更・remote への書き込み
     (`git push` / `gh pr edit|review|merge` / `gh api` の非 GET) を禁止する。
     Agent ツールにツールを絞るパラメータは無く、原則 4 の `isolation: "worktree"`
     が物理的に守るのは **親の作業ツリーだけ** (remote と認証は共有される)
3. 全エージェントとも親セッションの文脈を渡さず、diff ファイルと
   PR 本文ファイルのパスだけ渡して純粋に評価させる。
4. レビュー agent (Correctness / Security / Impact / Analyst、legacy: Reviewer A / B / Fact-checker) は **必ず
   `isolation: "worktree"` で spawn し、かつプロンプトで作業ツリーの
   変更を禁止する (二重防御)**。理由: Agent (subagent) は
   `isolation` を指定しない限り親と cwd / git 作業ツリーを共有する。
   dotclaude のように `~/.claude/*` がリポ作業ツリーへの symlink で
   配布される環境では、subagent が「実機テスト」のつもりで
   `git checkout` / `gh pr checkout` すると **ライブ設定
   (settings.json / hooks) ごと別ブランチ版にリバートされる**
   (実際に発生した事例があり、`SessionStart` matcher が複数回 main 版に
   戻った)。worktree 分離で親ツリーを物理的に守り、
   プロンプト制約で checkout 自体を抑止する。レビュー (Reviewer A/B /
   Correctness / Security / Impact / Analyst) はローカル diff ファイルの
   Read のみで完結するため、作業ツリーの書き換えは本来不要。

---

## 手順

### Step 0: 入力解決 + 起動コンテキスト判定

#### 0.1 PR 番号 + フラグの解析

本 skill の **`args` パラメータ (Skill ツール)** をスペース区切りで解析する。
PR 番号 (数値) は 1 つ、モードフラグ (`--review-only` / `--fix`) は最大 1 つ、
深度フラグ (`--depth lightweight` / `--depth full`) は最大 1 つ:

```bash
# 受け取った args 例:
#   "123"                           → ARG_PR=123 / ARG_MODE_FLAG="" / ARG_DEPTH=""
#   "123 --review-only"             → ARG_PR=123 / ARG_MODE_FLAG="--review-only" / ARG_DEPTH=""
#   "123 --depth lightweight"       → ARG_PR=123 / ARG_MODE_FLAG="" / ARG_DEPTH="lightweight"
#   "123 --depth full --fix"        → ARG_PR=123 / ARG_MODE_FLAG="--fix" / ARG_DEPTH="full"
#   ""                              → ARG_PR=""  / ARG_MODE_FLAG="" / ARG_DEPTH=""

ARG_PR=""
ARG_MODE_FLAG=""
ARG_DEPTH=""
EXPECT_DEPTH_VALUE=False
for tok in $args:   # 擬似コード: $args を空白区切りでトークン化したものを順に処理
    if EXPECT_DEPTH_VALUE:
        if tok not in ("lightweight", "full"):
            echo "[review-pr] --depth の値が不正です: ${tok} (lightweight | full)"
            中断 (skill return)
        ARG_DEPTH = tok
        EXPECT_DEPTH_VALUE = False
    elif tok == "--depth":
        if ARG_DEPTH != "":
            echo "[review-pr] --depth が重複しています"
            中断 (skill return)
        EXPECT_DEPTH_VALUE = True
    elif tok in ("--review-only", "--fix"):
        if ARG_MODE_FLAG != "":
            echo "[review-pr] モードフラグが重複しています: ${ARG_MODE_FLAG} と ${tok}"
            中断 (skill return)
        ARG_MODE_FLAG = tok
    elif tok starts with "-":
        # typo (--review--only / -fix 等) を黙って無視すると意図と違う MODE / DEPTH で走る
        echo "[review-pr] 未知のフラグです: ${tok}"
        中断 (skill return)
    elif tok matches regex ^[0-9]+$:   # 整数のみ厳密 match (例: "5x" や "1-foo" は不可)
        if ARG_PR != "":
            echo "[review-pr] PR 番号が複数あります: ${ARG_PR} と ${tok}"
            中断 (skill return)
        ARG_PR = tok
    else:
        pass   # フラグでも番号でもないトークンは無視する (自然言語の補足を許容。
               # 意図を変える入力はすべて "-" 始まりか整数なので、上の分岐で捕まる)
if EXPECT_DEPTH_VALUE:
    echo "[review-pr] --depth に値がありません (lightweight | full)"
    中断 (skill return)

# PR 番号の確定
if [ -n "$ARG_PR" ]:
    N=$ARG_PR
else:
    N=$(gh pr view --json number -q .number 2>/dev/null)
    if [ -z "$N" ]:
        if [ "$ARG_MODE_FLAG" = "--review-only" ]:
            # review-only モードでは PR 必須
            echo "現在のブランチに紐づく PR がありません。先に /create-pr を実行してください"
            中断 (skill return)
        # fix モードでは PR 不在でも続行 (経路 A: create-pr から委譲された場合、
        # レビュー時点で PR はまだ存在しない)
```

`ARG_MODE_FLAG` は Step 0.2.5 で `MODE` に解決する。

#### 0.2 リポジトリ情報の取得

```bash
# リポジトリルートを解決 (全パスの基点。両モード共通)
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -z "$REPO_ROOT" ]:
    echo "[review-pr] リポジトリルートを解決できません。git 管理下で実行してください"
    中断 (skill return)

# docs/temp/ を両モード (fix / review-only) で確実に作成
mkdir -p "$REPO_ROOT/docs/temp"

# オフラインで解決 (ワーカーをネットワークなしで回せるようにする)
OWNER_REPO=$(git remote get-url origin 2>/dev/null \
    | sed -E 's#(\.git)?/?$##' \
    | sed -E 's#^.*[:/]([^/]+/[^/]+)$#\1#')
if [ -z "$OWNER_REPO" ]:
    # フォールバック (ネットワーク必要)
    OWNER_REPO=$(gh repo view --json owner,name -q '.owner.login + "/" + .name')

# BASE は create-pr Step 1 と同じ方式で解決 (offline-first)
BASE=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's@^origin/@@')
if [ -z "$BASE" ]:
    if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then
        BASE=main
    elif git ls-remote --exit-code --heads origin master >/dev/null 2>&1; then
        BASE=master
    else
        BASE=main
    fi

# 経路 B (PR 存在時): PR の実際の target branch を取得してオーバーライド
# (非デフォルトブランチを target とする PR で正しい diff を生成するため)
if [ -n "$N" ]:
    PR_BASE=$(gh pr view "$N" --repo "$OWNER_REPO" --json baseRefName -q .baseRefName 2>/dev/null)
    if [ -n "$PR_BASE" ]:
        BASE="$PR_BASE"
```

#### 0.2.5 MODE の解決 (fix vs review-only)

PR author と現在ユーザーを比較して MODE を決定。明示フラグがあれば最優先で
それを採用、無ければ author 一致で自動判定:

```bash
PR_AUTHOR=$(gh pr view "$N" --repo "$OWNER_REPO" --json author -q .author.login 2>/dev/null)
CURRENT_USER=$(gh api user -q .login 2>/dev/null)

if [ "$ARG_MODE_FLAG" = "--review-only" ]:
    MODE="review-only"
elif [ "$ARG_MODE_FLAG" = "--fix" ]:
    MODE="fix"
elif [ -z "$PR_AUTHOR" ] && [ -z "$CURRENT_USER" ]:
    # 両方失敗 = 認証 / 接続が完全に壊れている可能性 → skill 中断
    # (この状態では Step 0.2 の BASE 取得もすでに失敗しているはずで、
    # 後続 Step が確実に壊れる。MODE を review-only に倒すより明示中断が安全)
    echo "[review-pr] gh api user と gh pr view --json author の両方で取得失敗。認証状態 (gh auth status) を確認してから再実行してください"
    中断 (skill return)
elif [ -z "$PR_AUTHOR" ] || [ -z "$CURRENT_USER" ]:
    # 片方だけ失敗時は safer default = review-only (collaborator PR を勝手に
    # 上書きする事故を防ぐ)
    MODE="review-only"
    echo "[review-pr] gh api user / author の取得が片方失敗のため、安全側で review-only モードに切替"
elif [ "$PR_AUTHOR" = "$CURRENT_USER" ]:
    MODE="fix"
else:
    MODE="review-only"
    echo "[review-pr] PR #$N の author ($PR_AUTHOR) が現在ユーザー ($CURRENT_USER) と異なるため、自動的に review-only モードに切替 (override は --fix で可能)"
```

**MODE 確定後のガード**: MODE が `review-only` で `N` が空の場合、
Step 6.6 の `gh pr review` 投稿など後続 Step が確実に失敗するため中断する:

```bash
if [ "$MODE" = "review-only" ] && [ -z "$N" ]:
    echo "[review-pr] review-only モードでは PR 番号が必須です。先に /create-pr を実行してください"
    中断 (skill return)
```

**MODE が確定したら以降の Step で挙動が分岐する**。各 Step 冒頭で MODE を
チェックし、review-only 時の差分を明示する。基本系 (差分言及なし) は fix
モードを記述している。

**bot author (`dependabot[bot]` / `renovate[bot]` 等) の PR**: `PR_AUTHOR`
が bot 系 login の場合、`CURRENT_USER` と不一致なので自動的に review-only
に倒れる (safer default の意図通り)。bot ブランチをローカルから自分で
fix push したい運用では `--fix` 明示 override で fix モードに切替える。
書き込み権限 (リポへの write、または fork 元への push) は別途必要。

#### 0.3 PR 本文ファイルの所有権判定 (重要)

擬似コード構造 (review-only と fix で完全分岐、fix モードのみ以降の所有権
判定ロジックを実行する):

```text
if MODE == "review-only":
    OWNED_BODY_FILE = False   # PR 本文を触らないので docs/temp/pr-body.md は作らない
    Step 0.4 へ進む (本 Step の以降は skip)
else:
    # 以下、fix モード (および create-pr 内部呼び出し経路 A) の所有権判定
    ...
```

以下は fix モード時の本 Step の中身 (review-only では実行しない):

Step 4.5 で PR 本文「対応履歴」を毎巡更新する際の挙動が、呼び出し元の
状態で 2 経路に分かれる:

- **(A) `create-pr` からの内部呼び出し**: `docs/temp/pr-body.md` が
  すでに存在 (create-pr Step 3 で生成済み) → このファイルを編集して
  対応履歴を追記する。**ファイル削除は呼び出し元
  (create-pr Step 9) の責務**、本 skill は触らない
- **(B) 単独起動 (ad-hoc)**: `docs/temp/pr-body.md` が無い →
  `gh pr view --json body` で現本文を取得して `docs/temp/pr-body.md`
  に書き出し、以降の巡で同ファイルを編集する。**本 skill が作った
  ファイルなので終了時 (Step 8) に rm する**

判定ロジック (sidecar マーカー `docs/temp/.pr-body.owner` でブランチ名を
記録して所有権を識別。PR 本文には何も埋め込まない):

```bash
# mkdir -p / REPO_ROOT は Step 0.2 で解決済み
OWN_MARK_FILE="$REPO_ROOT/docs/temp/.pr-body.owner"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

if [ -f "$REPO_ROOT/docs/temp/pr-body.md" ]:
    # 既存ファイルあり → sidecar のブランチ名で判定
    if [ -f "$OWN_MARK_FILE" ] && [ "$(cat "$OWN_MARK_FILE" 2>/dev/null)" = "$CURRENT_BRANCH" ]:
        OWNED_BODY_FILE=False   # 呼び出し元 (create-pr) が当該ブランチ用に
                                # 用意したファイル → 最後の rm は呼び出し元
    else:
        # sidecar 無し / 別ブランチのゴミファイル → 経路 B 扱いで上書き再生成
        if [ -n "$N" ]:
            gh pr view "$N" --repo "$OWNER_REPO" --json body -q .body > "$REPO_ROOT/docs/temp/pr-body.md"
        else:
            # PR 不在 (sidecar 不一致 + N 空の異常状態) → 空ファイル
            echo "" > "$REPO_ROOT/docs/temp/pr-body.md"
        echo "$CURRENT_BRANCH" > "$OWN_MARK_FILE"
        OWNED_BODY_FILE=True
else:
    # ファイル無し → 経路 B
    if [ -n "$N" ]:
        gh pr view "$N" --repo "$OWNER_REPO" --json body -q .body > "$REPO_ROOT/docs/temp/pr-body.md"
    else:
        # PR 不在 (経路 A で sidecar もない異常状態) → 空ファイル
        echo "" > "$REPO_ROOT/docs/temp/pr-body.md"
    echo "$CURRENT_BRANCH" > "$OWN_MARK_FILE"
    OWNED_BODY_FILE=True         # 本 skill が作った → Step 8 で rm
```

呼び出し元 (create-pr Step 3) も `$REPO_ROOT/docs/temp/pr-body.md` 生成時に同じ
`echo "$BRANCH" > $REPO_ROOT/docs/temp/.pr-body.owner` を実行する規約とする。両 skill
共通のフォーマットにすることで、所有権判定が確実になる。sidecar 方式
なので PR 本文には一切影響しない (HTML コメントすら残らない)。

`OWNED_BODY_FILE` フラグは Step 8 のクリーンアップ判定でのみ使う。
Step 4.5 のファイル編集ロジックは両経路で共通。Step 8 では
`OWNED_BODY_FILE=True` のとき `docs/temp/pr-body.md` と sidecar
(`docs/temp/.pr-body.owner`) の両方を rm する。create-pr 経路 (A) では
create-pr Step 9 が両方を rm する責務を持つ。

#### 0.4 ループ全体の制御変数

レビュー本体は **Step 1 → Step 2 → … → Step 6 のループ** で回す。
ループ制御変数を Step 0 末尾でまとめて初期化する:

```text
iteration = 1            # 1 始まり (1 巡目)
if MODE == "review-only":
    ITER_MAX = 1         # 単発レビュー (review-only モード)
elif ARG_DEPTH == "lightweight":
    ITER_MAX = 1         # バグ修正の軽量パス
elif ARG_DEPTH == "full":
    ITER_MAX = 3         # 機能追加のフルパス
else:
    ITER_MAX = 5         # 後方互換 (短縮禁止セクション参照)
DEPTH = ARG_DEPTH or "legacy"   # "lightweight" / "full" / "legacy"
ESCALATE_REASON = None   # escalate 検出時に理由を保持 (例: "base-conflict",
                         # "review-finding", "browser-regression")。
                         # Step 7 の最終報告で出力する
POSTED_TO_GITHUB = False # review-only モード Step 6.6.3 で gh pr review が
                         # 成功したら True を立てる。Step 8 cleanup で参照
                         # (True なら markdown を削除、False なら残置して
                         # ユーザーが手で投稿 / 編集できる状態に保つ)。
                         # 全 MODE 共通で初期化 (未定義参照リスクの根絶)
# 経路 A (create-pr 経由) で create-pr Step 4 が初回ブラウザテストを実施したか。
# 判定キーは「PR 本文に `## ブラウザテスト` セクションがあるか」。経路 B でも同じ。
# review-only モードでは使わない (Step 5 自体 skip)
BROWSER_TEST_DONE = (grep -qF '## ブラウザテスト' "$REPO_ROOT/docs/temp/pr-body.md" 2>/dev/null && echo True || echo False)
PUSH_FAILED = False      # 経路 B の Step 6.5 で push できなかったら True。Step 7 で参照 (全 MODE 共通で初期化)
RESOLVED_KEYS = set()    # fix-stable 収束キー。**前巡までに** auto-fix 済みの
                         # 指摘のキー (kind 名前空間付き "defect:..." / "judgment:...")。
                         # 本巡の auto-fix 分は Step 6 の収束判定の **後** に足す。
                         # 収束判定 (Step 6) では defect のみを対象とする
FIXED_KEYS_THIS_ROUND = set()   # 本巡 Step 4 で auto-fix した指摘のキー。毎巡 Step 4 先頭で空にする
                         # キー = file + kind + normalize(content)
                         #   normalize = 空白正規化 + 行番号除去 + 指摘番号 (R-n) 除去
```

**review-only モードの ITER_MAX が 1 である理由**: 修正をかけずに reviewer
を再起動しても、新しい情報が無いので findings は本質的に同じになる
(reviewer subagent は親文脈を持たないため、前巡の findings を知らない)。
fix モードの 5 巡が意味を持つのは「修正 → その修正が新たな問題を呼んでい
ないか再レビュー」のサイクルがあるため。review-only は単発で十分。

**ループ枠の明示** (Step 1 〜 Step 6 の流れ):

```text
while iteration <= ITER_MAX:
    Step 1 (base 再同期)
        → fix モード: rebase (push しない)
        → review-only モード: fetch のみ (BEHIND 報告のみ、HEAD 変更しない)
        → 意味的コンフリクト検出時 (fix のみ): ESCALATE_REASON = "base-conflict"
          → Step 4.5 (escalate 内容のみで対応履歴に追記、本巡 commit 無し)
          → break (Step 7 → Step 8 の順は必ず実施)
    Step 1.5 (docs-drift / test-gap 事前検出)
        → fix モード初巡のみ。review-only / 2 巡目以降は skip
        → 検出した乖離・ギャップがあれば修正 → commit (push はしない。最終 push は create-pr 側で行う)
    Step 2 (DEPTH に応じたレビュアーロール + Analyst の並列レビュー、MODE 共通)
        → iteration >= 3 なら各ロールのプロンプト末尾に後半巡制約を付与
          (全 DEPTH 共通。lightweight / review-only は ITER_MAX=1 のため走らない)
    Step 3 (指摘分類)
        → fix モード: silent-reject / escalate / auto-fix の 3 分類
        → review-only モード: silent-reject / report の 2 分類
    Step 4 (修正実行) — fix モードのみ
        → review-only モード: 本 Step は完全 skip
        → fix モード先頭で early-break 判定:
          (a) escalate が 1 件以上: ESCALATE_REASON = "review-finding"
              → Step 4.5 (escalate 内容のみで対応履歴に追記、本巡 commit 無し)
              → break
          (b) auto-fix が 0 件: break (本巡 commit 無し、Step 4.5 / Step 5
              は走らせない。レビュー収束 = 正常終了)
        → 上記以外は auto-fix 全件実装 → commit
    Step 4.5 (PR 本文「対応履歴」追記) — fix モードのみ
        → review-only モード: 本 Step は完全 skip (collaborator の PR 本文
          を書き換えないため)
        → fix モード: 本巡 commit がある場合に記録、escalate 直行経路では
          commit なしで escalate 理由のみを記録
    Step 5 (ブラウザテスト再走査) — fix モードのみ
        → review-only モード: 本 Step は完全 skip (本巡 commit が無いため)
        → fix モード: UI 影響あり時のみ。回帰失敗: ESCALATE_REASON =
          "browser-regression" → break
    Step 6 (収束判定 → RESOLVED_KEYS 更新 → iteration += 1)
        → 2 巡目以降、本巡の defect が前巡までに直した論点だけなら break (収束)
        → iteration > ITER_MAX なら break (Step 6.5 / 6.6 / Step 7 へ)
        → そうでなければループ先頭 (Step 1) へ
Step 6.5 (fix モード経路 B のみ、ループ後): final push + PR 本文更新
Step 6.6 (review-only モードのみ、ループ後): findings を GitHub PR に投稿
Step 7 (最終報告)
Step 8 (クリーンアップ、OWNED_BODY_FILE=True のときのみ rm)
```

**break 経路と Step 6.5 / 6.6 / 7 / 8 の関係 (重要)**: ループ内のどの Step で
break しても、その後の必須実施順序は **MODE で分岐**:

- **fix モード**: 任意の break → Step 6.5 (経路 B 条件付き) → Step 7 → Step 8 (Step 6.6 は skip)
- **review-only モード**: ITER_MAX=1 で正規 break → Step 6.6 → Step 7 → Step 8
  (review-only では Step 1 rebase / Step 4 escalate / Step 5 ブラウザ
  回帰の経路自体が存在しないため、break は ITER_MAX 到達のみ。Step 6.5 は
  fix モード専用のため skip)

**Step 7 → Step 8 は必ず順に実施する** (Step 8 をスキップすると
`OWNED_BODY_FILE=True` 経路で `docs/temp/pr-body.md` が、review-only 経路で
投稿成功した `docs/temp/pr${N}-review-comment.md` が残置される)。

---

### Step 1: base 再同期 (毎巡先頭)

**review-only モード時の差分**: collaborator のブランチを書き換えないため、
fetch のみ実施して BEHIND を報告し HEAD は変更しない:

```bash
if [ "$MODE" = "review-only" ]:
    # PR の head 情報を取得 (fork PR の場合は head リポの owner も必要)
    HEAD_REF=$(gh pr view "$N" --repo "$OWNER_REPO" --json headRefName -q .headRefName)
    HEAD_OWNER=$(gh pr view "$N" --repo "$OWNER_REPO" --json headRepositoryOwner -q .headRepositoryOwner.login)
    # cross-repo (fork PR) 判定: head のオーナーが base リポのオーナーと違う場合
    BASE_OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)

    # BEHIND 計算は **gh api compare に一本化** する。refspec 省略形の
    # `git fetch origin "$BASE" "$HEAD_REF"` は refs/remotes/origin/$HEAD_REF の
    # 更新を保証せず、local rev-list が stale な値を「成功」として返すため
    # (フォールバックが効かない)。同一リポは base...head、fork は base...owner:head
    if [ "$HEAD_OWNER" = "$BASE_OWNER" ]:
        BEHIND=$(gh api "repos/$OWNER_REPO/compare/$BASE...$HEAD_REF" -q .behind_by 2>/dev/null \
                 || echo 0)
    else:
        BEHIND=$(gh api "repos/$OWNER_REPO/compare/$BASE...$HEAD_OWNER:$HEAD_REF" -q .behind_by 2>/dev/null \
                 || echo 0)
    BEHIND=${BEHIND:-0}   # 空文字フォールバック (.behind_by が JSON null だった等)
    if [ "$BEHIND" -gt 0 ]:
        echo "[review-pr] PR #$N は base ($BASE) から $BEHIND コミット遅れています (rebase は author に依頼)"
    # 次の Step (Step 2: レビュー) へ進む。rebase は本 skill では行わない。
```

**fork PR の検出と compare 方式**: `headRepositoryOwner` を gh CLI 経由で
取得し base リポオーナー (`$OWNER_REPO` の前半) と比較。一致なら同一リポ branch、
不一致なら fork PR と判定して compare API の cross-repo 形式
(`compare/$BASE...$HEAD_OWNER:$HEAD_REF`) を使う。どちらも `.behind_by`
(= head が base から何コミット遅れているか) を読む。local の git fetch +
rev-list は使わない (上記コメント参照)。

以下は fix モードの挙動:

他 PR が間に入って base が進んでいる場合に追随する:

```bash
git fetch origin "$BASE"
BEHIND=$(git rev-list --count "HEAD..origin/$BASE")
if [ "$BEHIND" -gt 0 ]:
    git rebase "origin/$BASE"   # コンフリクト時の規則:
    #  - 機械的解消可能 (import 順 / フォーマット差等) → 自動解消
    #  - 意味的コンフリクト (同関数を両側で別意図に変更等) → escalate
    #    (ESCALATE_REASON = "base-conflict" を立てて Step 7 へ。
    #     Step 7 → Step 8 の順で必ず副作用処理を完了させる)
    #
    # 補足: $BASE は Step 0.2 でループ外で 1 回だけ取得しており、
    # ループ中の PR base 変更には追従しない。実運用ではレアなので
    # 許容している。base が動的に変わる運用がある場合は本 Step 冒頭
    # で `BASE=$(gh pr view "$N" --repo "$OWNER_REPO" --json baseRefName -q .baseRefName)`
    # を再実行する変種で対応

    # rebase 後も push しない (最終 push は create-pr Step 7 で 1 回だけ)
else:
    :
```

### Step 1.5: docs-drift / test-gap 事前検出 (fix モードのみ、初巡のみ)

→ **fix モードのとき**: `references/fix-steps.md` の Step 1.5 セクションを Read して手順に従う。
**review-only モードのとき**: skip。

### Step 2: レビュー実行 (DEPTH に応じたポジションロール構成)

**MODE 共通**: 本 Step (2.1 〜 2.5 全体) は fix モード / review-only モード
両方で実施する。

**毎巡先頭で diff ファイルを書き出す** (fix モード):

```bash
# REPO_ROOT は Step 0.2 で解決済み
git diff "origin/$BASE"...HEAD > "$REPO_ROOT/docs/temp/review-${iteration}.diff"
DIFF_PATH="$REPO_ROOT/docs/temp/review-${iteration}.diff"
PR_BODY_PATH="$REPO_ROOT/docs/temp/pr-body.md"
```

review-only モードでは `gh pr diff` の出力を一時ファイルに書き出す:

```bash
# REPO_ROOT は Step 0.2 で解決済み
gh pr diff "$N" --repo "$OWNER_REPO" > "$REPO_ROOT/docs/temp/review-${iteration}.diff"
DIFF_PATH="$REPO_ROOT/docs/temp/review-${iteration}.diff"
# PR 本文も一時ファイルに
gh pr view "$N" --repo "$OWNER_REPO" --json body -q .body > "$REPO_ROOT/docs/temp/review-pr-body.md"
PR_BODY_PATH="$REPO_ROOT/docs/temp/review-pr-body.md"
```

`DIFF_PATH` と `PR_BODY_PATH` は `references/reviewer-prompts.md` のプレースホルダーに代入される。

#### 2.1 レビュアーロールの並列起動

DEPTH に応じて起動するロールが変わる。1 メッセージで Agent ツールを並列に
呼ぶ (single message, multiple tool calls)。**全レビュアーロールは read-only**
(プロンプトで Edit / Write と作業ツリー・remote の変更を禁止し、worktree 分離で
親ツリーを守る。重要原則 2 / 4)。

**大規模 diff の zone 分割 (任意)**: diff ファイルの変更ファイル数が 20 以上
の場合、ファイルを非重複の zone（ディレクトリ単位 or 機能単位）に分割し、
各レビュアーロールの prompt に担当 zone のファイルリストを渡してトークン効率を
上げてよい。zone 分割した場合は全レビュアー完了後に **縫合部 (seam) 検査** を
追加で実施する: zone 間で共有される interface / trait / 型定義 / route 定義の
変更が、他 zone の利用箇所と整合しているかを Analyst が検証する。
zone 分割は判断に委ね、20 ファイル未満では不要。
**Security ロールは zone 分割の対象外**: 認証・認可・ミドルウェア等の
セキュリティ関連の変更は zone 境界をまたぐことが多いため、Security
レビュアーは常に全ファイルを対象とする。

**DEPTH == "lightweight"**: Correctness + Security (2 ロール)

```text
Agent(
    description = f"Correctness reviewer of {'PR #'+N if N else 'branch '+CURRENT_BRANCH}",
    subagent_type = "general-purpose",
    isolation = "worktree",
    prompt = CORRECTNESS_PROMPT
)
Agent(
    description = f"Security reviewer of {'PR #'+N if N else 'branch '+CURRENT_BRANCH}",
    subagent_type = "general-purpose",
    isolation = "worktree",
    prompt = SECURITY_PROMPT
)
```

**DEPTH == "full"**: Correctness + Security + Impact (3 ロール)

```text
# 上記 2 ロール + 以下を同一メッセージで並列起動:
Agent(
    description = f"Impact reviewer of {'PR #'+N if N else 'branch '+CURRENT_BRANCH}",
    subagent_type = "general-purpose",
    isolation = "worktree",
    prompt = IMPACT_PROMPT
)
```

**DEPTH == "legacy" (フラグなし)**: 後方互換で Reviewer A / B (2 ロール)

```text
Agent(
    description = f"Independent reviewer A of {'PR #'+N if N else 'branch '+CURRENT_BRANCH}",
    subagent_type = "general-purpose",
    isolation = "worktree",
    prompt = LEGACY_REVIEWER_PROMPT
)
Agent(
    description = f"Independent reviewer B of {'PR #'+N if N else 'branch '+CURRENT_BRANCH}",
    subagent_type = "general-purpose",
    isolation = "worktree",
    prompt = LEGACY_REVIEWER_PROMPT
)
```

##### 各ロールのプロンプト

→ **`references/reviewer-prompts.md` を Read して使用する**。
共通ヘッダ、CORRECTNESS_PROMPT、SECURITY_PROMPT、IMPACT_PROMPT、
LEGACY_REVIEWER_PROMPT、後半巡制約、fix-stable 収束キー除外指示の
全テンプレートが定義されている。

#### 2.2 全ロールの結果をマージ

全レビュアーロールのレポートを受け取り、以下を実施:

- 各 finding をパース → `{id, file, line, marks, kind, content, action, role}`
  (`kind` は `defect` または `judgment`。レビュアーが付けた種別をそのまま保持。
   `kind` が未指定の場合は `defect` として扱う — 後方互換)
- file + 近傍行 + 主題 が一致する finding 同士を 1 クラスタにまとめる
- 各クラスタに `agreement` (ヒットしたロール数) を付与
- クラスタごとに代表 finding (より具体的な記述の方) を採用
- **fix-stable 収束キーを生成**: 各 finding に `convergence_key =
  file + kind + normalize(content)` を付与 (パース結果に実在するフィールドだけで作る)
  - `normalize`: 空白正規化 + 行番号除去 + 指摘番号 (R-n) 除去

結果として、重複排除済み・agreement count 付き・収束キー付きの finding
リスト `FINDINGS_RAW` を得る。

#### 2.3 Pre-classification by parent (tool-existence claims)

Analyst (subagent) に投げる前に、**親しか確実に検証できない事実主張** は
親が直接処理する。これは重要な設計原則:

> Subagent は自分の toolset しか見えず、親の toolset は推測でしか
> 答えられない。tool-existence 系の主張を Analyst に投げると、
> subagent が自分の手元の deferred tool 一覧から推測して
> confidently false-verify する。

親による事前処理対象:

- 「ツール X が存在しない / 別名 Y が正しい」
  → 親が実在を確認できれば即座に silent-reject 候補にマーク
- 「親が今回のセッションで実際に使ったツール / コマンドが間違い」
  → 親が直近の tool 履歴から判断、誤指摘なら silent-reject

残りの事実主張を Analyst subagent に渡す。

#### 2.4 Analyst（裁定者）を起動

**MODE 共通**: review-only モードでも本 Step は実施する。Analyst は旧
Fact-checker の事実検証機能に加え、**全ロールの指摘を統合・重複排除・
最終判定する裁定者**としての役割を持つ。

```text
Agent(
    description = f"Analyst (judge) of {'PR #'+N if N else 'branch '+CURRENT_BRANCH} review findings",
    subagent_type = "general-purpose",
    isolation = "worktree",
    prompt = ANALYST_PROMPT
)
```

ANALYST_PROMPT:

```text
{'PR #'+N if N else 'ブランチ '+CURRENT_BRANCH} ({OWNER_REPO}) について、複数のレビュアーロール
（Correctness / Security / Impact）から得られた指摘リストを
**裁定** してください。

## 検証対象ファイル
- diff ファイル: `{DIFF_PATH}`
- PR 本文: `{PR_BODY_PATH}`
- Issue: PR 本文に Issue クローズキーワード (`Close(s|d)? #<N>` 等) があれば
  `gh issue view <N> --repo {OWNER_REPO}` で成功条件・受け入れ基準を取得する
  (目的適合性の検証に使う)

## 重要な制約 (作業ツリーを変更しないこと)
検証は上記ファイルの Read、および `gh api` / `gh issue view` / `gh search code`
での read-only な取得のみで行うこと。**`git checkout` / `git switch` /
`git branch` 作成 / `gh pr checkout` で作業ツリーや HEAD を変更してはならない**。
Edit / Write、および remote への書き込み (`git push` / `gh pr edit|review|merge` /
`gh api` の非 GET) も禁止。

## あなたの役割
1. **事実検証**: 各指摘の事実主張（関数の存否 / 行番号 / ファイル存否等）
   を verify し、"verified" / "false-claim" / "n/a" でマーク
2. **重複排除**: 複数ロールから同一の問題が報告されている場合を特定
3. **最終判定**: 各指摘について以下を判定:
   - 事実に基づいているか（false-claim なら reject 推奨）
   - 主マークの妥当性（[Must-fix] が本当にブロッカーか等）
   - PR の criticalDecisions 宣言（もしあれば）との整合性
4. **目的適合性**: PR の diff が Issue の要求スコープに収まっているか:
   - 要件に含まれない「ついでの改善」が混入していないか
   - diff が Issue の要件を超えていないか
   スコープ逸脱を検出したら [Must-fix] [defect] で報告する
5. **根拠性**: レビュアーの指摘が実際のコードに基づいているか:
   - 「〜の可能性がある」を「〜である」として扱っていないか
   - 推測を事実として報告している指摘がないか
   根拠なき指摘は false-claim 候補としてマークする
6. **criticalDecisions 検証** (PR 本文に Critical Decisions セクションが
   ある場合): 宣言と実際の diff を照合し、以下を検出:
   - 宣言漏れ（マイグレーションがあるのに dataModelChange: notApplicable）
   - 過小宣言（影響範囲が宣言より広い）
   宣言漏れ・過小宣言があれば [Must-fix] として追加報告する

## 検証対象外
- 「ツール X は存在しない / Y が正しい名称」のような subagent の
  toolset に依存する主張は対象外。"n/a" を返す。

## 返答フォーマット
指摘番号ごとに 1 行 (末尾に主マークの妥当性判定を付ける。Step 3 の分類は元の
主マークで行い、この判定は Step 7 の報告に「Analyst の再評価」として載せる):
  A-<id> — <verified|false-claim|n/a> — <根拠 or 補足> — <適切 | 過大→[提案マーク] | 過小→[提案マーク]>

追加指摘 (criticalDecisions 検証で発見) がある場合 (種別 [defect] / [judgment] を必ず付ける):
  A-NEW-<N> — <ファイルパス:行番号> — <マーク> — <種別> — <内容> — <推奨アクション>

## 縫合部検査 (zone 分割時のみ、以下が付与される)
zone 分割が適用された場合、以下の zone 境界ファイルリストが追加される。
zone 間で共有される interface / trait / 型定義 / route 定義 / 認証ミドルウェア
の変更が、他 zone の利用箇所と整合しているかを検証し、不整合があれば
[Must-fix] [defect] で追加報告する。
{ZONE_SEAM_FILES (zone 分割未使用時は本セクション自体を省略)}

## 検証対象の指摘リスト
{FINDINGS_RAW}
```

**legacy モードでは**: Analyst の代わりに Fact-checker を起動する
(`references/reviewer-prompts.md` の LEGACY_FACTCHECK_PROMPT。事実検証のみで
criticalDecisions 検証と主マーク再評価は行わない)。

#### 2.5 Analyst 結果を FINDINGS_RAW にマージ

各 finding に `factcheck` フィールド (`verified` / `false-claim` / `n/a` /
`parent-rejected`) を付与。Analyst の追加指摘（criticalDecisions 検証）も
finding リストに追加する (`agreement = 1`、`factcheck = "verified"` 扱い。
`convergence_key` と `kind` は Step 2.2 と同じ規則で付与し、`kind` 未指定は
defect)。`FINDINGS` という最終リストを得る。これを Step 3 に渡す。

**重要**: Skill ツールで他のレビュー skill を直接呼び出すと同一コンテキスト
実行になりバイアスが残るため不可。必ず Agent ツールでレビュアー + Analyst を
起動する。

### Step 3: 指摘分類

`FINDINGS` (= レビュアーロール (Correctness / Security / Impact、legacy では
Reviewer A/B) の集約 + Pre-class + Analyst (legacy では Fact-checker) の検証結果付き)
を以下のいずれかに振り分け、結果を各 finding の `classification` フィールド
(`silent-reject` / `escalate` / `auto-fix`、review-only では `silent-reject` /
`report`) に格納する (Step 6 の収束判定と Step 7 の報告が参照する)。
Analyst の主マーク再評価 (過大 / 過小) は分類に使わず、Step 7 の報告に載せる。

**review-only モード時の差分**: `silent-reject` と `report` (= GitHub
コメントに投稿) の 2 分類のみ。`escalate` / `auto-fix` の区別は無い (両者
とも report 扱い、Step 6.6 で投稿)。

**ただし、review-only では事実確認できなかった重大主張を silent-reject
すると、ITER_MAX=1 かつ「2 巡目以降で再評価する機会がない」ため、本来
collaborator に判断を委ねるべき重大指摘が黙って消える**。これを防ぐため、
review-only モードでは以下に該当する finding は **`[Question]` 扱いで report
する** (Step 6.6.1 の「質問 / 要確認」セクションに集約):

- legacy: (i) の `agreement == 1` かつ `[Must-fix]` かつ `factcheck != "verified"`
  (= ハルシネーション疑いの単独票重大主張)
- ポジションロール方式 (lightweight / full): `[Must-fix]` かつ `factcheck == "n/a"`
  (fix モードの escalate 振替と同じ条件。`agreement` は見ない)

```text
if MODE == "review-only":
    各 finding について:
        if factcheck == "false-claim" or factcheck == "parent-rejected":
            → silent-reject (誤指摘なので投稿しない)
        elif 上記の DEPTH 別「質問振替」条件に該当:
            → report (ただし「質問 / 要確認」セクションへ振替、
                      「要事実確認」の旨を 1 行添える)
        else:
            → report (主マーク [Must-fix] / [Should-fix] / [Nice-to-have] /
                      [Tradeoff] / [Security] をそのまま保持して Step 6.6 で
                      groupby 表示する)
    Step 4 / 4.5 / 5 を skip して Step 6 へ (ITER_MAX=1 なので即 break)
```

以下は fix モードの 3 分類:

#### (i) silent-reject (= 何もしない、Step 7 で件数のみ要約)

- `factcheck == "false-claim"`
- `factcheck == "parent-rejected"` (2.3 で親が tool 実在等を override)
- **legacy (Reviewer A/B) のみ**: `agreement == 1` かつ主マーク `== [Must-fix]`
  かつ `factcheck != "verified"` かつ `iteration < 3`
  (= 同一プロンプトの 2 名のうち片方しか拾わなかった重大主張が事実確認できない
  = ハルシネーション疑い、保留)。**ポジションロール方式 (lightweight / full) では
  この条件を適用しない**: 観点を分業しているため `agreement == 1` が常態で、
  Security 単独の [Must-fix] を黙って捨てることになる。ポジションロール方式で
  `agreement == 1` かつ `[Must-fix]` かつ `factcheck == "n/a"` (Analyst が検証
  できなかった) のときは silent-reject ではなく **escalate** に振り替える
  (下の (ii))。`agreement >= 2` の `[Must-fix]` は n/a でも (iii) の auto-fix
  (複数ロールが独立に同じ重大指摘を出しており、設計判断寄りでも捨てる側に倒さない)

**legacy の iteration >= 3 の例外**: 3 巡目以降は各ロールのプロンプトを
「マージブロッカー級のみ」に絞っているため (Step 2.1 後半巡制約参照)、
`agreement == 1` の `[Must-fix]` であっても silent-reject せず **escalate に
振り替える** (下の (ii) に該当として扱う)。理由: 後半巡の単独票 [Must-fix] は
「絞り込んだプロンプトでも片方の reviewer が拾った重大指摘」であり、
silent-drop すると 3 巡目以降の観点絞り込みがブロッカー級の見逃しを引き起こす
リスクがある。escalate に倒してユーザー判断を仰ぐ方が安全側。

#### (ii) escalate (= ユーザー確認が必要、真に判断分岐するもの)

- 修正でユーザーの過去の意図的な選択を覆すおそれ (例: revert)
- データ整合性 / マイグレーション影響あり
- アーキテクチャ判断 / 公開 API の breaking change
- 仕様判断 (要件解釈で複数の正解がありうる)
- 付加マーク `[Tradeoff]` 明示あり
- `[Security]` かつ修正方針が複数 (例: 「MD5 → bcrypt 移行戦略」)
- ポジションロール方式で `agreement == 1` かつ `[Must-fix]` かつ `factcheck == "n/a"`
  ((i) からの振替。単一ロールの重大主張を Analyst が検証できなかった = 人が見る)
- legacy の 3 巡目以降で `agreement == 1` かつ `[Must-fix]` かつ `factcheck != "verified"`
  ((i) の例外からの振替)

**escalate は Step 4 の early-break で同巡の auto-fix を無効化する** (fix-steps.md
Step 4 先頭)。lightweight (ITER_MAX=1) では escalate 1 件で 0 修正のまま終わるので、
振替条件を上の 2 つに限定している (agreement を見ない振替は、複数ロールが一致した
Must-fix まで escalate に倒して修正を止めてしまう)。

#### (iii) auto-fix (= 自動修正対象、上記以外すべて)

- 主マーク不問。判断分岐しないなら `[Must-fix]` でも auto-fix。
- `agreement == 2` (2 名一致) は信頼性高、優先的に auto-fix
- `agreement == 1` でも `factcheck == "verified"` なら auto-fix
- **`agreement == 1` かつ `factcheck == "n/a"` でも、主マークが
  `[Should-fix]` または `[Nice-to-have]` で修正コストが小さいもの
  (typo / 命名 / 不要 import / コメント補足 / 表記揺れ等) は
  auto-fix する**。閾値を過度に厳しくすると有用な提案を取りこぼす
- 例: typo / 命名 / 不要 import / 検証追加 / コメント補足 /
      ハードコード値の定数化 / 明らかなバグの単純修正 /
      `[Security]` だが対応方針が一意 (例: 「ハードコード API
      キーを env 変数に移す」)

silent-reject した指摘は subagent に問い合わせず、Step 7 で
「false-positive: 件数 + 主な内訳」として要約報告するだけにする。
1 巡ごとに些末な事実誤認でユーザー判断を仰ぐのは自動化の意味を損なう。

### Step 4, 4.5, 5: 修正実行 → 対応履歴更新 → ブラウザテスト再走査

→ **fix モードのとき**: `references/fix-steps.md` を Read して Step 4, 4.5, 5 の手順に従う。
**review-only モードのとき**: Step 4, 4.5, 5 は全て skip して Step 6 へ。

### Step 6: 巡数判定とループ継続

```text
# fix-stable 収束判定: 本巡の defect が **前巡までに** auto-fix 済みの
# 論点だけなら ITER_MAX 前でも終了。RESOLVED_KEYS は「前巡までの分」で比較し、
# 本巡の auto-fix 分 (FIXED_KEYS_THIS_ROUND) は判定の **後** に足す。
# (先に足すと本巡で直した defect が必ず差し引かれ、全 defect を auto-fix した巡で
# 常に 1 巡目で終了してしまう = 「修正が新たな問題を呼んでいないか」の再レビューが
# 走らない)。1 巡目は比較対象が無いので判定しない。
# judgment と silent-reject 済みの finding は判定に含めない
# (judgment を直し続けて巡数を消費するのを防ぐ / 誤指摘が永久に "new" にならない)
if MODE == "fix" and iteration >= 2:
    # kind 未指定は defect フォールバック。convergence_key は kind で名前空間を
    # 分ける (judgment として fix されたキーが同一 location の defect を遮蔽するのを防ぐ)
    new_defect_keys = {
        "defect:" + f.convergence_key
        for f in FINDINGS
        if (f.kind or "defect") == "defect" and f.classification != "silent-reject"
    } - RESOLVED_KEYS
    if len(new_defect_keys) == 0:
        RESOLVED_KEYS |= FIXED_KEYS_THIS_ROUND
        break  # 前巡までに直した論点しか出てこない → 収束。Step 7 へ

RESOLVED_KEYS |= FIXED_KEYS_THIS_ROUND   # 本巡の auto-fix 分を次巡以降の比較対象に加える
iteration += 1

if iteration > ITER_MAX:   # fix: depth 依存 / review-only: 1 巡完了
    break  # → Step 6.5 (fix 経路B) / Step 6.6 (review-only) → Step 7 へ
else:
    Step 1 へ戻る           # review-only は ITER_MAX=1 なのでここには来ない
```

ループ終了条件 (上の Step 0.4 のループ枠と整合):

| 終了原因 | 振る舞い | 該当 MODE |
|---|---|---|
| auto-fix が 0 件のレビューが返った | Step 4 で break、Step 7 へ (理想形) | fix |
| 5 巡完了 (iteration > ITER_MAX) | Step 6 で break、Step 7 へ (警戒シグナル or 収束 — 上の概要を参照) | fix |
| escalate を検出 (ESCALATE_REASON 設定) | 検出した Step で即 break、Step 7 へ | fix |
| ブラウザテスト回帰失敗 | 即中断して Step 7 へ | fix |
| base 同期で意味的コンフリクト | 即中断して Step 7 へ (ユーザー判断) | fix |
| 1 巡完了 (ITER_MAX=1) | Step 6 で break、Step 6.6 (GitHub 投稿) → Step 7 へ | review-only |

### Step 6.5: 経路 B final push (fix モード、経路 B のみ)

**fix モード + 経路 B (standalone、`OWNED_BODY_FILE=True` かつ `N` が非空) のみ
実行する**。経路 A (create-pr 経由) では create-pr Step 7 が push するため skip。
review-only モードでも skip。

レビューループで commit した修正をリモートに反映し、PR 本文を更新する:

**経路 B の force push は `--force-with-lease` のみ。`--force` は禁止。**

```bash
if [ "$MODE" = "fix" ] && [ "$OWNED_BODY_FILE" = "True" ] && [ -n "$N" ]:
    gh auth setup-git
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    # fetch 前に SHA を捕まえてリースを固定する (fetch 後に expect 値なしで
    # --force-with-lease を使うと、他人の新規コミットも黙って吹き飛ばす)
    EXPECTED=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
    git fetch origin "$BRANCH"
    if [ -n "$EXPECTED" ]:
        git push --force-with-lease="refs/heads/$BRANCH:$EXPECTED" || PUSH_FAILED=True
        # lease 不一致 (他人が先に push した) は reject される。force しない
    else:
        # 中断しない: ここで return すると Step 7 / 8 を通らず docs/temp/ が残る。
        # remote-tracking ref が無い = remote の履歴を一度も取り込んでいないので、
        # expect 値なしの force push は remote 側コミットを消しうる。push せず記録する
        echo "[review-pr] remote-tracking ref が無いため push しません (Step 7 で報告)"
        PUSH_FAILED=True
    if [ "$PUSH_FAILED" = "True" ]:
        # remote に無いコミットの「対応履歴」を PR 本文に載せない。本文はローカルの
        # docs/temp/pr-body.md に残し (Step 8 は OWNED_BODY_FILE=True でも
        # PUSH_FAILED=True なら rm しない)、Step 7 で手動手順を案内する
        :
    else:
        gh pr edit "$N" --repo "$OWNER_REPO" --body-file "$REPO_ROOT/docs/temp/pr-body.md"
```

### Step 6.6: GitHub に summary review コメントを投稿 (review-only モードのみ)

→ **review-only モードのとき**: `references/review-only-output.md` を Read して手順に従う。
**fix モードのとき**: skip して Step 7 へ。

### Step 7: 最終報告

**review-only モード時の差分**: auto-fix / commit / 対応履歴の話ではなく、
レビュー結果サマリを報告する:

- PR の URL と author
- レビュー方式 (DEPTH とロール構成、ITER_MAX=1)
- 主マーク別の finding 件数: `Must-fix M (うち Question 振替 K) / Should-fix S / Nice-to-have N / Question Q (=振替合計 K + [Tradeoff] 振替分)`
  - **二重カウント方針**: Question 振替された finding は **元の主マーク側
    の件数からは控除し、Question 件数のみに計上** する (Step 6.6.1 markdown
    のセクション振分と整合)。`Must-fix M` の `M` は section に実掲載された
    件数、`(うち Question 振替 K)` は内訳開示のみ
- defect / judgment の内訳 (finding 件数を種別で表示)
- silent-reject 件数 + 内訳
- 6.6 の投稿結果 (投稿済み / 編集後投稿済み / 投稿せず終了 / 投稿失敗)
- base 比 BEHIND コミット数 (あれば)

以下は fix モード:

以下をまとめて報告:

- PR の URL
- depth (lightweight / full / legacy) と起動ロール構成
- セルフレビュー巡数 (1-ITER_MAX)
- 各巡の auto-fix 件数推移 (例: `6 → 4 → 1 → 0`)
- 収束方式: 「auto-fix 0 件」/ 「fix-stable 収束（新規キー 0 件）」/ 「ITER_MAX 到達」
- ITER_MAX 到達ケースは「後半巡が Nice-to-have のみ = 収束」/「Must-fix/Should-fix が出続けた = 警戒」のどちらかを明記
- ブラウザテストの実施状況と最終結果
- escalate された指摘 (あれば内容と該当指摘箇所、`ESCALATE_REASON` 値)
- 経路 B で `PUSH_FAILED=True` なら、以下を案内する (force push を手で打たせない):
  `git fetch origin "$BRANCH"` → `git log --oneline HEAD..origin/$BRANCH` で remote 側
  だけにあるコミットを確認 → 空なら通常 `git push` で反映、あれば取り込んでから push。
  PR 本文の更新は push 後に `gh pr edit "$N" --repo "$OWNER_REPO" --body-file docs/temp/pr-body.md`
  で行う (ファイルは Step 8 で残置している)
- defect / judgment の内訳 (各巡の auto-fix 件数を defect / judgment 別に表示)
- silent-reject の件数と内訳 (主な理由)
- **spurious 監査リスト**: silent-reject した全件を一覧で掲載する (件数だけでなく
  個々の指摘内容を含める)。Analyst が誤って除外した真の defect を人間が発見
  できる唯一の面。件数が多い場合は折りたたみ表示可。
  **[Security] マーク付きの finding が silent-reject された場合は太字で強調し、
  除外理由を明記する** (セキュリティ指摘の除外は特にリスクが高いため)
- 残コミット履歴の概要

### Step 8: クリーンアップ

**いかなる break 経路 (自然終了 / 5 巡到達 / base-conflict / review-finding /
browser-regression escalate / review-only 投稿完了) でも、Step 7 完了後に
必ず本 Step を実行する**。スキップすると `OWNED_BODY_FILE=True` 経路で
`docs/temp/pr-body.md` が、review-only 経路で `docs/temp/pr${N}-review-comment.md`
が残置される。

```bash
# 全モード共通: レビュー diff ファイルを削除 (経路A は create-pr Step 9 でも
# 削除するが、経路B / review-only ではここが唯一のクリーンアップポイント)
rm -f "$REPO_ROOT"/docs/temp/review-*.diff

# fix モード: 本 skill 所有の PR 本文ファイルを削除
# (経路 B で push できなかった場合は、手動 push 後の gh pr edit に要るので残す。Step 7 の案内参照)
if [ "$OWNED_BODY_FILE" = "True" ] && [ "$PUSH_FAILED" != "True" ]:
    rm -f "$REPO_ROOT/docs/temp/pr-body.md" "$REPO_ROOT/docs/temp/.pr-body.owner"
    # -f で冪等性確保 (rebase 失敗時の途中状態などで既に消えていても
    # error にしない)。sidecar (.pr-body.owner) も同時に消すことで
    # 次回起動時の所有権判定が確実に「経路 B」になる

# review-only モード: review コメント markdown を削除
# ただしユーザーが 6.6.2 で「投稿せず終了」を選んだ場合は残置する
# (ユーザーが手で投稿 or 編集したいケース)
if [ "$MODE" = "review-only" ]:
    rm -f "$REPO_ROOT/docs/temp/review-pr-body.md"   # Step 2 で生成した PR 本文の一時コピー
    if [ "$POSTED_TO_GITHUB" = "True" ]:
        rm -f "$REPO_ROOT/docs/temp/pr${N}-review-comment.md"
```

`docs/temp/` に他のファイルがある場合があるため、**ディレクトリごと
削除しない**。呼び出し元 (create-pr) が用意したファイルは呼び出し元側
で削除されるため、本 skill は所有権を持つときだけ rm する。

#### 孤児 worktree の防御的 sweep

Step 2 で `isolation: "worktree"` で spawn したレビュアーロール / Analyst
(legacy では Reviewer A/B/Fact-checker) の
worktree (`.claude/worktrees/agent-*`) は、subagent が**正常終了すれば
harness が unlock + remove する**。この worktree の lock を保持
しているのは **subagent 自身ではなく親 harness プロセスの pid** であり、同一
セッション内では親が生きている限り孤児は基本的に発生しない (harness が自動
回収するため)。

孤児が残るのは **harness ごと異常終了した過去のセッション** のケースである。
親 harness が落ちると lock (= 既に死亡した過去 harness の pid) が残り、worktree
が `.claude/worktrees/` に残置される (`git worktree prune` は **lock 付きの実在
worktree を対象外とする**ため掃除できない)。累積するとリポ丸ごとの複製がディスク
を食い、serena の index 対象に入れば **メモリ肥大・OOM** を招く。

そこで Step 8 で **lock の pid が死んでいる孤児 worktree のみ**を掃除する。
これは「**過去の死亡セッションが残した孤児の防御的掃除**」であり、自セッション
の worktree (親 harness が生存 = `kill -0` が成功) は対象外になる (意図どおり)。
**lock の pid が生存している worktree は実行中の自セッション / 他の parallel
セッションが使用中の可能性があるため絶対に触らない**。無条件の
`rm -rf .claude/worktrees/*` は厳禁。

**この sweep ブロックは本 skill 内で唯一の実行可能 shell** であり、末尾「注意
事項」の「`bash` code block は疑似コード」宣言の **例外**である。Step 8 で親
エージェントが `bash` ツールで **verbatim 実行する** (他ブロックのような
`if [ ... ]:` 風の非実行疑似コードではない)。

```bash
# .claude/worktrees 配下で lock の pid が死んでいる孤児だけを掃除。
# pid が抽出できない (手動 lock 等) ものは安全側に倒して対象外。
# wt 抽出は substr で行末まで取る (パスにスペースが含まれても切れないように。
# $2 だと "worktree /path with space/..." が途中で切れる)。
git worktree list --porcelain | awk '
  /^worktree /{wt=substr($0,10)}
  /^locked/{ if (match($0,/pid [0-9]+/)) print wt"\t"substr($0,RSTART+4,RLENGTH-4) }
' | while IFS=$'\t' read -r wt pid; do
    case "$wt" in */.claude/worktrees/*) ;; *) continue ;; esac   # 対象限定
    kill -0 "$pid" 2>/dev/null && continue                        # 稼働中は触らない
    git worktree unlock "$wt" 2>/dev/null
    git worktree remove --force "$wt" 2>/dev/null \
      && git branch -D "worktree-$(basename "$wt")" 2>/dev/null   # 残骸ブランチも削除
done
git worktree prune
```

review-only モードでも本 sweep は実行してよい (collaborator のブランチや PR
本文には触れず、ローカルの孤児 worktree を掃除するだけなので read-only 制約に
反しない)。

---

## エスカレーション基準

skill が「ユーザー確認を取って停止する」のは以下のときのみ:

1. **コンフリクトの意味的解消** (Step 1)
   - 同じ関数や条件分岐を両側で別の意図に変更している
   - 何を残すかは仕様判断
2. **レビュー指摘のブロッカー / トレードオフ判定** (Step 3)
   - 上述の分類表参照
3. **ブラウザテストの回帰** (Step 5)
   - 修正で動いていた機能が壊れた

それ以外 (lint 違反 / 命名 / 不要 import / typo / 軽微なリファクタ提案等)
は **すべて自動修正する**。

---

## ブラウザテスト再走査判定基準

Step 5 を参照。判定の skip 判断は不要。条件が false でも実施したほうが
安心な場合は実施して構わない。

---

## 注意事項

- `docs/temp/` は `.gitignore` 対象外なので Step 8 で必ず掃除 (所有権ある場合)
- セルフレビューループ中の commit message は短くて良い
  (`chore: <N> 巡目レビュー指摘反映` 等)、プロジェクトの commit 規約
  (日本語 / 英語) に合わせる。squash は経路 A では create-pr Step 6 が自動で行う
  (経路 B の単独起動では squash しない)
- **指摘 0 件で自然終了 = 基本ゴール / 5 巡到達 = 警戒シグナル または収束**
  (上の概要を参照)。Step 7 の報告では 5 巡到達ケースの「巡ごとの auto-fix
  件数推移」と「収束 / 警戒の判定」を明記すること

### review-only モード固有の注意

- **`gh pr review --comment` 投稿は不可逆**: collaborator に通知が飛ぶため、
  Step 6.6.2 のユーザー承認を必ず取る。承認なしに投稿してはならない
- **collaborator のブランチ / PR 本文に一切書き込まない**: Step 4 / 4.5 /
  Step 1 の rebase は完全 skip。`gh pr edit` も呼ばない
- **MODE 自動判定の通知**: フラグなしで `/review-pr <N>` 起動時、
  collaborator PR と判定して review-only に自動切替する場合は、Step 0.2.5
  の `echo` で明示的に通知する (ユーザーが意図と違う MODE に切り替わった
  ことに気付けるよう)
- **MODE 自動判定の override**: 自分の collaborator (write access あり) の
  PR で「許可を得て auto-fix したい」ケースは `--fix` フラグで明示 override
- **subagent 制約はそのまま**: review-only でもレビュアーロール + Analyst
  は `isolation: "worktree"` で spawn し、prompt で作業ツリー変更を禁止する
  (重要原則 4)。read-only レビューだからといって isolation を緩めない
- awaiting 宣言 (`AskUserQuestion` 経由の PermissionRequest) は本 skill
  には **含めない**。create-pr など呼び出し元の責務として残す。単独起動
  時はユーザーがそのまま手元で次操作する想定で awaiting 化不要
- frontmatter `allowed-tools` の `mcp__playwright__*` は **Step 5 の
  ブラウザテスト再走査用**。実起動の条件は `BROWSER_TEST_DONE == True`
  (= PR 本文に `## ブラウザテスト` セクションあり) かつ
  Step 5 UI 影響あり判定 (a)/(b)/(c)/(d) のいずれか。経路 A (create-pr 経由)
  で初回ブラウザテスト実施済の PR が主想定だが、経路 B (ad-hoc) でも判定
  キーが満たされれば起動する (allowed-tools での ACL は経路を区別しない)。
  起動の skip ロジックは Step 5 末尾の skip 条件で集中管理されているため、
  ACL に経路区別を持たせる必要はない
- 本 skill 内の `bash` 言語タグ付き code block は原則 **LLM 向け疑似コード**
  (Python 風 `if [ ... ]:` / `else:` 等を許容)。実行可能な shell スクリプト
  ではない。実機実行する箇所は親エージェントが個別に `bash` ツールで実行
  する責務。**例外: Step 8「孤児 worktree の防御的 sweep」のブロックのみは
  verbatim 実行を意図した実シェル** (当該節に明記)
- `review-pr` 自身を **Skill ツール経由で呼ぶ** ことは可能 (create-pr Step 5
  の委譲経路) で、その場合 `review-pr` 本体は親と同一コンテキストで走る。
  これがバイアスを生まないのは、本 skill が「コードを書いた本人がレビュー
  する」ことを禁じているのは **レビュアーロール / Analyst (legacy では
  Reviewer A/B/Fact-checker) subagent の独立性**
  のためで、orchestration 層 (= `review-pr` 本体) の独立性ではないため。
  実際のレビューは Step 2 で必ず Agent ツール経由 (`isolation: "worktree"`)
  でレビュアーロール + Analyst を spawn することで担保される
