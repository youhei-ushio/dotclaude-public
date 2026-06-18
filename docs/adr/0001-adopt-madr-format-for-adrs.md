# ADR を MADR 形式で記録する

## ステータス

Accepted — 2026-06-18

## 背景と課題

設計上の意思決定をどの様式で残すかが定まっておらず、記録の有無・粒度・フォーマットがばらつく。documentation-standards スキルで ADR の標準フォーマットを定め、プロジェクト横断で一貫した意思決定記録を残せるようにしたい。どの ADR 様式を採用するか。

## 意思決定の要因

- Markdown だけで完結し、専用ツールやサービスに依存しないこと
- 広く使われ、参考例・エコシステムが豊富で学習コストが低いこと
- 「検討した選択肢」「決定」「結果（Consequences）」を構造的に書け、レビューしやすいこと
- 連番 + kebab-case 命名で採番・相互参照（Supersede 等）を機械的に追えること

## 検討した選択肢

- MADR（Markdown Any Decision Records）形式
- Michael Nygard 式のオリジナル ADR（Context / Decision / Consequences の 3 節）
- プロジェクト独自フォーマット

## 決定内容

選択した選択肢: **MADR 形式**。documentation-standards スキルに MADR 準拠のテンプレート（配置先・ステータス値・テンプレート・作成手順）を統合し、本 ADR 自身をその最初の適用例（ドッグフード）とする。日本語ラベル等の adaptation は加えるが、構造は本家 MADR（Considered Options → Decision Outcome → Pros and Cons of the Options）に合わせる。

### 結果（Consequences）

- 良い結果: Markdown 完結・ツール非依存で、本リポの symlink 配布運用と相性が良い。選択肢の列挙と評価が構造化され、判断の追跡性が高く、既存の MADR エコシステムに沿うため学習コストも低い
- 悪い結果: Nygard 式より節が多く、軽微な決定には記述コストが相対的に高い。日本語ラベル等の adaptation により本家 MADR と完全一致ではない（差分は意図的）

## 選択肢の評価（Pros and Cons）

### MADR（Markdown Any Decision Records）形式

選択肢の列挙・決定・結果を節で構造化する Markdown ベースの ADR 様式。

#### メリット

- 構造が明確でレビュー・差分比較がしやすい
- Supersede / Extends などの関係を記述する慣行がある

#### デメリット

- 節数が多く、ごく小さな決定にはオーバーヘッドになる

### Michael Nygard 式のオリジナル ADR

Context / Decision / Consequences の 3 節からなる最小様式。

#### メリット

- 最小限で記述コストが低い

#### デメリット

- 選択肢の比較を書く場所が定型化されておらず、判断根拠が薄くなりやすい

### プロジェクト独自フォーマット

自前で様式を定義する。

#### メリット

- 自プロジェクトの事情に最適化できる

#### デメリット

- 標準がなく様式が揺れる。学習・保守コストが高い

## 関連リンク

- Related: [MADR (adr/madr)](https://github.com/adr/madr)
- Related: [documentation-standards スキルの「ADR」セクション](../../skills/global/documentation-standards/SKILL.md)
