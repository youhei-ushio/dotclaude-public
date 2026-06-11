# スクショ撮影ガイド

マニュアル用のスクショを Playwright MCP で撮影する手順。

## 基本方針

- **現物データを優先**: ローカル DB に既存データがあれば、それを使った画面を撮影
- **一時データは最小限 + 必ず後始末**: 印刷物などで現物にない場合のみ、最小限のテストデータを作って撮影後に削除
- **デバッグ表示・Issue 番号は映さない**: URL バーに `?debug=1` 等が残らないようにする
- **本物の業務語が映る**: メニュー名・画面タイトルが実装と一致する状態で撮影

## 解像度設定

| 用途 | 幅 × 高さ |
|---|---|
| PC 画面 | 1400 × 900 |
| スマホ画面 | 428 × 926 (iPhone 14 Pro Max 相当) |
| 印刷物 (A4 縦) | 1200 × 1600 |

```javascript
mcp__playwright__browser_resize({ width: 1400, height: 900 });
```

## 撮影の標準フロー

### 1. ローカル開発サーバの確認

```bash
curl -s -o /dev/null -w "%{http_code}" <your-dev-url>/
```

302 が返れば起動中 (login へのリダイレクト)。`<your-dev-url>` は
`http://localhost:8081` 等、自プロジェクトの開発用 URL に置き換える。

### 2. ログイン

```javascript
mcp__playwright__browser_navigate({ url: '<your-dev-url>/login' });
mcp__playwright__browser_fill_form({
  fields: [
    { name: 'MailAddress', type: 'textbox', target: '<ref>', value: '<your-test-account>@example.com' },
    { name: 'Password',    type: 'textbox', target: '<ref>', value: '<your-test-password>' },
  ],
});
mcp__playwright__browser_click({ target: '<ref of Login>' });
```

テスト認証情報はプロジェクトごとに保持する（本リポには書かない）。
ローカル開発用 test ユーザーで、本番には存在しないものを使う。

### 3. テストデータの確認 / 一時データ作成

#### 既存データを探す

Laravel なら `mcp__laravel-boost__tinker`、Rails なら `rails console`、
その他のフレームワークでは ORM ごとの REPL でクエリを書いて、撮影に適した
データを探す。

例: 注文関連画面なら、未処理の `Order` で関連商品が存在するもの。

#### 一時データを作る場合 (印刷物等で必要なとき)

以下は Laravel + Eloquent の例。フレームワークに応じて読み替え:

```php
use App\Models\Order;
use App\Models\OrderItem;

$order = Order::create([
    'order_number' => 'DEMO-' . now()->timestamp,
    // ... 業務メモに「スクショ撮影用 (削除予定)」を入れる
]);
// item を作成
echo $order->id; // ← 撮影で使う ID をメモ
```

**必ず最後に削除する**:

```php
Order::where('id', $demoId)->delete();
OrderItem::where('order_id', $demoId)->delete();
```

### 4. 画面遷移と撮影

```javascript
mcp__playwright__browser_navigate({ url: '<your-dev-url>/<path>' });
mcp__playwright__browser_snapshot();  // 要素 ref を取得して入力したい場合
mcp__playwright__browser_fill_form({ fields: [...] });
mcp__playwright__browser_take_screenshot({
  filename: '/path/to/repo/docs/images/issue-XXXX/<purpose>.png',
  fullPage: true,
  type: 'png',
});
```

#### スクリーンショット保存先

```
docs/images/issue-<number>/<purpose>.png
```

ファイル名命名規則 (例):
- `<feature>-overview.png` 全体画面
- `<feature>-<action>-input.png` 入力欄の状態
- `<feature>-<state>-warning.png` 警告表示
- `<feature>-print.png` 印刷物
- `<feature>-<mobile|pc>.png` 端末別

#### Markdown での参照: スマホ縦長スクショは `class="mobile-shot"`

スマホ画面 (428×926 等) を A4 幅 100% に拡大すると 1 ページを超え、`page-break-inside: avoid` と相まって前ページに大きな空白を作る。スマホ縦長は `class="mobile-shot"` を付けて横幅 360px に絞る (pdf SKILL の manual-style.css で定義済み):

```markdown
<img src="../../images/issue-XXXX/feature-mobile.png" alt="..." class="mobile-shot"/>
```

PC / 印刷物 (横長 or A4 比率) は `![]()` のままで OK。すべての画像に max-height 620px が effective なので、A4 印刷物 1200×1600 も自然に本文と同居する。

### 5. 後始末

- 一時データを削除 (撮影用に作った Order / OrderItem 等のレコード)
- 副作用のあるテーブル（在庫など、商品マスタや残高に影響するもの）も忘れずに巻き戻す
- 削除前後で件数比較を表示してログに残す

## 撮影時のチェックリスト

撮影前:
- [ ] ログイン済み (ログイン画面が映らない)
- [ ] デバッグバーが OFF (or 開発モードと分かりにくい状態)
- [ ] URL クエリパラメータに `?debug=` 等が残っていない
- [ ] 開発専用バナー (`開発モード: ...`) が映っていない
  - 一部の開発モード経由の遷移では映ることがあるので、ログイン後のフラグを再確認

撮影後:
- [ ] PNG ファイルが保存されている (`ls -la` で確認)
- [ ] 画像を `Read` で開いて意図通りに映っているか確認
- [ ] 一時データの後始末完了
- [ ] テストデータの後始末をログ出力 (`echo "Cleanup: ..."`)

## よくある落とし穴

### スクリーンショットの相対パスが Playwright の cwd 依存

`mcp__playwright__browser_take_screenshot({ filename: '/absolute/path/...' })` で
絶対パス指定しても、Playwright のサンドボックスによっては相対パスで保存される
ことがある。撮影後に `ls` で実際の保存場所を確認する。

### 遅延バインディングの更新タイミング（例: Livewire wire:model.blur）

blur / change 契機で値を送信するフレームワーク（Livewire の `wire:model.blur`、
Vue の `v-model.lazy` 等）では、入力後すぐスクショを撮ると反映前の値が映る
ことがある。入力後に別要素をクリック (フォーカス外し) してから撮影する。

### enum 値の文字化け (testing DB 等)

DB 接続の charset が `latin1` になっている環境では、enum 定義時に日本語が
文字化けして保存され、後の INSERT で `Data truncated` エラーになる。
撮影時に再現する場合は、修復マイグレーション (SET NAMES utf8mb4 + ALTER) を別途用意する。

## 印刷物の撮影

ラベル・帳票など印刷専用ページは、グローバルヘッダー・ナビを省略した
専用レイアウト（Laravel なら `layout('layouts.print_sheet')` 相当）で
レンダリングされていることが多い。**ブラウザの幅を 1200x1600 程度にして
fullPage で撮影** すると、印刷時のイメージに近い画像が取れる。

QR コードが含まれる場合、QR は実物の解像度で出力されるため、画像サイズも余裕を持って
撮ること。
