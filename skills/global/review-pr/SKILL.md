---
name: review-pr
description: 指定 PR (引数なしならカレントブランチの PR) をセルフレビューする。Reviewer A / B + Fact-checker の 3 エージェント並列構成 (worktree 分離)。自分の PR は「指摘 0 件 (auto-fix = 0)」まで最大 5 巡で auto-fix モード、collaborator の PR は自動的に review-only モードで GitHub に inline review コメント (Reviews API で行アンカー投稿) を投稿 (フラグ --review-only / --fix で明示 override 可。--fix で他者 PR を上書きするには対象リポへの write 権限が必要)。「/review-pr 123」「PR レビューして」「指摘消して」「セルフレビュー」のような自然言語で起動。create-pr Step 6 からも内部呼び出しされる。
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, Agent, mcp__playwright__browser_navigate, mcp__playwright__browser_click, mcp__playwright__browser_type, mcp__playwright__browser_evaluate, mcp__playwright__browser_resize, mcp__playwright__browser_take_screenshot, mcp__playwright__browser_snapshot, mcp__playwright__browser_tab_select, mcp__playwright__browser_console_messages
---

# PR セルフレビュー (auto-review/fix ループ)

「PR レビューして」と言われたら、指定 PR を独立セルフレビューする。
**2 つの動作モード** がある:

| MODE | 想定対象 | 挙動 |
|---|---|---|
| **fix** | 自分が author の PR | 「独立セルフレビューで指摘が無くなった (= auto-fix が 0 件) 状態」にして戻す。最大 5 巡で auto-fix + commit + push + PR 本文「対応履歴」追記まで自動 |
| **review-only** | 他者 (collaborator) が author の PR | レビューのみ実施し、findings を inline review コメント (行アンカー) として GitHub PR に投稿 (ユーザー承認後)。行に紐付かない指摘は review 本文に集約。collaborator のブランチ・PR 本文には一切書き込まない |

### MODE 決定ロジック (Step 0.2.5 で確定)

| 入力 | 結果 MODE |
|---|---|
| `/review-pr 5 --review-only` (明示) | review-only |
| `/review-pr 5 --fix` (明示) | fix |
| `/review-pr 5` フラグなし + PR author == 自分 | fix |
| `/review-pr 5` フラグなし + PR author != 自分 | review-only (auto 切替、Step 0.2.5 でユーザーに通知) |
| 自動検出失敗 (gh api user エラー等) | review-only (safer default) |

create-pr Step 6 からの内部呼び出しは作りたての自分の PR が対象なので、自然に fix モードのまま (明示フラグは渡さない)。

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

**「小さい修正だから」「diff が少ないから」という理由で、Step 2 のレビュー構成 (Reviewer A / B 2 名並列 + Fact-checker 1 名) や巡数上限 (fix モード: 5 巡 / review-only モード: 1 巡) を独断で短縮することは禁止する**。

### 適用範囲

本ルールが禁止対象とするのは **Step 2 のレビュー構成と巡数上限の独断短縮のみ**。skill 内に明記された条件付き skip パス (Step 5 のブラウザテスト未実施時 skip、Step 4 先頭の early-break による escalate / auto-fix=0 中断等) は本ルールの対象外であり、明記された条件で正規に skip / 中断する。

**review-only モードの ITER_MAX=1 は本ルールの「短縮」に該当しない**: Step 0.4 の説明 (line 「review-only モードの ITER_MAX が 1 である理由」参照) のとおり、修正をかけずに reviewer を再起動しても新しい情報が得られない構造的理由による設計上の正規値。fix モードの「5 巡」と同列の規範であり、「独断で減らした」ものではない。

「短縮」とは構成や上限の **下振れ方向** (削減方向) を指す。上振れ (レビュアーを 3 名以上に増やす等) は本ルールの対象外だが、想定外の挙動を生むので推奨もしない。

### 理由

- 修正のコード量と影響範囲は比例しない。1 行の変更でも race condition / セキュリティ脆弱性を生むことはある (運用上観測された実例: 数行の修正で `os.replace` の inode race が 2 巡目に独立レビュアーから発見されたケース、1 行修正で shell injection が 1 巡目に検出されたケース等)
- 「簡素な修正は本当に簡素なら自然に 1-2 巡で収束する」のがこの skill の終了条件 (auto-fix 0 件で break) の意図。短縮判断を呼び出し側に持ち込むと、その判定基準自体がブレて一貫性が損なわれる (短縮指示を撤回したケースで 2 巡で自然終了することが繰り返し観測されている)
- 過剰な巡数を恐れて短縮するくらいなら、終了条件を信じて回す方が安全

### 具体的に禁止される行動

- Reviewer A / B 2 名並列起動を 1 名に減らす (常に 2 名 + Fact-checker 1 名 = 3 エージェント並列で起動)
- Fact-checker subagent を「面倒だから」省略する (Step 2.3 の parent pre-classification は **前段処理として常に実施した上で**、Step 2.4 の Fact-checker subagent も **残指摘について必ず起動** する。parent 処理は subagent の代替ではない)
- 「1 巡で終わらせる前提」で 2 巡目以降のレビュー実施判断をスキップする (auto-fix 0 件で自然 break するまで毎巡レビューを起動する)
- 「これは些細だから」と escalate 候補を勝手に auto-fix 扱いに格下げ
- 逆方向 (短縮の対称) として **「auto-fix 可能な指摘を不必要に escalate に格上げして 2 巡目以降を打ち切る」のも禁止**。Step 3 の分類基準に厳密に従う

例外: **無し**。skill の流れ通りに必ず実施する。

## 重要原則

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
   変更を禁止する (二重防御)**。理由: Agent (subagent) は
   `isolation` を指定しない限り親と cwd / git 作業ツリーを共有する。
   本リポ運用のように `~/.claude/*` がリポ作業ツリーへの symlink で
   配布される環境では、subagent が「実機テスト」のつもりで
   `git checkout` / `gh pr checkout` すると **ライブ設定
   (settings.json / hooks) ごと別ブランチ版にリバートされる事故が起きうる**
   (実例として、subagent の checkout で `SessionStart` matcher が
   複数回 main 版に巻き戻る事象が観測されている)。worktree 分離で親ツリーを
   物理的に守り、プロンプト制約で checkout 自体を抑止する。レビューは
   `gh pr diff` / `gh pr view` のみで完結するため、作業ツリーの書き換えは
   本来不要。

---

## 手順

### Step 0: 入力解決 + 起動コンテキスト判定

#### 0.1 PR 番号 + フラグの解析

本 skill の **`args` パラメータ (Skill ツール)** をスペース区切りで解析する。
PR 番号 (数値) は 1 つ、フラグ (`--review-only` / `--fix`) は最大 1 つ:

```bash
# 受け取った args 例:
#   "123"                 → ARG_PR=123 / ARG_MODE_FLAG=""
#   "123 --review-only"   → ARG_PR=123 / ARG_MODE_FLAG="--review-only"
#   "--fix 123"           → ARG_PR=123 / ARG_MODE_FLAG="--fix"
#   ""                    → ARG_PR=""  / ARG_MODE_FLAG=""  (カレントブランチ
#                                                          の PR を後段で引く)
#   "--review-only"       → ARG_PR=""  / ARG_MODE_FLAG="--review-only"
#                         (カレントブランチの PR を review-only で)

ARG_PR=""
ARG_MODE_FLAG=""
for tok in $args:   # 擬似コード: $args を空白区切りでトークン化したものを順に処理
    if tok in ("--review-only", "--fix"):
        ARG_MODE_FLAG = tok
    elif tok matches regex ^[0-9]+$:   # 整数のみ厳密 match (例: "5x" や "1-foo" は不可)
        ARG_PR = tok
    elif tok starts with "--":
        # フラグらしき token だが未知 → typo の可能性が高い (例: "--review--only")。
        # silent failure させると collaborator PR を fix モードで auto-fix する事故に
        # 直結するため、明示的に中断してユーザーに再入力を促す
        echo "[review-pr] 未知のフラグ '$tok' を検出。typo の可能性があります"
        echo "[review-pr] サポートするフラグ: --review-only / --fix"
        中断 (skill return)
    else:
        # 数値でもフラグでもないトークン (例: PR URL の prefix 等) は将来拡張のため
        # 警告のみ出して無視
        echo "[review-pr] 未知のトークン '$tok' を無視します"

# PR 番号の確定
if [ -n "$ARG_PR" ]:
    N=$ARG_PR
else:
    N=$(gh pr view --json number -q .number 2>/dev/null)
    if [ -z "$N" ]:
        # 「中断」 = 呼び出し元 (create-pr など) に "PR 不在" を返して本 skill
        # を終了する疑似コード。`exit` は同一コンテキスト実行下では使わず、
        # Step 7 簡易出力 → Step 8 (経路 B のときのみ rm) を経て return する
        echo "現在のブランチに紐づく PR がありません。先に /create-pr を実行してください"
        中断 (skill return)
```

`ARG_MODE_FLAG` は Step 0.2.5 で `MODE` に解決する。

#### 0.2 リポジトリ情報の取得

```bash
OWNER_REPO=$(gh repo view --json owner,name -q '.owner.login + "/" + .name')
# Step 0.2.5 / Step 1 で必要な PR フィールドをまとめて 1 回で取得 (API 効率化)
PR_META=$(gh pr view "$N" --repo "$OWNER_REPO" --json baseRefName,author 2>/dev/null)
BASE=$(echo "$PR_META" | jq -r .baseRefName)
PR_AUTHOR=$(echo "$PR_META" | jq -r .author.login 2>/dev/null)
# --repo "$OWNER_REPO" 明示: ad-hoc 起動 (経路 B) で cwd と PR リポが
# 不一致 (例: 別 parallel から他リポの PR を /review-pr する) のケースで、
# cwd の git remote から別 PR を解決して無関係なリポの情報を取得する事故
# を防ぐ。注意: OWNER_REPO は依然 cwd 依存 (gh repo view --json owner,name)
# なので、本 skill は **対象 PR のリポ cwd 内から呼ぶ前提**。OWNER_REPO 自体
# が間違っていれば以降の全 gh pr 系コマンドが無関係なリポを参照する
```

#### 0.2.5 MODE の解決 (fix vs review-only)

PR author と現在ユーザーを比較して MODE を決定。明示フラグがあれば最優先で
それを採用、無ければ author 一致で自動判定:

```bash
# PR_AUTHOR は Step 0.2 で取得済み
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
  すでに存在 (create-pr Step 5 で生成済み) → このファイルを編集して
  `gh pr edit --body-file` で反映。**ファイル削除は呼び出し元
  (create-pr Step 8) の責務**、本 skill は触らない
- **(B) 単独起動 (ad-hoc)**: `docs/temp/pr-body.md` が無い →
  `gh pr view --json body` で現本文を取得して `docs/temp/pr-body.md`
  に書き出し、以降の巡で同ファイルを編集する。**本 skill が作った
  ファイルなので終了時 (Step 8) に rm する**

> **経路 A の有効化条件**: 経路 A は、`create-pr` 側が **`docs/temp/pr-body.md` と
> sidecar `docs/temp/.pr-body.owner` を生成し、本 skill に引き継ぐ規約に対応した
> 実装** になっている場合のみ自然に発動する。本 skill 単体を使う場合や、
> create-pr 実装が古いインライン形 (sidecar を書き出さない / 「対応履歴」を
> 委譲しない) のままなら、Step 0.3 の判定で sidecar が見つからないため
> **常に経路 B (= 本 skill が現本文を取得して新規生成) が選択される**。経路 B
> でも skill としての挙動は正しく完結するので、create-pr が経路 A 対応の
> 実装になっていなくても安全。

判定ロジック (sidecar マーカー `docs/temp/.pr-body.owner` で PR 番号を
記録して所有権を識別。PR 本文には何も埋め込まない):

```bash
mkdir -p docs/temp
OWN_MARK_FILE="docs/temp/.pr-body.owner"

if [ -f docs/temp/pr-body.md ]:
    # 既存ファイルあり → sidecar の PR 番号で判定
    if [ -f "$OWN_MARK_FILE" ] && [ "$(cat "$OWN_MARK_FILE" 2>/dev/null)" = "$N" ]:
        OWNED_BODY_FILE=False   # 呼び出し元 (create-pr) が当該 PR 用に
                                # 用意したファイル → 最後の rm は呼び出し元
    else:
        # sidecar 無し / 別 PR のゴミファイル → 経路 B 扱いで上書き再生成
        gh pr view "$N" --repo "$OWNER_REPO" --json body -q .body > docs/temp/pr-body.md
        echo "$N" > "$OWN_MARK_FILE"
        OWNED_BODY_FILE=True
else:
    # ファイル無し → 経路 B
    gh pr view "$N" --repo "$OWNER_REPO" --json body -q .body > docs/temp/pr-body.md
    echo "$N" > "$OWN_MARK_FILE"
    OWNED_BODY_FILE=True         # 本 skill が作った → Step 8 で rm
```

呼び出し元 (create-pr Step 5) も `docs/temp/pr-body.md` 生成時に同じ
`echo "$N" > docs/temp/.pr-body.owner` を実行する規約とする。両 skill
共通のフォーマットにすることで、所有権判定が確実になる。sidecar 方式
なので PR 本文には一切影響しない (HTML コメントすら残らない)。

`OWNED_BODY_FILE` フラグは Step 8 のクリーンアップ判定でのみ使う。
Step 4.5 のファイル編集ロジックは両経路で共通。Step 8 では
`OWNED_BODY_FILE=True` のとき `docs/temp/pr-body.md` と sidecar
(`docs/temp/.pr-body.owner`) の両方を rm する。create-pr 経路 (A) では
create-pr Step 8 が両方を rm する責務を持つ。

#### 0.4 ループ全体の制御変数

レビュー本体は **Step 1 → Step 2 → … → Step 6 のループ** で回す。
ループ制御変数を Step 0 末尾でまとめて初期化する:

```text
iteration = 1            # 1 始まり (1 巡目)
if MODE == "review-only":
    ITER_MAX = 1         # 単発レビュー (review-only モード)
else:
    ITER_MAX = 5         # 最大巡数 (短縮禁止セクション参照)
ESCALATE_REASON = None   # escalate 検出時に理由を保持 (例: "base-conflict",
                         # "review-finding", "browser-regression")。
                         # Step 7 の最終報告で出力する
POSTED_TO_GITHUB = False # review-only モード Step 6.5.3 で Reviews API 投稿が
                         # 成功したら True を立てる。Step 8 cleanup で参照
                         # (True なら payload JSON を削除、False なら残置して
                         # ユーザーが手で投稿 / 編集できる状態に保つ)。
                         # 全 MODE 共通で初期化 (未定義参照リスクの根絶)
if MODE == "review-only":
    BROWSER_TEST_DONE = False   # review-only は Step 5 自体 skip するため使わないが、
                                # 未定義参照リスク根絶のため明示的に False で初期化
else:
    # fix モード: PR 本文に「## 動作確認スクリーンショット」セクションが
    # あれば create-pr Step 3 で初回ブラウザテストを実施済 → True
    BROWSER_TEST_DONE=$(gh pr view "$N" --repo "$OWNER_REPO" --json body -q .body \
                        | grep -qF '## 動作確認スクリーンショット' && echo True || echo False)
REBASED_THIS_ITERATION = False   # Step 1 で毎巡先頭に再代入されるが、全 MODE 共通
                                  # 変数として未定義参照リスクの根絶のため init
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
        → fix モード: rebase + push
        → review-only モード: fetch のみ (BEHIND 報告のみ、HEAD 変更しない)
        → 意味的コンフリクト検出時 (fix のみ): ESCALATE_REASON = "base-conflict"
          → Step 4.5 (escalate 内容のみで対応履歴に追記、本巡 commit 無し)
          → break (Step 7 → Step 8 の順は必ず実施)
    Step 2 (3 エージェント並列レビュー: Reviewer A / B + Fact-checker、MODE 共通)
        → (fix モードのみ) iteration >= 3 なら REVIEWER_PROMPT 末尾に後半巡
          制約を付与 (review-only は ITER_MAX=1 のためこの分岐は走らない)
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
        → 上記以外は auto-fix 全件実装 → commit → push
    Step 4.5 (PR 本文「対応履歴」追記) — fix モードのみ
        → review-only モード: 本 Step は完全 skip (collaborator の PR 本文
          を書き換えないため)
        → fix モード: 本巡 commit がある場合は SHA を含めて記録、escalate
          直行経路では commit なしで escalate 理由のみを記録
    Step 5 (ブラウザテスト再走査) — fix モードのみ
        → review-only モード: 本 Step は完全 skip (本巡 commit が無いため)
        → fix モード: UI 影響あり時のみ。回帰失敗: ESCALATE_REASON =
          "browser-regression" → break
    Step 6 (iteration += 1)
        → iteration > ITER_MAX なら break (Step 6.5 / Step 7 へ)
        → そうでなければループ先頭 (Step 1) へ
Step 6.5 (review-only モードのみ、ループ後): findings を GitHub PR に投稿
Step 7 (最終報告)
Step 8 (クリーンアップ、OWNED_BODY_FILE=True のときのみ rm)
```

**break 経路と Step 6.5 / 7 / 8 の関係 (重要)**: ループ内のどの Step で
break しても、その後の必須実施順序は **MODE で分岐**:

- **fix モード**: 任意の break → Step 7 → Step 8 (Step 6.5 は skip)
- **review-only モード**: ITER_MAX=1 で正規 break → Step 6.5 → Step 7 → Step 8
  (review-only では Step 1 rebase / Step 4 escalate / Step 5 ブラウザ
  回帰の経路自体が存在しないため、break は ITER_MAX 到達のみ)

**Step 7 → Step 8 は必ず順に実施する** (Step 8 をスキップすると
`OWNED_BODY_FILE=True` 経路で `docs/temp/pr-body.md` が、review-only 経路で
投稿成功した `docs/temp/pr${N}-review.json` が残置される)。

---

### Step 1: base 再同期 (毎巡先頭)

**review-only モード時の差分**: collaborator のブランチを書き換えないため、
fetch のみ実施して BEHIND を報告し HEAD は変更しない:

```bash
if [ "$MODE" = "review-only" ]:
    # PR の head 情報を 1 回でまとめて取得 (API 効率化)
    HEAD_META=$(gh pr view "$N" --repo "$OWNER_REPO" --json headRefName,headRepositoryOwner 2>/dev/null)
    HEAD_REF=$(echo "$HEAD_META" | jq -r .headRefName)
    HEAD_OWNER=$(echo "$HEAD_META" | jq -r .headRepositoryOwner.login)
    BASE_OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)

    # BEHIND 計算は **gh api compare API に一本化** する。
    # 理由: 旧実装で `git fetch origin "$BASE" "$HEAD_REF"` + local `git rev-list`
    # を使うパスがあったが、refspec 省略形 fetch では `refs/remotes/origin/$HEAD_REF`
    # の更新が config 依存で保証されない (FETCH_HEAD のみ更新されるケースあり)。
    # 結果として古い ref を見て stale な BEHIND を返すリスクがあった。
    # BEHIND は informational only (rebase は本 skill では行わない) なので、
    # ホットパスではなく、API 1 回の往復コストを払って正確性を優先する。
    if [ "$HEAD_OWNER" = "$BASE_OWNER" ]:
        # 同一リポ: compare/<base>...<head> の .behind_by = head が base から遅れている数
        BEHIND=$(gh api "repos/$OWNER_REPO/compare/$BASE...$HEAD_REF" -q .behind_by 2>/dev/null || echo 0)
    else:
        # fork PR: compare API は base...head_owner:head_ref 形式を要求
        BEHIND=$(gh api "repos/$OWNER_REPO/compare/$BASE...$HEAD_OWNER:$HEAD_REF" -q .behind_by 2>/dev/null || echo 0)
    BEHIND=${BEHIND:-0}   # 空文字フォールバック (.behind_by が JSON null だった等)
    if [ "$BEHIND" -gt 0 ]:
        echo "[review-pr] PR #$N は base ($BASE) から $BEHIND コミット遅れています (rebase は author に依頼)"
    # 次の Step (Step 2: レビュー) へ進む。rebase は本 skill では行わない。
    # REBASED_THIS_ITERATION は Step 0.4 で init 済み (review-only では参照されない)
```

**fork PR の検出と compare 方式**: `headRepositoryOwner` を gh CLI 経由で
取得し base リポオーナー (`$OWNER_REPO` の前半) と比較。同一リポなら
`compare/$BASE...$HEAD_REF` の `.behind_by`、fork PR なら
`compare/$BASE...$HEAD_OWNER:$HEAD_REF` の `.behind_by` を使う。両ケースとも
**「PR の head が base から何コミット遅れか」という同一意味の値** を取得する。

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
    # で `BASE=$(gh pr view "$N" --json baseRefName -q .baseRefName)`
    # を再実行する変種で対応

    # rebase 後はローカルと remote が分岐するので force-with-lease 必須。
    # ただし HEAD と upstream が一致していれば push 不要 (二重 push 防止)。
    if [ "$(git rev-list --count @{u}..HEAD)" -gt 0 ]:
        git push --force-with-lease
    REBASED_THIS_ITERATION=True
else:
    REBASED_THIS_ITERATION=False
```

### Step 2: レビュー実行 (Reviewer A / B + Fact-checker の 3 段並列構成)

**MODE 共通**: 本 Step (2.1 〜 2.5 全体) は fix モード / review-only モード
両方で実施する。review-only モードでも Reviewer A / B 並列起動 (2.1)、結果
マージ (2.2)、parent pre-classification (2.3)、Fact-checker subagent 起動
(2.4)、fact-check 結果マージ (2.5) のいずれも省略しない (Step 3 の review-only
分類は factcheck フィールドを参照するため必須)。

#### 2.1 Reviewer A と Reviewer B を並列起動

1 メッセージで Agent ツールを 2 つ並列に呼ぶ (single message, multiple tool calls)。
両者とも同じプロンプトを与えるが、独立な subagent なので結果は別個に出る:

```text
Agent(
    description = f"Independent reviewer A of PR #{N}",
    subagent_type = "general-purpose",
    isolation = "worktree",   # 親の作業ツリーを汚さない (重要原則 4)
    prompt = REVIEWER_PROMPT  # 下記 (iteration で内容が分岐する)
)
Agent(
    description = f"Independent reviewer B of PR #{N}",
    subagent_type = "general-purpose",
    isolation = "worktree",   # 親の作業ツリーを汚さない (重要原則 4)
    prompt = REVIEWER_PROMPT
)
```

REVIEWER_PROMPT (f-string で補間してから渡す。`iteration` の値に応じて
**3 巡目以降は後半巡制約ブロックを追加する**):

```text
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
   の形で構造化して返す。**行番号は改修後ファイル (diff 新側 / RIGHT) の
   絶対行番号** を使う (review-only モードはこの行に inline コメントを
   アンカーするため。旧側 / diff 相対の行番号だとアンカーできず body に降格する)。
   **ファイルパスはリポルート相対** (diff の `b/` 除去後と同形。例
   `skills/global/review-pr/SKILL.md`) で報告する (worktree 絶対パスは使わない。
   突合はパス完全一致のため、絶対パスだと全 finding が body に降格する)
6. 1 つの finding につき 1 行にまとめ、指摘番号 (R-1, R-2, ...) を
   付けて返す。後段のファクトチェック / 集約処理がパースしやすい
   ようにするため
```

**3 巡目以降 (`iteration >= 3`) は以下のブロックを REVIEWER_PROMPT
末尾に追加する**:

```text
## 後半巡の制約 (3 巡目以降、本巡が該当)
前 2 巡で Must-fix / Should-fix の主要指摘は概ね出尽くしていることを
前提に、本巡では **マージブロッカー級のみ** を報告対象とする:
  - [Must-fix] 機能不具合 / ロジック誤り
  - [Security] (任意重大度、セキュリティ影響があれば必ず報告)
以下は本巡では報告しないこと (= 後半巡の Nice-to-have 発掘ループを抑制):
  - typo / コメント文言 / 命名の好み / 不要 import の追加発見
  - 「より良い書き方」「他の選び方もある」系の Nice-to-have
前巡までに記録された指摘の再指摘も避ける (gh pr view {N} で本文の
「対応履歴」セクションを確認し、既出の論点は除外)。「対応履歴」
セクションが本文に無ければこのチェックは skip して良い (Step 4.5 の
追記順序の都合で対応履歴がまだ生成されていないケース等が該当)。
指摘が無ければ「指摘なし」と明示的に返す。
```

(根拠: 後半巡の Reviewer プロンプトを「マージブロッカー級のみ」に絞ると、
5 PR 連続で 5 巡到達していたケースが 2-4 巡で自然収束することが運用上
観測された。後半巡 Nice-to-have の発掘ループを抑制する効果が大きい)

#### 2.2 Reviewer A / B の結果をマージ

2 レポートを文字列で受け取り、以下を実施:

- 各 finding をパース → `{id, file, line, marks, content, action}`
- file + 近傍行 + 主題 が一致する finding 同士を 1 クラスタにまとめる
- 各クラスタに `agreement = 2` (両者ヒット) または `1` (片方のみ) を付与
- クラスタごとに代表 finding (より具体的な記述の方) を採用

結果として、重複排除済みかつ agreement count 付きの finding リスト
`FINDINGS_RAW` を得る。

#### 2.3 Pre-classification by parent (tool-existence claims)

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

#### 2.4 Fact-checker を 1 つ起動 (親 pre-classification 後の残りについて)

**MODE 共通**: review-only モードでも本 Step は実施する。`factcheck` フィールド
の値 (Fact-checker subagent が付与する `verified` / `false-claim` / `n/a` と、
Step 2.3 で親が付与する `parent-rejected` の 4 値) は、Step 3 の review-only
分類で silent-reject 判定 (`factcheck == "false-claim"` または `factcheck ==
"parent-rejected"`) と `[Question]` 振替判定 (`agreement == 1` かつ
`factcheck != "verified"` かつ `iteration < 3` の単独票 [Must-fix]、詳細条件は
Step 3 (i) 参照) の両方で参照されるため、Fact-checker subagent 起動は省略
できない (短縮禁止セクションの「Fact-checker subagent を『面倒だから』省略
する」禁止条項と同じ趣旨)。

`FINDINGS_RAW` から「親が処理済み」のものを除いた指摘を渡して verify させる:

```text
Agent(
    description = f"Fact-check of PR #{N} review findings",
    subagent_type = "general-purpose",
    isolation = "worktree",   # 親の作業ツリーを汚さない (重要原則 4)
    prompt = FACTCHECK_PROMPT
)
```

FACTCHECK_PROMPT (`{N}` 等は実値に置換して prompt 引数に渡す):

```text
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
{FINDINGS_RAW}   # ← 2.2 で得たリストをテキスト化して埋め込む
```

#### 2.5 Fact-check 結果を FINDINGS_RAW にマージ

各 finding に `factcheck` フィールド (`verified` / `false-claim` / `n/a` /
`parent-rejected`) を付与。`FINDINGS` という最終リストを得る。これを
Step 3 に渡す。

**重要**: Skill ツールで他のレビュー skill を直接呼び出すと同一コンテキスト
実行になりバイアスが残るため不可。必ず Agent ツール 3 個 (Reviewer A,
Reviewer B, Fact-checker) を使う。

### Step 3: 指摘分類

`FINDINGS` (= Reviewer A/B 集約 + Pre-class + Fact-check 結果付き) を以下
のいずれかに振り分ける。

**review-only モード時の差分**: `silent-reject` と `report` (= GitHub
コメントに投稿) の 2 分類のみ。`escalate` / `auto-fix` の区別は無い (両者
とも report 扱い、Step 6.5 で投稿)。

**ただし、review-only では (i) silent-reject の `agreement == 1 かつ
[Must-fix] かつ factcheck != verified かつ iteration < 3` 条件 (=
ハルシネーション疑いの単独票重大主張) を silent-reject すると、ITER_MAX=1
かつ「2 巡目以降で再評価する機会がない」ため、本来 collaborator に
判断を委ねるべき重大指摘が黙って消える**。これを防ぐため、review-only
モードでは当該条件に該当する finding は **`[Question]` 扱いで report する**
(Step 6.5.1 の「質問 / 要確認」セクションに集約):

```text
if MODE == "review-only":
    各 finding について:
        if (i) silent-reject 条件のうち factcheck="false-claim" / "parent-rejected":
            → silent-reject (誤指摘なので投稿しない)
        elif (i) の agreement==1 / [Must-fix] / factcheck unverified 条件:
            → report (ただし「質問 / 要確認」セクションへ振替、
                      「単独票・要事実確認」の旨を 1 行添える)
        else:
            → report (主マーク [Must-fix] / [Should-fix] / [Nice-to-have] /
                      [Tradeoff] / [Security] をそのまま保持して Step 6.5 で
                      groupby 表示する)
    Step 4 / 4.5 / 5 を skip して Step 6 へ (ITER_MAX=1 なので即 break)
```

以下は fix モードの 3 分類:

#### (i) silent-reject (= 何もしない、Step 7 で件数のみ要約)

- `factcheck == "false-claim"`
- `factcheck == "parent-rejected"` (2.3 で親が tool 実在等を override)
- `agreement == 1` かつ主マーク `== [Must-fix]` かつ `factcheck != "verified"`
  かつ `iteration < 3`
  (= 単独票の重大主張が事実確認できない = ハルシネーション疑い、保留)

**iteration >= 3 の例外**: 3 巡目以降は REVIEWER_PROMPT を「マージブロッカー
級のみ」に絞っているため (Step 2.1 後半巡制約参照)、`agreement == 1` の
`[Must-fix]` であっても silent-reject せず **escalate に振り替える**
(下の (ii) に該当として扱う)。理由: 後半巡の単独票 [Must-fix] は
「絞り込んだプロンプトでも片方の reviewer が拾った重大指摘」であり、
silent-drop すると後半巡制約導入のメリット (収束加速) と引き換えに
ブロッカー級の見逃しを引き起こすリスクがある。escalate に倒してユーザー
判断を仰ぐ方が安全側。

#### (ii) escalate (= ユーザー確認が必要、真に判断分岐するもの)

- 修正でユーザーの過去の意図的な選択を覆すおそれ (例: revert)
- データ整合性 / マイグレーション影響あり
- アーキテクチャ判断 / 公開 API の breaking change
- 仕様判断 (要件解釈で複数の正解がありうる)
- 付加マーク `[Tradeoff]` 明示あり
- `[Security]` かつ修正方針が複数 (例: 「MD5 → bcrypt 移行戦略」)

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

### Step 4: 修正実行

**review-only モード時は本 Step 全体を skip して Step 6 へ進む**
(Step 3 で `report` のみ確定済み、修正は行わない)。

**Step 4 先頭 (early-break 判定)** — fix モード:

```text
if escalate が 1 件以上:
    ESCALATE_REASON = "review-finding"
    Step 4.5 へ (escalate 内容のみで対応履歴に追記、本巡 commit 無し)
    その後 break (Step 7 へ)

if auto-fix が 0 件:
    break  # レビュー OK、ループ終了 (本巡 commit 無しのため Step 4.5 / 5 は skip)
```

**Step 4 本体 (auto-fix 実装)**:

auto-fix を全件実装 (Edit / Write):

```bash
git add <変更ファイル>
# commit message はプロジェクトの規約に合わせる
# (日本語 OK のリポなら日本語、英語規約なら英語)
git commit -m "chore: <iteration> 巡目レビュー指摘反映"

# 本巡の commit SHA を Step 4.5 の対応履歴テンプレートに渡すため取得
CURRENT_SHA=$(git rev-parse --short HEAD)

# push 種別の分岐:
if [ "$REBASED_THIS_ITERATION" = "True" ]:
    git push --force-with-lease
else:
    git push
```

### Step 4.5: PR 本文「対応履歴」の更新 (毎巡必須)

**review-only モード時は本 Step 全体を skip**: collaborator の PR 本文を
書き換えないため。Step 6.5 で GitHub に投稿する review コメントには履歴
セクションを含めない (1 回切りの投稿で対応履歴の概念がない)。

以下は fix モード:

次巡のレビュアーが古い情報で評価しないように、push と同時に PR 本文も
更新する。**escalate 直行経路 (本巡 commit 無し) でも本 Step を必ず通す**
ことで、escalate 理由を PR 本文に残しレビュー経路を可視化する。
`docs/temp/pr-body.md` は Step 0.3 ですでに用意済み (経路 A:
呼び出し元が用意 / 経路 B: 本 skill が現本文から生成)、両経路で以降の
処理は共通:

`docs/temp/pr-body.md` を編集:

- 既存の Summary / 設計判断 / 維持されたノウハウは保持
- 「対応履歴」セクションを追加または更新し、今巡の auto-fix /
  escalate / silent-reject の件数と主な内訳を 3-5 行で要約
- 本巡 commit がある場合: `### N 巡目 (commit $CURRENT_SHA)` (Step 4 で
  取得した short SHA を使う)
- escalate 直行経路で commit 無しの場合: `### N 巡目 (commit なし、escalate
  中断 / 理由: $ESCALATE_REASON)`
- Test plan のチェック状態も最新化 (完了項目は `[x]`)

```bash
gh pr edit "$N" --repo "$OWNER_REPO" --body-file docs/temp/pr-body.md
```

#### 「対応履歴」セクションテンプレート

```markdown
## 対応履歴

### {iteration} 巡目 (commit {CURRENT_SHA})
- レビュアー: 2 名 / Fact-checker: 1 名
- agreement 2/2: {件数} 件
- agreement 1/2: {件数} 件
- 分類: auto-fix {件数} / silent-reject {件数} / escalate {件数}
- 主な auto-fix: {短い箇条書き 2-3 件}
- silent-reject 内訳: {件数} 件 (主な理由: 事実誤認 {件数} / 主観 1 票 {件数})
- escalate (あれば): {内容}

### 2 巡目 (commit {CURRENT_SHA})
...

### {iteration} 巡目 (commit なし、escalate 中断 / 理由: base-conflict)
- レビュアー: (Step 2 未実施のため省略)
- escalate 理由: base 同期で意味的コンフリクト検出 (詳細: {詳細})
- ユーザー判断待ち。Step 7 で詳細報告
```

**placeholder 記法**: テンプレ内 `{iteration}` は本巡の iteration 番号 (1〜5)、
`{CURRENT_SHA}` は Step 4 で取得した `$CURRENT_SHA` の値で展開する。`{件数}` /
`{内容}` 等の `{...}` 系 placeholder は親エージェントが実値に展開してから
`gh pr edit --body-file` で投稿する (Step 6.5.1 の `{...}` プレースホルダ規約と
統一。GitHub Markdown で `<...>` は未知 HTML タグとして strip される可能性が
あるため、本 skill は全 markdown テンプレで `{...}` 形式を採用)。

ファイル削除は **しない** (経路 A の呼び出し元 = create-pr が Step 8 で
削除する。経路 B は本 skill の Step 8 で削除する)。

#### 所有権ライフサイクル (両 skill 共通の要約)

fix モードの `docs/temp/pr-body.md` + sidecar `docs/temp/.pr-body.owner` の所有権:

- **経路 A (create-pr → review-pr, fix モード)**: create-pr Step 5 が **作成** →
  review-pr が **編集** (毎巡 Step 4.5 で対応履歴追記) →
  create-pr Step 8 が **削除** (両ファイル)
- **経路 B (review-pr 単独 ad-hoc, fix モード)**: review-pr Step 0.3 が **作成**
  (gh pr view から生成) → review-pr 自身が **編集** (毎巡 Step 4.5) →
  review-pr Step 8 が **削除** (両ファイル)

review-only モードの `docs/temp/pr${N}-review.json` の所有権:

- **経路 C (review-only モード)**: review-pr Step 6.5.1 が **作成** (review payload
  JSON を新規 Write、`mkdir -p docs/temp` で親ディレクトリ存在も担保) → ユーザー承認後
  Step 6.5.3 で `gh api .../reviews --input` 投稿 → Step 8 が
  **削除** (ただし `POSTED_TO_GITHUB=True` のときのみ。投稿せず終了 / 投稿失敗
  の場合は残置してユーザーが手で投稿 / 編集 / 破棄)。**`pr-body.md` / sidecar
  は review-only では一切作成しない**。

### Step 5: ブラウザテストの再走査 (UI 影響のある修正のときのみ)

**review-only モード時は本 Step 全体を skip**: 本巡 commit が無いため
(Step 4 を skip した結果)。

**前提**: Step 4 で `auto-fix == 0 件` の自然 break / escalate / `iteration == 1`
の base-conflict などで **本巡 commit が無い場合は本 Step 全体を skip する**
(ループ枠の break 経路で本 Step に到達しない設計、Step 0.4 のループ制御参照)。
本 Step が走るのは「本巡で 1 件以上の auto-fix commit が生成された後」のみ。

判定対象は今巡 (= 直近 commit) で変更されたファイルのみ:

```bash
git diff HEAD~1 HEAD --name-only
```

UI 影響あり判定 (いずれか満たせば再走査)。**下記パターンは一例**なので、
自プロジェクトのビュー/コンポーネント/ルーティングの配置に読み替える
(例: React/Next の `app/**`・`pages/**`、Vue の `src/**`、Rails の
`app/views/**`、Laravel の `resources/views/**`・`.blade.php` 等):

- **(a) パス判定**: ブラウザテスト対象の拡張子/ディレクトリパターンに該当
  (`.vue`, `.tsx`, `.jsx`, `.razor`, `.blade.php`, ビューディレクトリ配下 等)
- **(b) スタイル系**: `*.css`, `*.scss`, `tailwind.config.*` に変更あり
- **(c) ルーティング系**: ルーティング定義ファイルに変更あり
  (例: `routes/web.php`, Next の `app/**/page.tsx`, `config/routes.rb` 等)
- **(d) クラス変更**: コンポーネント class 属性 / Tailwind utility class の追加削除を
  機械判定 (`git diff HEAD~1 HEAD -- '*.vue' '*.tsx' '*.jsx' '*.blade.php' 'resources/views/**' | grep -E '^[+-].*(class=| class:)'`。
  末尾のパスは自プロジェクトのビューディレクトリに置き換える。例: Rails `app/views/**`、Vue `src/**`)

```text
if BROWSER_TEST_DONE  # Step 0.4 で判定: PR 本文に「動作確認スクリーン
                      # ショット」セクションがあれば True (経路 A/B 共通)
    AND (a または b または c または d):
    全ケースを再走査
    失敗したら ESCALATE_REASON = "browser-regression" を立てて Step 7 へ進む
```

以下は完全 skip (= 正常な終了パス、escalate しない):

- `BROWSER_TEST_DONE == False` (画面変更なし判定で初回もブラウザテスト
  未実施だった PR、経路 A/B 共通)
- 今巡の auto-fix が typo / import 整理など UI に無関係なもののみ

### Step 6: 巡数判定とループ継続

```text
iteration += 1
if iteration > ITER_MAX:   # fix mode: 5 巡完了 / review-only: 1 巡完了
    break  # → Step 6.5 (review-only のみ) → Step 7 へ
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
| 1 巡完了 (ITER_MAX=1) | Step 6 で break、Step 6.5 (GitHub 投稿) → Step 7 へ | review-only |

### Step 6.5: GitHub に inline review コメントを投稿 (Reviews API, review-only モードのみ)

**fix モード時は本 Step 全体を skip して Step 7 へ**。

review-only モードで Step 3 の `report` バケットに振り分けた findings を、
**GitHub Reviews API のバッチ review** (`gh api --method POST
repos/$OWNER_REPO/pulls/$N/reviews`) で投稿する。1 回の API 呼び出しで
「**行アンカーされた inline コメント複数 + 全体サマリ本文**」を **1 レビュー
= 1 通知** としてまとめて送る (旧実装の `gh pr review --comment` による summary
一括投稿を置き換える。`gh pr review` は inline 行コメントを付けられないため
Reviews API を直接叩く)。投稿前に必ず **ユーザー承認** を取る (collaborator に
通知が飛び、PR レビュー履歴に永続記録される。API での削除は技術的には可能
だが、UI からは手動操作が必要で、いったん見た / 通知を受け取った相手の印象を
取り消すことはできない)。

**inline / body の振分 (hybrid)**: GitHub の行コメントは **PR diff に現れて
いる行にしか付けられない**。そこで各 finding を次で振り分ける:

- **アンカー可能** (`file:line` があり、その行が PR diff の新側 (RIGHT) hunk に
  存在) → `comments[]` の要素として **inline 投稿**
- **アンカー不能** (行番号なし / 行が diff 外 / ファイル・アーキ全体の指摘 /
  行に紐付かない「質問 / 要確認」/ 補足メタ) → review の `body` (サマリ) に集約

diff 外の行を inline 指定すると API が **422 で review 全体を拒否**するため、
6.5.1 のアンカー可能性検証は必須。

#### 6.5.1 review payload (JSON) の生成

書き出し先ディレクトリの存在を担保してから Write する:

```bash
mkdir -p docs/temp
```

**(1) アンカー可能な行の集合を作る**。PR diff の hunk header から新側 (RIGHT)
の行番号を洗い出し、各 finding の `(path, line)` がこの一覧に含まれるものだけ
inline にする (含まれなければ body へ降格):

```bash
# 注意: plain な `gh pr diff` を使う (デフォルトで unified diff)。
# `--patch` を付けると git format-patch 形式 (From/Subject 等のコミット
# ヘッダ付き) になり awk が誤パースするので付けない。
gh pr diff "$N" --repo "$OWNER_REPO" \
  | awk '
      # ヘッダ領域 (in_body=0) と hunk body (in_body=1) を構造的に区別する。
      # body 内の内容行 "+++ ..." (元テキストが "++ ...") をヘッダと誤認しない。
      /^diff --git / { in_body=0; f=""; next }                   # ファイル境界でリセット
      /^@@ /  { match($0,/\+[0-9]+/); ln=substr($0,RSTART+1,RLENGTH-1)+0; in_body=1; next }
      in_body==0 && /^\+\+\+ / { f=$0; sub(/^\+\+\+ b\//,"",f); next }  # 対象ファイル (行全体抽出=スペース対応)
      in_body==0 { next }                                        # ヘッダ領域の他行 (--- / index / mode 等) は無視
      f=="" || f=="+++ /dev/null" { next }                       # 新側なし (削除ファイル) は対象外
      /^\+/   { print f"\t"ln; ln++; next }                      # 追加行 = コメント可
      /^ /    { print f"\t"ln; ln++; next }                      # 文脈行 = コメント可
      /^-/    { next }                                           # 削除行は新側行を進めない
    '
```

この一覧を保持し、各 finding について `(finding.file, finding.line)` が一覧に
**完全一致で含まれるか** を確認する。finding.file が worktree 絶対パス
(reviewer は worktree 分離で走るため起こりうる) の場合はリポルート prefix を
除去して**リポルート相対に正規化**してから突合する (一覧の path は diff の
`b/` 除去後 = リポルート相対なので、これを揃えないと全 finding が不一致で
body 降格する)。含まれれば `comments[]` に入れ、含まれなければ body の該当
セクションへ降格する。これが 6.5 冒頭の「アンカー可能性検証」の実体。**範囲
コメント (`start_line`+`line`) を使う場合は、start_line から line までの
**全行が同一 path の一覧に連続して含まれる** ことを確認する (= 範囲全体が
単一 hunk 内。単一行ケースと同じ厳密さで突合する)。start_line が diff 外だと、
また範囲が hunk をまたぐと、GitHub が 422 で review 全体を拒否する。

**(2) `docs/temp/pr${N}-review.json` を Write する** (ファイル名の `${N}` と
テンプレ内の `{...}` **波括弧プレースホルダ** は親エージェントが実値に展開して
から Write する。GitHub Markdown で `<...>` は未知 HTML タグとして strip され
うるため body 内でも `<N>` ではなく `{N}` 形式を使う):

```json
{
  "event": "COMMENT",
  "body": "{サマリ本文 markdown}",
  "comments": [
    {"path": "{file}", "line": {line}, "side": "RIGHT", "body": "{finding 本文}"}
  ]
}
```

- **`comments[]` (inline)**: アンカー可能な finding 1 件 = 1 要素。`body` の
  先頭に主マークを明示する (例: `**[Must-fix]** [Security] パスワードがログ
  出力されている — {推奨アクション}`)。複数行にまたがる指摘は `start_line`
  + `start_side` + `line` + `side` (いずれも `"RIGHT"`) で範囲指定してよい
  (開始側は `side` ではなく `start_side` を使う。片方だけだと開始行が無視される)。
- **`body` (サマリ本文)**: 以下を Markdown で集約する (件数 0 の項目は省略):

```markdown
## レビュー結果

PR #{N} を読みました (inline コメント {I} 件 + 以下)。

### 全体・アンカー不能の指摘 (X 件)
- `{file}` — **[{主マーク}]** {行に紐付かない指摘 / ファイル・アーキ全体の指摘} — {推奨アクション}

### 質問 / 要確認 (Y 件)
- `{file}:{line}` — {内容} (主マーク {Must-fix/...} + 単独票・要事実確認 / 付加マーク [Tradeoff]) — {推奨アクション}

### 補足
- レビュー方式: Reviewer A/B + Fact-checker 独立 3 agent 並列、worktree 隔離
- 内部 silent-reject: {N} 件 (内訳: false-claim {N} 件 / parent-rejected {N} 件 / その他 {N} 件)
- base ({BASE}) 比 BEHIND: {N} コミット (rebase は author 側で対応をお願いします)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

**JSON エスケープに注意**: 上記 body / 各 `comments[].body` は複数行 Markdown
なので、JSON 文字列として埋め込む際は **改行を `\n`、`"` を `\"` にエスケープ**
して valid JSON にすること (親エージェントが Write する `pr${N}-review.json`
は `gh api --input` がパースできる正しい JSON でなければ 400 で失敗する)。手で
エスケープすると引用符・バックティック混じりの finding 本文で崩れやすいので、
**`jq -n` で組み立てて構文的に valid を保証する**のが安全 (例:
`jq -n --arg body "$BODY" --argjson comments "$COMMENTS" '{event:"COMMENT", body:$body, comments:$comments}'`。
`--arg` は文字列を自動エスケープする)。

**マーク → 表現の規約** (主マーク = 1 個必須、付加マーク = 0 以上):

- **主マーク** (`Must-fix` / `Should-fix` / `Nice-to-have`): アンカー可能なら
  inline コメント body の先頭に `**[主マーク]**` を付けて表現する。付加マーク
  `[Security]` は body 内に明示 (例: `**[Must-fix]** [Security] ...`)。
- **`[Tradeoff]` 付き / 「質問 / 要確認」振替の finding**: 行に紐付く場合でも
  **inline にせず body の「質問 / 要確認」セクションに集約** (判断・議論を促す
  指摘はレビュー本文でまとめて提示するほうが読みやすい)。ここに入るのは次の 2 種:
  - Step 3 review-only 分類で `[Question]` 振替された finding
    (単独票 [Must-fix] + factcheck unverified)
  - 付加マーク `[Tradeoff]` 付きの finding (主マーク不問)
- **アンカー不能な主マーク finding** (行が diff 外 / 行番号なし): body の
  「全体・アンカー不能の指摘」セクションに主マークを明示して載せる。

件数 0 のセクションは省略する。各 finding は元の `R-<id>` を保持しなくて
よい (内部 ID なので external には意味がない)。「単独票 [Must-fix] の保留」
は前述の [Question] 振替により review-only では原則発生しないので、補足の
silent-reject 内訳には載せない (false-claim / parent-rejected が主因)。

#### 6.5.2 ユーザー承認

生成した review payload を **人間可読な形で表示** してから (inline コメントは
`{file}:{line} — {body}` の一覧として、body サマリはそのまま全文表示)、
`AskUserQuestion` で確認。**question 文には必ず以下のガード文言を含める**:
「**投稿すると collaborator に通知が飛び、PR レビュー履歴に永続記録されます
(API での削除は技術的には可能ですが、UI からは手動操作が必要で、いったん
見た / 通知を受け取った相手の印象は取り消せません)。inline コメントと本文に
問題ないか最終確認をお願いします**」。

初回 AskUserQuestion 呼び出し例 (options に必ず (a)(b)(c) 3 つを提示):

```text
AskUserQuestion({
    questions: [{
        question: "投稿すると collaborator に通知が飛び、PR レビュー履歴に永続記録されます...本文に問題ないか最終確認をお願いします。",
        header: "投稿確認",
        multiSelect: false,
        options: [
            {label: "投稿する",                    description: "そのまま Reviews API で inline review を投稿"},
            {label: "payload を編集してから投稿",   description: "JSON を手で編集後、再度確認"},
            {label: "投稿せず終了",                  description: "Step 7 へ進み、payload JSON は残置"},
        ]
    }]
})
```

回答ごとの遷移:

- (a) 投稿する → 6.5.3 へ
- (b) payload を編集してから投稿 → 以下のループを実行:
    ```text
    EDIT_LOOP_MAX = 3   # 連続 (b) 選択の上限。到達したら (c) 扱いで終了
    edit_loop_count = 0
    while True:
        edit_loop_count += 1
        if edit_loop_count > EDIT_LOOP_MAX:
            echo "[review-pr] 編集ループが ${EDIT_LOOP_MAX} 回連続したため (c) 投稿せず終了として扱います"
            POSTED_TO_GITHUB = False
            break    # 6.5.3 を skip して Step 7 へ
        ユーザーに「`docs/temp/pr${N}-review.json` を手で編集して
        完了したら教えてください」と伝えて待機 (会話上の自然な往復)
        ユーザーから完了報告を受領
        編集後の payload を人間可読な形で再表示
        AskUserQuestion で (a)(b)(c) を再提示 (同じ options 構成)
        if 回答 == (a): break    # 6.5.3 へ
        if 回答 == (c):
            POSTED_TO_GITHUB = False
            break    # 6.5.3 を skip して Step 7 へ
        if 回答 == (b): continue    # ループ継続 (上の count++ で増える)
    ```
- (c) 投稿せず終了 → `POSTED_TO_GITHUB` は False のまま 6.5.3 を skip
    (Step 7 へ、payload JSON は Step 8 で残置されユーザーが手で
    投稿 / 編集 / 破棄)

#### 6.5.3 投稿

承認後に Reviews API で投稿し、成功可否を `POSTED_TO_GITHUB` に反映する。
`repos/$OWNER_REPO/...` のように **path に `$OWNER_REPO` を埋める** (`gh api`
には `--repo` フラグが無いため。cwd 依存の誤投稿を防ぐ):

```bash
if gh api --method POST "repos/$OWNER_REPO/pulls/$N/reviews" \
       --input "docs/temp/pr${N}-review.json"; then
    POSTED_TO_GITHUB=True
    echo "[review-pr] PR #$N に inline review を投稿しました"
else
    # 典型的な失敗は comments[] のどれかが diff 外の行を指して 422 になるケース。
    # inline を諦めるが、**comments[] を body 末尾にテキスト列挙してから** 1 度だけ
    # 再投稿する。単に comments を捨てると inline 指摘 (Must-fix/Should-fix) が丸ごと
    # 消え、しかも fallback 成功で POSTED_TO_GITHUB=True → Step 8 が payload を削除して
    # 復旧不能になる。body に畳み込めば旧実装の summary 一括と同等 (全 finding が
    # body に載る、ただし行アンカーは無し) になる:
    tmp_body="docs/temp/pr${N}-review-bodyonly.json"
    # body 冒頭に「inline 失敗の縮退投稿」である旨を前置し、intro の
    # 「inline コメント {I} 件」表示との齟齬を打ち消す。
    jq '{event, body: ("> ⚠️ inline 行アンカー投稿に失敗したため、全指摘を本文にまとめています (行アンカーなし)。\n\n"
          + .body + (if (.comments|length) > 0
          then "\n\n### inline 投稿できなかった指摘\n"
               + ([.comments[] | "- `\(.path):\(.line)` — \(.body)"] | join("\n"))
          else "" end))}' "docs/temp/pr${N}-review.json" > "$tmp_body"
    if gh api --method POST "repos/$OWNER_REPO/pulls/$N/reviews" --input "$tmp_body"; then
        POSTED_TO_GITHUB=True
        echo "[review-pr] inline 投稿に失敗したため、指摘を body にまとめた summary で投稿しました (行アンカーなし)"
        rm -f "$tmp_body"
    else
        POSTED_TO_GITHUB=False
        # 元 payload (pr${N}-review.json) は 422 の原因行を含むため手動でも同じ 422 を
        # 繰り返す。inline を外した body-only 版 ($tmp_body) を残置し、そちらの手動投稿を促す。
        echo "[review-pr] 投稿に失敗しました。inline を外した body-only 版を残置します: $tmp_body (元の inline payload: docs/temp/pr${N}-review.json)"
        # ESCALATE_REASON は立てない (投稿失敗を escalate に格上げする運用はせず、
        # Step 7 で投稿失敗ステータスをそのまま報告する)
    fi
fi
```

**`--repo "$OWNER_REPO"` の規約**: `gh pr <subcommand> "$N"` は `--repo` 無し
だと cwd の git remote から PR を解決するため、cwd と PR リポが不一致だと
別 PR への誤投稿事故が起きうる (例: 別 parallel から ad-hoc で他リポの PR を
レビューするケース、レビュー対象 PR のリポを clone していないケース等)。
Step 0.2 で `$OWNER_REPO` を取得済みなので、**MODE 共通で全 `gh pr` 系
コマンドに `--repo "$OWNER_REPO"` を明示する**:

- **review-only モード**: 参照系の全 `gh pr` 系コマンドで必須。不可逆な
  GitHub 投稿は Step 6.5.3 の Reviews API (`gh api --method POST
  repos/$OWNER_REPO/pulls/$N/reviews`) で行うが、`gh api` は `--repo` フラグを
  持たないため **path に `$OWNER_REPO` を埋め込む** ことで同じ誤投稿防止を担保する
- **fix モード**: 基本は「自分の PR をローカル展開して fix する」前提だが、
  Step 0.3 で初期 body 取得、Step 4.5 で本文編集など参照・編集系コマンドが
  cwd 依存だと、Fix した branch を間違ったリポに push する 2 次事故に
  つながりうる。Step 0.2 / 0.3 / 0.4 / 4.5 / Step 1 で `gh pr view` / `gh pr edit`
  を呼ぶ箇所はすべて `--repo "$OWNER_REPO"` 明示で統一する

`event=COMMENT` は中立レビュー (Approve / Request changes ではない)。投稿成功
(`POSTED_TO_GITHUB=True`、inline / body-only fallback いずれの成功も含む) なら
Step 8 で payload JSON を削除、失敗 (`POSTED_TO_GITHUB=False`) なら残置して
ユーザーに手動投稿を促す。いずれの分岐でも Step 7 → Step 8 へ進む。

### Step 7: 最終報告

**review-only モード時の差分**: auto-fix / commit / 対応履歴の話ではなく、
レビュー結果サマリを報告する:

- PR の URL と author
- レビュー方式 (3-agent 並列、ITER_MAX=1)
- 主マーク別の finding 件数 (Question 振替分は元主マーク側からは **控除済み**):
  - `Must-fix M (Question 振替: K 件、M には未計上)`
  - `Should-fix S`
  - `Nice-to-have N`
  - `Question Q` (= 元 [Must-fix] からの Question 振替 K + 付加マーク `[Tradeoff]`
    振替分 T。`Q = K + T`)
  - **二重カウント方針**: Question 振替された finding は **元の主マーク側
    の件数からは控除し、Question 件数のみに計上** する (Step 6.5.1 の inline /
    body 振分と整合)。`Must-fix M` の `M` は Must-fix として投稿された
    (inline または body) 件数のみ、`(Question 振替: K 件、M には未計上)` は
    内訳開示のため別途記載 (= M に **含まれない** ことを明示)
- inline / body の内訳 (inline コメント I 件 / body 集約 B 件)
- silent-reject 件数 + 内訳
- 6.5 の投稿結果 (inline 投稿済み / body-only 縮退投稿済み / 編集後投稿済み /
  投稿せず終了 / 投稿失敗)
- base 比 BEHIND コミット数 (あれば)

以下は fix モード:

以下をまとめて報告:

- PR の URL
- セルフレビュー巡数 (1-5)
- 各巡の auto-fix 件数推移 (例: `6 → 4 → 1 → 0`)
- 5 巡到達ケースは「後半巡が Nice-to-have のみ = 収束」/「Must-fix/Should-fix が出続けた = 警戒」のどちらかを明記
- ブラウザテストの実施状況と最終結果
- escalate された指摘 (あれば内容と該当指摘箇所、`ESCALATE_REASON` 値)
- silent-reject の件数と内訳 (主な理由)
- 残コミット履歴の概要

### Step 8: クリーンアップ

**いかなる break 経路 (自然終了 / 5 巡到達 / base-conflict / review-finding /
browser-regression escalate / review-only 投稿完了) でも、Step 7 完了後に
必ず本 Step を実行する**。スキップすると `OWNED_BODY_FILE=True` 経路で
`docs/temp/pr-body.md` が、review-only 経路で `docs/temp/pr${N}-review.json`
が残置される。

```bash
# fix モード: 本 skill 所有の PR 本文ファイルを削除
if [ "$OWNED_BODY_FILE" = "True" ]:
    # $OWN_MARK_FILE は Step 0.3 で "docs/temp/.pr-body.owner" として定義済み。
    # sidecar パスを将来変えるときに 1 箇所だけ書き換えれば済むよう変数参照
    rm -f docs/temp/pr-body.md "$OWN_MARK_FILE"
    # -f で冪等性確保 (rebase 失敗時の途中状態などで既に消えていても
    # error にしない)。sidecar (.pr-body.owner) も同時に消すことで
    # 次回起動時の所有権判定が確実に「経路 B」になる

# review-only モード: review payload JSON を削除
# ただしユーザーが 6.5.2 で「投稿せず終了」を選んだ場合は残置する
# (ユーザーが手で投稿 or 編集したいケース)
if [ "$MODE" = "review-only" ] && [ "$POSTED_TO_GITHUB" = "True" ]:
    rm -f "docs/temp/pr${N}-review.json"
    # 注: fallback 成功 (body-only) 時は 6.5.3 が既に $tmp_body を rm 済み。
    # inline・body-only の両方が失敗 (POSTED_TO_GITHUB=False) した場合は
    # pr${N}-review.json と pr${N}-review-bodyonly.json の 2 ファイルが
    # 意図的に残置され、ユーザーが手で投稿 / 編集 / 破棄する。
```

`docs/temp/` に他のファイルがある場合があるため、**ディレクトリごと
削除しない**。呼び出し元 (create-pr) が用意したファイルは呼び出し元側
で削除されるため、本 skill は所有権を持つときだけ rm する。

#### 孤児 worktree の防御的 sweep

Step 2 で `isolation: "worktree"` で spawn した Reviewer A/B/Fact-checker の
worktree (`.claude/worktrees/agent-*`) は、subagent が**正常終了すれば
harness が unlock + remove する**。この worktree の lock を保持しているのは
**subagent 自身ではなく親 harness プロセスの pid** であり、同一セッション内では
親が生きている限り孤児は基本的に発生しない (harness が自動回収するため)。

孤児が残るのは **harness ごと異常終了した過去のセッション** のケースである。
親 harness が落ちると lock (= 既に死亡した過去 harness の pid) が残り、worktree
が `.claude/worktrees/` に残置される (`git worktree prune` は **lock 付きの実在
worktree を対象外とする**ため掃除できない)。累積するとリポ丸ごとの複製がディスク
を食い、コード解析ツール (serena 等) の index 対象に入れば **メモリ肥大・OOM** を
招く。

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

- push は必ず `gh` 経由 (SSH 鍵なし)。`gh auth setup-git` を先に走らせる
- `docs/temp/` は `.gitignore` 対象外なので Step 8 で必ず掃除 (所有権ある場合)
- rebase 後の push は `--force-with-lease` (`--force` は禁止)
- セルフレビューループ中の commit message は短くて良い
  (`chore: <N> 巡目レビュー指摘反映` 等)、プロジェクトの commit 規約
  (日本語 / 英語) に合わせる。squash は後で人がやる
- **指摘 0 件で自然終了 = 基本ゴール / 5 巡到達 = 警戒シグナル または収束**
  (上の概要を参照)。Step 7 の報告では 5 巡到達ケースの「巡ごとの auto-fix
  件数推移」と「収束 / 警戒の判定」を明記すること

### review-only モード固有の注意

- **Reviews API による inline review 投稿は不可逆**: collaborator に通知が飛ぶ
  ため、Step 6.5.2 のユーザー承認を必ず取る。承認なしに投稿してはならない
- **collaborator のブランチ / PR 本文に一切書き込まない**: Step 4 / 4.5 /
  Step 1 の rebase は完全 skip。`gh pr edit` も呼ばない
- **MODE 自動判定の通知**: フラグなしで `/review-pr <N>` 起動時、
  collaborator PR と判定して review-only に自動切替する場合は、Step 0.2.5
  の `echo` で明示的に通知する (ユーザーが意図と違う MODE に切り替わった
  ことに気付けるよう)
- **MODE 自動判定の override**: 自分の collaborator (write access あり) の
  PR で「許可を得て auto-fix したい」ケースは `--fix` フラグで明示 override
- **subagent 制約はそのまま**: review-only でも Reviewer A/B + Fact-checker
  は `isolation: "worktree"` で spawn し、prompt で作業ツリー変更を禁止する
  (重要原則 4)。read-only レビューだからといって isolation を緩めない
- awaiting 宣言 (`AskUserQuestion` 経由の PermissionRequest) は本 skill
  には **含めない**。create-pr など呼び出し元の責務として残す。単独起動
  時はユーザーがそのまま手元で次操作する想定で awaiting 化不要
- frontmatter `allowed-tools` の `mcp__playwright__*` は **Step 5 の
  ブラウザテスト再走査用**。実起動の条件は `BROWSER_TEST_DONE == True`
  (= PR 本文に `## 動作確認スクリーンショット` セクションあり) かつ
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
- `review-pr` 自身を **Skill ツール経由で呼ぶ** ことは可能 (create-pr Step 6
  の委譲経路) で、その場合 `review-pr` 本体は親と同一コンテキストで走る。
  これがバイアスを生まないのは、本 skill が「コードを書いた本人がレビュー
  する」ことを禁じているのは **Reviewer A/B/Fact-checker subagent の独立性**
  のためで、orchestration 層 (= `review-pr` 本体) の独立性ではないため。
  実際のレビューは Step 2 で必ず Agent ツール経由 (`isolation: "worktree"`)
  で 3 subagent を spawn することで担保される
