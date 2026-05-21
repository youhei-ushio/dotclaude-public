# dotclaude-public

[Claude Code](https://claude.com/claude-code) の user-level 資産（`~/.claude/` 配下に置く skill / hooks / settings / CLAUDE.md / statusline）の dotfiles テンプレート。

複数マシン間で `~/.claude/` を同期するために、リポを clone してシンボリックリンクを張る運用を想定しています。

## このリポで管理するもの

| 項目 | 配置先 | 役割 |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | global ルール（言語・コード discovery 方針 等） |
| `settings.json` | `~/.claude/settings.json` | env / permissions / hooks のサンプル設定 |
| `statusline.sh` | `~/.claude/statusline.sh` | 2 行構成のカスタム statusline |
| `hooks/` | `~/.claude/hooks/` | PreToolUse / PostToolUse / Notification / Stop の hook スクリプト |
| `skills/global/` | `~/.claude/skills/` | プロジェクト非依存の global skill |

## セットアップ

```bash
# clone
git clone git@github.com:<your-account>/dotclaude-public.git ~/repos/dotclaude

# 配置先ディレクトリを用意
mkdir -p ~/.claude/hooks ~/.claude/skills

# CLAUDE.md / settings.json / statusline
ln -sf ~/repos/dotclaude/CLAUDE.md       ~/.claude/CLAUDE.md
ln -sf ~/repos/dotclaude/settings.json   ~/.claude/settings.json
ln -sf ~/repos/dotclaude/statusline.sh   ~/.claude/statusline.sh

# hooks（必要なものだけ張る）
for f in ~/repos/dotclaude/hooks/*.py ~/repos/dotclaude/hooks/*.sh; do
  ln -sf "$f" ~/.claude/hooks/
done

# global skill（すべて symlink）
for d in ~/repos/dotclaude/skills/global/*/; do
  ln -sf "$d" ~/.claude/skills/
done
```

シンボリックリンク運用にしておくと、`git pull` するだけで `~/.claude/` 側にも反映される。

## hooks 一覧

| Hook | トリガー | 役割 | 環境依存 |
|---|---|---|---|
| `skill-enforcer.py` | PreToolUse / Bash | skill 対応コマンドを直接 Bash で叩いた際に block し対応 skill へ誘導 | 汎用 |
| `serena-enforcer.py` | PreToolUse / Bash | `grep` / `find` / `cat` でのコード探索を block し [serena](https://github.com/oraios/serena) MCP へ誘導 | serena MCP 利用前提 |
| `git-push-merged-pr-check.py` | PreToolUse / Bash | `git push` 時に現在ブランチが MERGED PR を持つなら block | `gh` CLI が必要 |
| `sail-env-inline-block.py` | PreToolUse / Bash | `COMPOSE_PROJECT_NAME=... ./vendor/bin/sail ...` のインライン環境変数指定を block | Laravel Sail 利用時のみ意味あり（他環境では空振り） |
| `sql-schema-check.py` | PreToolUse / Write | `.sql` ファイル書き込み時に参照テーブルが事前確認済みかバリデート | 汎用（SQL を書く Claude セッション向け） |
| `sql-schema-record.py` | PostToolUse / Bash | スキーマ照会クエリを検出してセッション内 state に記録（上の check と対） | 同上 |
| `parallel-notification.py` | Notification / Stop | 並走 clone（`*-parallel-N`）環境向け WPF ポップアップ通知 + Windows Terminal タブ focus | **WSL2 + Windows Terminal + powershell.exe 前提** |
| `run-drawio-export.sh` | （手動 / skill から） | drawio → SVG 変換ラッパー（Xvfb + drawio） | drawio CLI が必要 |

`parallel-notification.py` は WSL2 上の特殊用途なので、他環境で使う場合は無効化するか各自書き換える想定。

## skill 一覧

### フレームワーク非依存

| Skill | 用途 |
|---|---|
| `create-issue` | GitHub Issue 作成（一時ファイル経由で本文中 `#` 行のエスケープ問題を回避） |
| `edit-issue` | 既存 Issue 本文の編集（`--body-file` で許可確認を回避） |
| `create-pr` | 現在のブランチから PR 作成 |
| `pdf` | Markdown → PDF 生成（SVG を base64 インライン化、相対パス画像、日本語マニュアル向け CSS テンプレ対応） |
| `commit-workflow` | コミット指示の判定と `[カテゴリ] 概要` 形式のメッセージ規約、デバッグログ削除確認 |
| `affected-area-testing` | 改修後テストの 4 段階（基本機能 / 新機能 / 統合 / 回帰）と Playwright での実機確認 |
| `playwright-error-detection` | Playwright MCP でのブラウザ検証直後に画面エラーを必ず検出する関数 |
| `pre-implementation-research` | 実装着手前の DB スキーマ実取得 + 仕様書確認 + serena 優先での既存実装把握 |
| `documentation-standards` | docs/ 配下のディレクトリ構造・命名規則・顧客向け/開発者向けの書き分けと PDF 生成手順 |
| `create-manual` | feature PR とセットで現場向け操作マニュアルを作成。物理名 → 業務語の置換ルール / レビュー観点チェックリスト / スクショ撮影手順 / マニュアル雛形を内包 |
| `issue` | Issue 番号指定で「main 取得 → 設計書ゲート → 実装 → テスト → PR → レビュー → マニュアル → ブラウザテスト」を一括実行（Laravel + Livewire を例として説明） |
| `parallel-setup` | 並走 clone（worktree でない独立 clone を 4〜7 本）を立てる pattern と手順。役割（feature/hotfix/PoC/refactor 等）別の分担、COMPOSE_PROJECT_NAME / ポート / .mcp.json の isolation、`parallel-notification.py` hook の wiring、共有 DB の扱い、運用 Tips |

### 特定スタック前提

| Skill | 前提スタック | 用途 |
|---|---|---|
| `livewire-v3-syntax` | Laravel + Livewire 3.x | v3 構文の徹底（v2 構文の検出と修正、context7 MCP で仕様確認） |
| `tailwind-enforcement` | Tailwind CSS | style 属性禁止、Tailwind utility class 必須 |
| `debug-bar-investigation` | Laravel Debug Bar | データ取得問題の 3 段階調査（再現 → Messages → Queries） |
| `route-management` | Laravel + Context 構成（DDD / モジュラーモノリス） | `routes/web.php` 直書き禁止、Context の ServiceProvider に集約 |

各 skill は `skills/global/<name>/SKILL.md` 自体に詳細な進め方が書かれている。Claude Code が auto-load してその手順に従う。スタック前提の skill は不要なら symlink を張らない、もしくは `settings.json` の `permissions.allow` から該当行を消す運用で OK。

## statusline

`statusline.sh` は 2 行構成:

- **1 行目**: セッション名 / Git ブランチ / カレントディレクトリ
- **2 行目**: モデル名 / コンテキスト使用率バー（70% で黄・90% で赤）/ セッションコスト / レートリミット

依存: `jq`、`git`。

## 運用ポリシー

- skill / hook / settings の中身は本リポで一元管理し、`~/.claude/` 側は symlink にする
- `~/.claude/settings.local.json` はマシン固有の allow リストや env を入れる用途なので、本リポでは追跡しない（`.gitignore` で除外済み）
- 新規 skill を追加するときは `skills/global/<name>/SKILL.md` を書き、必要なら `settings.json` の `permissions.allow` に `Skill(<name>)` を追加

## ライセンス

利用や fork は自由にどうぞ。設定例のテンプレートとして使えるよう、固有情報は含めていません。
