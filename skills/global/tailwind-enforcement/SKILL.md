---
name: tailwind-enforcement
description: |
  HTML / テンプレート / JSX / Vue SFC / Blade / Livewire コンポーネント等、
  UI 要素を編集するとき。style 属性を書こうとしているとき。スタイル指定のたびに参照。
---

# Tailwind CSS 必須ルール

HTML 要素のスタイル指定は必ず Tailwind CSS の class 属性を使う。
style 属性によるインラインスタイルは禁止。

## 例

NG:
```html
<div style="background-color: #3b82f6; padding: 16px; color: white;">
```

OK:
```html
<div class="bg-blue-500 p-4 text-white">
```

## 例外（style 属性が許可される場合）

### 動的な色表示

DB から取得した色値を直接表示する場合のみ:

```html
<div style="background-color: {{ $category['color_code'] }}"></div>
```

### Tailwind では表現不可能な動的スタイル

計算値や外部 API からの値をそのまま CSS に流す必要がある場合のみ。

## 適用対象

- すべての HTML / テンプレートファイル（Blade / JSX / Vue SFC / ERB 等）
- 既存コードの修正時も必ず適用

## 理由

- デザインシステムの一貫性
- メンテナンス性
- レスポンシブ対応の統一
- パフォーマンス最適化
