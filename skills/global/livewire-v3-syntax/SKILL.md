---
name: livewire-v3-syntax
description: |
  Livewire コンポーネントを書く・編集するときに必ず確認する。
  特に <livewire:...> タグ、@livewire ディレクティブ、wire:key / :key 属性のいずれかを書こうとしているとき。
  Livewire v2 と v3 で構文が大きく異なるため。
---

# Livewire v3 構文ルール

Livewire 3.x を使うプロジェクトで、v2 系の書き方が混入するのを防ぐ。
本 skill を有効にした状態では v2 構文は禁止。

## タグ記法

正解 (v3):
```blade
<livewire:component-name :key="$key" />
<livewire:component-name :prop="$value" />
<livewire:component-name :prop="$value" :key="$id" />
```

NG (v2 系):
```blade
@livewire('component-name')
<livewire:component-name wire:key="key" />
```

## キー属性

繰り返し描画時のキーは `:key` を使う。`wire:key` は v2 構文。

## 不確実な場合

claude.ai Context7 MCP で最新仕様を確認する:
1. `mcp__claude_ai_Context7__resolve-library-id` で Livewire の ID を取得
2. `mcp__claude_ai_Context7__query-docs` で最新仕様を確認
3. それに従って実装
