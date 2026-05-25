---
name: pdf-read
description: PDF を全ページ PNG にレンダリングして読み取ります。図表内の文字（PowerPoint 由来の図形に埋め込まれたテキスト、表のセル内文字など）もテキスト抽出のみでは取れないため、視覚的に確認する必要があるときに使います。「PDF を読み取って」「PDF の図表を確認」「PDF 全文確認」のような自然言語で起動します。
allowed-tools: Bash, Read, Glob
---

# PDF 読み取り（全ページ PNG レンダリング + テキスト抽出）

## 概要

PDF の中身を確実に読み取るためのスキル。次の 2 段階で処理する:

1. **テキスト抽出** (`pdfplumber` / MIT) — 流し読み可能。テーブル構造も可能な範囲で抽出
2. **全ページ PNG レンダリング** (`pypdfium2` / Apache 2.0 + BSD 3-clause、`Pillow` / HPND) — 図表・SmartArt・画像内文字を視覚確認用

依存ライブラリのライセンスは商用利用に支障のないものに揃えている (PyMuPDF は AGPL のため不採用)。

テキスト抽出だけだと、PowerPoint 由来の PDF や図表内の文字を取り逃すことが多い。本スキルは PNG も並行生成して、Claude が `Read` ツールで各ページを視覚的に確認できるようにする。

## 実行コマンド

```bash
~/.claude/skills/pdf-read/render.sh <入力.pdf> [出力ディレクトリ]
```

- 出力ディレクトリ省略時は入力 PDF と同じディレクトリの `<PDF名>-pages/` を作成
- 出力: `page-1.png`, `page-2.png`, ... + `pdfplumber-text.txt`（任意のテキスト抽出結果）
- PNG は 2x スケール（解像度 約 1684x1191）で日本語の小さい文字も視覚判読可能

## 使用後の手順

1. 出力されたページ一覧をユーザーに報告
2. **必ず各 PNG を Read ツールで開いて視覚確認する**（テキスト抽出だけで判断しない）
3. 図表内の数値・カテゴリー名・矢印の対応関係などは PNG で読み取る
4. テキスト抽出結果 (`pdfplumber-text.txt`) は補助情報として参照

## 前提条件

render.sh が以下を自動 install する（未インストール時のみ）。手動セットアップ時:

```
pip install --user --break-system-packages pypdfium2 Pillow pdfplumber
```

- `pypdfium2` (Apache 2.0 / BSD 3-clause) — PDF レンダリング
- `Pillow` (HPND) — PNG 書き出し
- `pdfplumber` (MIT) — テキスト抽出（任意、失敗時はテキスト抽出のみスキップ）
- **`--break-system-packages` を使うのは PEP 668 環境（Debian/Ubuntu 系の外部管理 Python）で user-site への install を強制するため**。システム Python を汚したくない場合は、事前に venv を作って activate 済みの状態で render.sh を呼ぶこと

## 注意点

- PowerPoint からエクスポートされた PDF は **図形内文字がテキスト抽出に乗らない** ことが多い → 必ず PNG 視覚確認
- 出力 PNG は容量が大きい（1 ページ 200KB〜2MB）。確認後は不要なら削除する
- 出力 PNG は PDF と同階層の `<PDF名>-pages/` に置かれる。`.gitignore` 対象とし、コミットしないこと
- 同じ入力 PDF を再実行すると、render.py が出力ディレクトリの既存 `page-*.png` を一掃してから書き出す（ページ数減少時の取り残し防止）
