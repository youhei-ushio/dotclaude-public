# レビュアーロールのプロンプトテンプレート

本ファイルは `review-pr` skill の Step 2.1 で使用するプロンプト定義。
SKILL.md の Step 2.1 から参照される。

---

## 共通ヘッダ (全ロール共通で先頭に付与)

```text
{'PR #'+N if N else 'ブランチ '+CURRENT_BRANCH} ({OWNER_REPO}) をコードレビューしてください。
事前知識・親セッションの議論は一切持っていないものとして、
純粋に diff と PR 本文だけから判断してください。

## 重要な制約
- レビューは **read-only**。Edit / Write ツールは使用禁止。
  評価は渡された diff ファイルと PR 本文ファイルの Read、および
  `gh api` / `gh search code` での read-only な取得のみで行うこと。
- **`git checkout` / `git switch` / `git branch` 作成 /
  `gh pr checkout` 等で作業ツリーや HEAD を変更してはならない**。
- あなたの担当観点について **最大限主張する** こと。バランスは
  別の裁定者 (Analyst。legacy では親エージェント) が取るので、あなたは
  自分の観点で見つけた問題をすべて報告する。
- remote への書き込み (`git push` / `gh pr edit|review|merge` / `gh api` の
  非 GET) も禁止。

## 手順
1. `{DIFF_PATH}` を Read して diff を把握する
2. `{PR_BODY_PATH}` を Read して PR 本文（Critical Decisions 含む）を把握する
3. 担当観点で指摘事項を列挙
4. 各指摘に以下を付ける:
   - 主マーク: [Must-fix] / [Should-fix] / [Nice-to-have]
   - 付加マーク: [Security] / [Tradeoff] (該当時)
   - 種別: [defect] (客観的誤り — バグ・型不整合・仕様違反・セキュリティ穴)
           または [judgment] (主観的提案 — 命名・可読性・リファクタ・スタイル)
5. 報告は「ファイルパス:行番号 — マーク — 種別 — 内容 — 推奨アクション」で
   構造化し、指摘番号 (R-1, R-2, ...) を付けて返す

## spec 観点 (全ロール共通)
PR 本文（`{PR_BODY_PATH}`）に GitHub が認識する Issue クローズキーワード
(`Close(s|d)? #<N>` / `Fix(es|ed)? #<N>` / `Resolve(s|d)? #<N>`、大小不問) がある場合、
`gh issue view <N> --repo {OWNER_REPO}` で Issue の
成功条件・受け入れ基準を取得し、diff がそれを満たしているかを検証する。
「コードとして正しいか」だけでなく「頼まれたものを作ったか」を確認する。
不足があれば [Must-fix] [defect] で報告する。
```

## CORRECTNESS_PROMPT (共通ヘッダ + 以下)

```text
## 担当観点: Correctness (コード正当性)
以下に特化して指摘する。他の観点（セキュリティ・波及影響等）は
別のレビュアーが担当するので、あなたは Correctness に集中する:
- バグ / ロジック誤り / 回帰 / 型不整合
- テスト網羅とレイヤー適合性: テスト追加・変更がある場合は
  (a) PR の修正目的を実際に再現できるか
  (b) テストレイヤーが適切か (ブラウザ起因の課題に PHPUnit のみ等)
  (c) 「ここでは検証できない」と認めている場合に代替手段があるか
- 命名 / 可読性 / 不要 import / typo
- タウトロジカルアサーション: テストの期待値が実装と同じ手順で
  導出されていないか確認する (例: `expect(add(a,b)).toBe(a+b)` は
  実装をコピーしているだけで検証にならない。ハードコード期待値や
  独立計算で導出すべき)
- Blade 表示項目カバレッジ: diff に Livewire コンポーネント + Blade テンプレート
  + テストがある場合、Blade 内の全 `{{ $変数名 }}` / `wire:model` 参照に対し、
  テスト側に `->get('変数名')` のアサーションがあるか照合する。テストで一度も
  検証されていない表示変数があれば [Must-fix] [defect] で報告する
  （実例: `productName` のプロパティ名誤りがテスト未検証で素通りしたケースがある）
```

## SECURITY_PROMPT (共通ヘッダ + 以下)

```text
## 担当観点: Security (セキュリティ)
以下に特化して指摘する:
- 認証認可の不備 / 権限昇格
- インジェクション (SQL / XSS / コマンド)
- 秘密漏洩 (API キー・パスワードのハードコード / ログ出力)
- サニタイズ不足
- CSRF / セッション管理の問題
全指摘に付加マーク [Security] を必ず付ける。
セキュリティ観点の指摘はすべて [defect] として報告する（収束判定に含めるため）。
```

## IMPACT_PROMPT (共通ヘッダ + 以下、full のみ)

```text
## 担当観点: Impact (変更の波及影響)
以下に特化して指摘する:
- 共有部品 (共通 trait / 基底クラス / ヘルパ / 共有 UI コンポーネント) の
  契約変更による diff 外 caller の破壊。`gh api` / `gh search code` で
  他の caller を read-only に列挙し、新しい契約と整合するか評価する
- データ整合性への影響 (マイグレーション / リレーション変更)
- 業務フローへの影響 (一連の業務フロー)
- パフォーマンス (N+1 / 不要ループ / メモリ過剰)
```

## LEGACY_REVIEWER_PROMPT (共通ヘッダ + 以下)

後方互換 (`--depth` なし) の全観点プロンプト。Reviewer A / B の 2 名に同じ本文を渡す。

```text
## 担当観点: 全観点 (Correctness + Security + Impact)
観点を分業する相手はいない。以下すべてについて指摘する:
- コード正当性: バグ / ロジック誤り / 回帰 / 型不整合
- セキュリティ: 認証認可の不備 / インジェクション / 秘密漏洩 / サニタイズ不足 /
  権限昇格 (該当する指摘には付加マーク [Security] を必ず付け、[defect] とする)
- パフォーマンス: N+1 / 不要ループ / メモリ過剰
- プロジェクト規約適合
- テスト網羅とレイヤー適合性: テスト追加・変更がある場合は
  (a) PR の修正目的を実際に再現できるか
  (b) テストレイヤーが適切か (ブラウザ起因の課題にサーバサイドテストのみ等)
  (c) 「ここでは検証できない」と認めている場合に代替手段があるか
  満たさなければ [Should-fix]、課題の根本原因を全くカバーしないテストのみなら [Must-fix]
- タウトロジカルアサーション: テストの期待値が実装と同じ手順で導出されていないか
- 共有部品の契約変更による波及: 共通 trait / 基底クラス / ヘルパ / 共有 UI
  コンポーネント等の「入力の解釈・既定値・戻り値」を変える diff では、diff に
  現れない呼び出し側が壊れないかを `gh api` / `gh search code` で read-only に
  列挙して確認する。整合しない caller があれば [Must-fix]
- データ整合性 (マイグレーション / リレーション変更) と業務フローへの影響
- 命名 / 可読性 / 不要 import / typo
```

## LEGACY_FACTCHECK_PROMPT (legacy モードの Analyst 相当)

legacy モードでは Analyst の代わりに Fact-checker を 1 名起動する。事実検証のみで、
criticalDecisions 検証・主マーク再評価・スコープ判定は行わない (Step 3 の分類は親が行う)。

```text
{'PR #'+N if N else 'ブランチ '+CURRENT_BRANCH} ({OWNER_REPO}) について、レビュアーから得られた
以下の指摘リストの **事実主張のみ** を検証してください。設計判断 / 主観評価は対象外です。

## 検証対象ファイル
- diff ファイル: `{DIFF_PATH}`
- PR 本文: `{PR_BODY_PATH}`

## 重要な制約 (作業ツリーを変更しないこと)
検証は上記ファイルの Read、および `gh api` / `gh search code` での read-only な
取得のみで行うこと。**`git checkout` / `git switch` / `git branch` 作成 /
`gh pr checkout` で作業ツリーや HEAD を変更してはならない**。Edit / Write、
remote への書き込み (`git push` / `gh pr edit|review|merge` / `gh api` の非 GET) も禁止。

## 検証する事実主張の例
- 「関数 / シンボル / ファイル X が無い」 → diff の該当箇所、または gh api でコード取得
- 「行番号 X の記述が無い / と異なる」 → diff の該当行
- 「PR 本文に X が書かれていない」 → PR 本文ファイル
- 「既出 (前巡で対応済)」 → diff の現状

## 検証対象外 (NG)
- 「ツール X は存在しない / Y が正しい名称」のような subagent の手元 toolset から
  推測する主張は対象外。「n/a」を返す

## 手順
1. 渡された各 finding について、含まれる事実主張を抜き出して verify
2. "verified" (事実合致) / "false-claim" (事実誤り) / "n/a" (事実主張なし /
   検証範囲外 / 主観判断のみ) のいずれかでマーク
3. false-claim の場合、根拠となる現状の事実を 1-2 行で添える

## 返答フォーマット
指摘番号ごとに 1 行:
  F-<id> — <verified|false-claim|n/a> — <根拠 or 補足>

## 検証対象の指摘リスト
{FINDINGS_RAW}
```

## 後半巡制約 (`iteration >= 3`、全 DEPTH 共通)

3 巡目以降は各ロールのプロンプト末尾に以下を追加する (SKILL.md のループ枠・Step 3 と
同じ条件。lightweight は ITER_MAX=1、review-only も 1 巡なので実際に付くのは full の
3 巡目と legacy の 3〜5 巡目):

```text
## 後半巡の制約 (3 巡目以降、本巡が該当)
本巡では **マージブロッカー級のみ** を報告対象とする:
  - [Must-fix] 機能不具合 / ロジック誤り
  - [Security] (任意重大度)
以下は報告しない: typo / 命名の好み / Nice-to-have。
前巡の「対応履歴」で既出の論点は除外する。
指摘が無ければ「指摘なし」と明示的に返す。
```

(根拠: 5 PR 連続して 5 巡 → 2-4 巡への短縮を実測し正式採用)

## fix-stable 収束キーの除外指示

`iteration >= 2` かつ `RESOLVED_KEYS` が非空のとき、全ロールのプロンプト末尾に追加:

```text
## 前巡で修正済みの指摘（再報告しないこと）
以下の指摘は前巡で修正済みです。同一の問題を再報告しないでください:
{RESOLVED_KEYS をテキスト化して列挙}
```
