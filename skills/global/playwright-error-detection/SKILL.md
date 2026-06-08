---
name: playwright-error-detection
description: |
  Playwright MCP でブラウザ検証する直後に、画面エラーを必ず検出する。
  実装テストでブラウザにアクセスした後の必須手順。
  フレームワーク固有のエラー UI（PHP デバッグバー等）の詳細展開時にも参照。
---

# Playwright によるブラウザエラー検出

実装テストで Playwright MCP でページをロードしたら、必ずエラー検出を実行する。

## エラー検出関数

`mcp__playwright__browser_evaluate` で以下の関数を実行:

```javascript
() => {
  const errorSelectors = [
    '.alert-danger',
    '.text-red-500',
    '.text-red-600',
    '.error-message',
    '[class*="error"]',
    '[class*="danger"]',
    '.bg-red-50',
    '.bg-red-100'
  ];
  let errors = [];
  errorSelectors.forEach(selector => {
    document.querySelectorAll(selector).forEach(el => {
      if (el.textContent.trim()) {
        errors.push({ selector, text: el.textContent.trim() });
      }
    });
  });
  return errors.length > 0 ? errors : null;
}
```

## エラーが見つかった場合の対処

1. **STOP**: 他の作業を中断、エラー修正を最優先
2. **FIX**: エラー内容を分析、根本原因を修正
3. **RETEST**: 修正後に再度エラー検出を実行

## エラーが無い場合の追加確認

`mcp__playwright__browser_console_messages` でコンソールエラーも確認。

## フレームワーク固有のエラー UI 展開（例: PHP デバッグバー）

スタックによっては画面内にエラー表示ウィジェットを持つ（Laravel の PHP
デバッグバー、Symfony の Web Profiler、Rails の better_errors 等）。省略
されたエラーメッセージは要素クリックで展開する。以下は PHP デバッグバーの例
（セレクタは各ウィジェットに読み替え）:

```javascript
() => {
  const el = document.querySelector('.phpdebugbar-widgets-error');
  if (el) {
    el.click();
    return el.textContent;
  }
  return 'no error element';
}
```

## Playwright MCP 使用時の禁則

- いかなる形式のコード実行も禁止（Python・JavaScript・Bash 等でのブラウザ操作）
- subprocess やコマンド実行によるアプローチ不可
- 利用可能なのは MCP ツールの直接呼び出しのみ
- エラー時は即座に報告（回避策を探さない、代替手段を実行しない）
