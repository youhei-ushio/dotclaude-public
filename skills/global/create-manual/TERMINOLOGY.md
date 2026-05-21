# 用語ガイドライン

現場向けマニュアルで **使ってはいけない物理名・開発用語** と、**業務語への置換例**。

> このファイルの **NG 例 / 置換例 / 拠点名・権限名** は説明のための plausible
> な例にすぎない。実プロジェクトに導入するときは、自プロジェクトの実テーブル
> 名・コンポーネント名・拠点名に書き換えて使う。「業務語として通用する用語」
> セクションも同様にカスタマイズ前提。

## NG ワード (絶対に書かない)

### DB スキーマ由来

- テーブル名: `Order`, `OrderItem`, `Product`, `Shipment`, `Warehouse` 等
  （**自プロジェクトの実テーブル名** に置き換えて運用）
- カラム名: `received_quantity`, `box_count`, `is_admin`, `status` の enum 値
  (`pending`, `received` 等) 等
- 内部 ID: `WarehouseId=42`, `ProductId`, `OrderItemId` 等

### コード由来

- 関数名・クラス名: `Log::warning(...)`, `OrderAllocator`, `BoxSplitter` 等
- パス: `storage/logs/<app>.log`, `app/<DomainLayer>/...`,
  `database/migrations/...`
- 環境変数・設定: `APP_PORT`, `DB_DATABASE` 等

### UI コンポーネントクラス名 (本プロジェクト固有)

現場マニュアルには **UI コンポーネントクラスの名前** を一切書かない。
代表例（**自プロジェクトのコンポーネント名に読み替え**）:

- `OrderForm`, `OrderModal`, `OrderSheet`, `OrderLabel`
- `Fill`, `Pick`, `Pack`, `Ship`, `BoxLabel`, `IntakeForm`

これらは grep で機械的に拾うのが難しいので、**マニュアル執筆後に
プロジェクトの実装クラス一覧を抽出して照合する** (後述 grep 例)。

## アンチパターン: 「業務語（英名）」の括弧併記

業務語の直後に括弧でクラス名・コンポーネント名を併記してはならない。

❌ NG: 「出荷梱包（Fill）画面」「注文モーダル（OrderModal）」「梱包ラベル（BoxLabel）」
✅ OK: 「出荷梱包画面」「注文モーダル」「梱包ラベル」

理由: 現場マニュアルは業務語のみで完結すべきで、英名併記は開発者向け
文書のスタイル。執筆中に「親切に英名も書こう」と思った瞬間が一番
危ない。物理名は業務語に **完全に置き換える** ことを徹底する。

### Issue / PR / ADR

- `Issue #NNNN`, `ADR #NNNN`, `本 PR では`, `(要件N)`, `Closes #XXXX`
- 「本マニュアルの対応 Issue」「関連 ADR」末尾セクションは現場向けでは削除

### 開発フェーズ語

- 「実装側で」「サーバー側で」「HTML 側で抑止」「フロントエンド」「バックエンド」
- フレームワーク名・「マイグレーション」「テストケース」
- 「`storage/logs/...` を grep」のようなログ調査手順

## 推奨置換例

実プロジェクトに合わせて拡張する前提のサンプル表。

| 物理名・開発語 | 業務語 |
|---|---|
| `Order` | 受注 |
| `OrderItem` | 受注明細 / 受注品 |
| `Receipt` | 荷受 |
| `PurchaseOrder` | 発注 |
| `TransferOrder` | 移送指示 |
| `TransferOrderLine` | 移送指示の 1 行 / 1 つの箱 |
| `PickedStock` | 出荷準備品 |
| `TrackingCode` の ID | QR コードの識別番号 / スキャンする箱の識別コード |
| `received_quantity` | 受領数量 (画面/帳票上の表示名と合わせる) |
| `box_number` / `box_count` | 箱番号 / 総箱数 |
| `is_admin = 1` | 管理者権限が必要 |
| `WarehouseId=42` | 移動中在庫 (実際の倉庫の業務名で記述) |
| `Log::warning(...)` | (画面文言があればそれを引用) / システムに自動で記録 |
| `storage/logs/<app>.log` を grep | システム担当に依頼 |
| `status = 'received'` | 受領済み |
| (要件N) | (削除) |
| 本 PR では未サポート | 用意していません / システム担当に依頼してください |
| `N 箱` (技術的表現) | 正しい箱数 / 必要な箱数 |
| `箱数 = 1 のとき` | 箱数を 1 にした場合 |

## 業務語として通用する用語 (使用 OK)

> ここはドメインによって変わる。物流・在庫系の例として残してあるので、自分の
> ドメインに合わせて入れ替える。

- 受注 / 発注 / 荷受 / 検査 / 不良 / 出荷 / 入庫 / 出庫 / 移送 / 移送指示
- 箱 / ラベル / 数量 / 残量 / プリンター / 倉庫 / 担当者
- 「管理者権限」「アクセス権限」
- システム担当 / 在庫調整 / 検査工程
- QR / バーコード (機能名は OK)

## チェック方法 (grep)

骨格作成後、以下を **すべて実行して何もヒットしないこと** を確認する。
NG パターン部分は自プロジェクトのテーブル名・カラム名に書き換えて使う。

### 1. 固定 NG ワード (DB スキーマ / コード由来 / Issue 参照)

```bash
grep -nE "Order|OrderItem|Product|Shipment|received_quantity|box_number|box_count|Log::warning|is_admin|WarehouseId|本 PR|本PR|\(要件[0-9]\)|Issue #|ADR #|Closes #|マイグレーション|テストケース" docs/business/manuals/<file>.md
```

### 2. 「業務語（英名）」の括弧併記アンチパターン

クラス名やコンポーネント名が業務語の直後に括弧で併記されていないかを検出
する。日本語直後に半角括弧で英大文字始まりの単語があるパターンを拾う:

```bash
grep -nE "[ぁ-んァ-ヶ一-龯]+（[A-Z][A-Za-z]+）" docs/business/manuals/<file>.md
```

このパターンに **ヒット 0 件であること**。ヒットしたら括弧と中身を削除し
業務語のみに直す（例:「出荷梱包（Fill）画面」→「出荷梱包画面」）。

### 3. 実装の UI コンポーネント / Model クラス名 (プロジェクト固有・動的抽出)

プロジェクトに存在する UI コンポーネントやドメインモデルの名前が
マニュアル本文に登場していないか機械的にチェック。下の例は Laravel +
Livewire 用なので、**自分のフレームワークのコンポーネント基底クラス**
（React なら `extends React.Component` / Vue なら `defineComponent` /
Rails なら `< ApplicationRecord` 等）に置き換える:

```bash
# 例: Laravel + Livewire のコンポーネント / Model 名を全列挙
PROJECT_CLASSES=$(grep -rEl "extends (Component|Model)" app/Contexts app/Models 2>/dev/null \
  | xargs -I {} basename {} .php \
  | grep -E "^[A-Z][A-Za-z]+$" \
  | sort -u \
  | paste -sd'|')
if [ -n "$PROJECT_CLASSES" ]; then
  grep -nwE "($PROJECT_CLASSES)" docs/business/manuals/<file>.md
fi
```

ヒット 0 件であること。ヒットした場合はそのクラスを業務語に置換する
(対応表が無ければ「推奨置換例」セクションに追記してから直す)。

### 4. ファイル名・パスの混入

```bash
grep -nE "\.(blade\.php|php|tsx?|jsx?|vue|rb)\b|app/|database/migrations/|resources/views/" docs/business/manuals/<file>.md
```

ヒット 0 件であること。拡張子・ディレクトリ名は自プロジェクトの構造に合わせて
調整する。

## 例外: 画面文言の引用

実画面に表示される文字列を **例として引用** する場合は、画面と一致させる必要があるため
そのまま記載する。

例: 受領画面の警告メッセージ
```
| 画面表示 | `⚠️ 数量乖離: 送り側 50 に対し受領数量は 48（差分 2）。受領後に警告ログに記録されます。` |
```

ここで「警告ログ」が出てくるのは画面文言と一致させるためなので OK。
ただし **画面外の説明文では「システムに自動で記録」と書く** こと。
