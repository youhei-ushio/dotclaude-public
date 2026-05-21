---
name: pdf
description: MarkdownファイルからPDFを生成します。SVG画像をbase64インライン化、相対パス画像、日本語マニュアル向けスタイルテンプレートに対応。「PDFを生成して」「PDF最新化して」のような自然言語で起動します。
allowed-tools: Read, Bash, Write
---

# Markdown → PDF 生成

## 概要

Markdown を PDF にする。基本生成 / SVG 埋め込み / 相対パス画像 / 日本語マニュアル体裁の 4 用途に対応。

## モード

| モード | 用途 | 必要な処理 |
|---|---|---|
| **基本** | 単一ファイル + インライン画像 | 手順 3 のみ |
| **SVG 埋め込み** | drawio 由来の `.svg` 参照あり | 手順 2 → 3 |
| **相対パス画像** | `../images/foo.png` などサブディレクトリ参照 | 手順 3 + `--basedir` |
| **日本語マニュアル** | 章立て + コールアウト + 番号バッジ表 + ページ番号フッタ | 手順 3 + `--stylesheet` |

## 手順

### 1. drawio → SVG 変換（drawioファイルが更新されている場合）

`hooks/run-drawio-export.sh` を Xvfb 経由で呼ぶラッパーとして用意してある。

```bash
~/.claude/hooks/run-drawio-export.sh <入力.drawio> <出力.svg>
```

複数ファイルを変換する場合はループで順次呼ぶ。`drawio` CLI と `Xvfb` が前提。

### 2. SVG を Base64 data URI にインライン化（SVG 参照ありの場合のみ）

`md-to-pdf` はSVGの相対パス参照を正しく解決できない場合があるため、PythonスクリプトでSVGをbase64インラインに変換する。

`/tmp/embed-svg-to-md.py` を作成して実行する:

```python
#!/usr/bin/env python3
import base64, re, sys
from pathlib import Path

def main():
    md_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    md_dir = md_path.parent
    content = md_path.read_text(encoding='utf-8')

    def replace_svg(match):
        alt, src = match.group(1), match.group(2)
        if not src.endswith('.svg'):
            return match.group(0)
        svg_path = (md_dir / src).resolve()
        if not svg_path.exists():
            return match.group(0)
        b64 = base64.b64encode(svg_path.read_bytes()).decode('ascii')
        return f'<img src="data:image/svg+xml;base64,{b64}" alt="{alt}" style="max-width:100%"/>'

    content = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_svg, content)
    output_path.write_text(content, encoding='utf-8')

if __name__ == '__main__':
    main()
```

```bash
python3 /tmp/embed-svg-to-md.py <入力.md> /tmp/pdf-source.md
```

### 3. PDF生成

#### 3-1. 基本

```bash
npx --yes md-to-pdf /tmp/pdf-source.md \
  --pdf-options '{"format": "A4", "margin": {"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"}}'
cp /tmp/pdf-source.pdf <出力先.pdf>
```

#### 3-2. 相対パス画像 (`../images/foo.png` など)

`--basedir` を **必ず指定** する。指定しないと相対パス画像が PDF に埋め込まれない（テキストのみ通る）。

```bash
cd <md があるディレクトリ> && npx --yes md-to-pdf manual.md \
  --basedir <共通ルート> \
  --pdf-options '{"format":"A4","printBackground":true,"preferCSSPageSize":true}' \
  --launch-options '{"args":["--no-sandbox","--disable-dev-shm-usage"]}'
```

#### 3-3. 日本語マニュアル体裁（CSS テンプレート利用）

このスキル同梱の `assets/manual-style.css` を `--stylesheet` で渡すと、章扉/赤ヘッダ/コールアウト/番号付き表/ページ番号フッタなどの体裁が一発で揃う。

```bash
npx --yes md-to-pdf <md> \
  --basedir <共通ルート> \
  --stylesheet ~/.claude/skills/pdf/assets/manual-style.css \
  --pdf-options '{"format":"A4","printBackground":true,"preferCSSPageSize":true}' \
  --launch-options '{"args":["--no-sandbox","--disable-dev-shm-usage"]}'
```

CSS の場所は環境により次のいずれか:
- ユーザー配置: `~/.claude/skills/pdf/assets/manual-style.css`
- システム配置: `/etc/claude-defaults/skills/pdf/assets/manual-style.css`

CSS テンプレートが提供する Markdown → 見た目のマッピング:

| Markdown | PDF 表示 |
|---|---|
| `# タイトル` | 大見出し + ブランド色アンダーライン |
| `## 第 N 章 ...` | ブランド色ヘッダ + 薄い下線 |
| `### N-N サブ節` | ブランド色の左罫線 |
| `> **ポイント**: ...` | 青コールアウトボックス |
| `> **ご注意**: ...` | 青コールアウトボックス |
| `\| 番号 \| 名称 \| 役割 \|` のような表 | ブランド色ヘッダ + 番号列強調 + 偶数行ストライプ |
| `![alt](path)` | 角丸 + 微シャドウ + 改ページ抑止 |

#### CSS カスタマイズ (CSS 変数)

ブランドカラー・フッタ表記は CSS 変数で上書きできる。Markdown ファイル冒頭に `<style>` を書くだけ。**変数は `:root` に書くこと** (`body` に書くと `@page` ルールに伝わらず、ページ番号フッタが効かない):

```html
<style>
:root {
  --brand: #0066cc;             /* ブランド色 (デフォルト #c8102e 赤) */
  --brand-tint: #cce0ff;        /* ブランド色の薄色 (h2 下線) */
  --footer-brand: "Acme Inc.";  /* 各ページ右下の小さいテキスト (デフォルト空) */
}
</style>
```

主な変数:
- `--brand`, `--brand-tint`: ブランド色 (赤系/青系/緑系などに切替可)
- `--footer-brand`: ページ右下フッタの企業/プロダクト名 (デフォルトは空)
- `--note-bg`, `--note-border`, `--note-text`, `--note-strong`: コールアウトボックスの色
- `--ink`, `--ink-muted`, `--ink-faint`: 本文/説明文/フッタ系の色

詳細は `manual-style.css` の冒頭 `:root { ... }` 参照。

> **`:root` と `body` の違い**: 通常の CSS 変数は `body` に書いてもページ内要素には伝播するが、`@page` ブロック (ページ番号やフッタ表記など印刷用ルール) は **document root** から変数を読むため、`body` 上書きでは効かない。Chromium で検証済み (2026-05)。

### 4. 確認

- `Read` ツールでPDFを開き、画像が正しく表示されていることを確認する
- 日本語が中国語フォント (WenQuanYi Zen Hei) で出ていないか目視（後述「日本語フォントの落とし穴」）

## 注意事項

### 日本語フォントの落とし穴 (Linux でビルドする場合)

CSS で `Hiragino Kaku Gothic ProN`, `Yu Gothic`, `Meiryo`, `Noto Sans CJK JP` を指定しても、Linux サーバー (Docker など) に **これらのフォントは入っていない**。Chromium のデフォルト fallback は中国語の **WenQuanYi Zen Hei** で、日本語特有のグリフが化ける可能性がある。

**回避策**: CSS の `font-family` 末尾に **`IPAPGothic`, `IPAGothic`** を入れる（情報処理推進機構フォント、`fonts-ipafont-gothic` パッケージで導入される）。

```css
font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo",
             "Noto Sans CJK JP", "IPAPGothic", "IPAGothic", sans-serif;
```

このスキル同梱の `assets/manual-style.css` には既に IPAPGothic フォールバックが入っている。

**確認方法**:

```bash
python3 -c "
from pypdf import PdfReader
r = PdfReader('<出力.pdf>')
fonts = set()
for p in r.pages:
    if '/Resources' in p and '/Font' in p['/Resources']:
        for fr in p['/Resources']['/Font'].values():
            f = fr.get_object() if hasattr(fr,'get_object') else fr
            fonts.add(str(f.get('/BaseFont')))
print(fonts)"
```

期待値: `IPAPGothic` または Hiragino/Yu Gothic 等が含まれている。`WenQuanYi` のみだった場合は CSS 修正が必要。

### その他

- `sed` でのbase64置換はSVGが大きいと `Argument list too long` エラーになる → Pythonスクリプト必須
- `--basedir` を忘れると相対パス画像が黙って欠落する。生成後の画像確認必須
- 章ごとに強制改ページしたい場合は CSS に `h2 { page-break-before: always; }` を追加。ただしページ数が増える（各章末尾に空白）ので、密度優先なら入れない
- PDF生成後は必ず確認してからコミットする

ARGUMENTS: $ARGUMENTS
