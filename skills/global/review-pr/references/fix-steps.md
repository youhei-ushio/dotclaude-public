# fix モード専用ステップ

本ファイルは `review-pr` skill の fix モード専用ステップ (1.5, 4, 4.5, 5) の詳細手順。
SKILL.md のループ枠から参照される。**review-only モードでは本ファイルを読む必要はない**。

---

## Step 1.5: docs-drift / test-gap 事前検出 (fix モードのみ、初巡のみ)

**review-only モード時は skip**。fix モードかつ `iteration == 1` のときのみ実施。
レビューループに入る前に、ドキュメントの乖離とテストのギャップを検出して先に
修正する。レビュー中に「テスト不足」「ドキュメント未更新」が指摘されて巡数を
消費するのを防ぐ。

```text
# docs-drift: diff に含まれるソースファイルに対応するドキュメント (README,
# ADR, API ドキュメント等) が同じ diff に含まれているか確認
git diff "origin/$BASE"...HEAD --name-only | 対応ドキュメントの有無を検査

# test-gap: diff に含まれるソースファイルに対応するテストファイルが
# 同じ diff に含まれているか確認
git diff "origin/$BASE"...HEAD --name-only | 対応テストの有無を検査
```

検出した乖離・ギャップがあれば:
1. 不足しているドキュメント更新・テスト追加を実装
2. commit (push はしない。最終 push は create-pr 側で行う)
3. Step 2 のレビューに進む

検出結果が空（乖離もギャップも無い）ならそのまま Step 2 へ。

**スコープガード**: diff にアプリケーションソースコード（`.php` / `.js` / `.ts` /
`.vue` 等）が含まれない場合（skill ファイル・設定ファイル・ドキュメントのみの
変更）、docs-drift / test-gap 検出は対象外であり、何も報告せず Step 2 へ進む。
また、振る舞い変更を伴わないリファクタリング（内部構造変更・フォーマット修正）
の場合はテストギャップと判定しない。

---

## Step 4: 修正実行

**review-only モード時は本 Step 全体を skip して Step 6 へ進む**
(Step 3 で `report` のみ確定済み、修正は行わない)。

**Step 4 先頭 (early-break 判定)** — fix モード:

```text
FIXED_KEYS_THIS_ROUND = set()   # 本巡分を毎巡リセット

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
git commit -m "chore: <iteration> 巡目レビュー指摘反映"
```

**fix-stable 収束キーの記録**: auto-fix した全指摘の `convergence_key` を
kind 名前空間付き (`"defect:" + key` / `"judgment:" + key`) で
`FIXED_KEYS_THIS_ROUND` に集める。**`RESOLVED_KEYS` にはここでは足さない**
(Step 6 の収束判定が「前巡までの分」と比較するため。判定後に Step 6 が足す)。
次巡の Step 2.1 では `RESOLVED_KEYS` がレビュアープロンプトに除外指示として渡される。

---

## Step 4.5: PR 本文「対応履歴」の更新 (毎巡必須)

**review-only モード時は本 Step 全体を skip**: collaborator の PR 本文を
書き換えないため。Step 6.6 で GitHub に投稿する review コメントには履歴
セクションを含めない (1 回切りの投稿で対応履歴の概念がない)。

以下は fix モード:

次巡のレビュアーが古い情報で評価しないように、commit と合わせて PR 本文も
更新する。**escalate 直行経路 (本巡 commit 無し) でも本 Step を必ず通す**
ことで、escalate 理由を PR 本文に残しレビュー経路を可視化する。
`$REPO_ROOT/docs/temp/pr-body.md` は Step 0.3 ですでに用意済み (経路 A:
呼び出し元が用意 / 経路 B: 本 skill が現本文から生成)、両経路で以降の
処理は共通:

`$REPO_ROOT/docs/temp/pr-body.md` を編集:

- 既存の Summary / 設計判断 / 維持されたノウハウは保持
- 「対応履歴」セクションの位置は `## Test plan` の直前 (`## ブラウザテスト` が
  ある場合はその後ろ)。create-pr Step 3 のテンプレートには書かず、初回はここで挿入する
- 「対応履歴」セクションを追加または更新し、今巡の auto-fix /
  escalate / silent-reject の件数と主な内訳を 3-5 行で要約
- 本巡 commit がある場合: `### N 巡目`
- escalate 直行経路で commit 無しの場合: `### N 巡目 (escalate 中断
  / 理由: $ESCALATE_REASON)`
- Test plan のチェック状態も最新化 (完了項目は `[x]`)

### 「対応履歴」セクションテンプレート

```markdown
## 対応履歴

### 1 巡目
- depth: <lightweight|full|legacy> / ロール: <Correctness+Security|+Impact|A/B+FC>
- 分類: auto-fix <件数> / silent-reject <件数> / escalate <件数>
- 主な auto-fix: <短い箇条書き 2-3 件>
- silent-reject 内訳: <件数> 件 (主な理由: 事実誤認 N 件 / 主観 1 票 N 件)
- escalate (あれば): <内容>
- 収束キー解消: <件数> 件 (FIXED_KEYS_THIS_ROUND。Step 6 で RESOLVED_KEYS に反映)

### 2 巡目
...

### N 巡目 (escalate 中断 / 理由: base-conflict)
- escalate 理由: base 同期で意味的コンフリクト検出 (詳細: ...)
- ユーザー判断待ち。Step 7 で詳細報告
```

ファイル削除は **しない** (経路 A の呼び出し元 = create-pr が Step 9 で
削除する。経路 B は本 skill の Step 8 で削除する)。

### 所有権ライフサイクル (両 skill 共通の要約)

`docs/temp/pr-body.md` + sidecar `docs/temp/.pr-body.owner` の所有権:

- **経路 A (create-pr → review-pr)**: create-pr Step 3 が **作成** →
  review-pr が **編集** (毎巡 Step 4.5 で対応履歴追記) →
  create-pr Step 9 が **削除** (両ファイル)
- **経路 B (review-pr 単独 ad-hoc)**: review-pr Step 0.3 が **作成**
  (gh pr view から生成) → review-pr 自身が **編集** (毎巡 Step 4.5) →
  review-pr Step 8 が **削除** (両ファイル)

---

## Step 5: ブラウザテストの再走査 (UI 影響のある修正のときのみ)

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

UI 影響あり判定 (いずれか満たせば再走査):

- **(a) パス判定**: ブラウザテスト対象の拡張子/ディレクトリパターンに該当
  (`.blade.php`, `.vue`, `.tsx`, `.jsx`, `resources/views/**`,
  `resources/js/**`, `app/(Http/)?Livewire/**` 等)
- **(b) スタイル系**: `*.css`, `*.scss`, `tailwind.config.*` に変更あり
- **(c) ルーティング系**: `routes/web.php`, `routes/api.php` に変更あり
- **(d) クラス変更**: コンポーネント class 属性 / Tailwind utility class の追加削除を
  機械判定 (`git diff HEAD~1 HEAD -- '*.blade.php' '*.vue' '*.tsx' '*.jsx' 'resources/views/**' 'resources/js/**' | grep -E '^[+-].*(class=| class:)'`)

```text
if BROWSER_TEST_DONE  # Step 0.4 で判定: PR 本文に「ブラウザテスト」
                      # セクションがあれば True (経路 A/B 共通)
    AND (a または b または c または d):
    全ケースを再走査
    失敗したら ESCALATE_REASON = "browser-regression" を立てて Step 7 へ進む
```

以下は完全 skip (= 正常な終了パス、escalate しない):

- `BROWSER_TEST_DONE == False` (画面変更なし判定で初回もブラウザテスト
  未実施だった PR、経路 A/B 共通)
- 今巡の auto-fix が typo / import 整理など UI に無関係なもののみ
