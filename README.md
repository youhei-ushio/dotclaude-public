# dotclaude-public

[Claude Code](https://claude.com/claude-code) の user-level 資産（`~/.claude/` 配下に置く skill / hooks / settings / CLAUDE.md / statusline）の dotfiles テンプレート。

複数マシン間で `~/.claude/` を同期するために、リポを clone してシンボリックリンクを張る運用を想定しています。

> **言語・フレームワーク非依存の core を志向しています。** 汎用 skill / hook は
> 特定言語に依存せず、TypeScript / .NET / Go / Rails / Laravel など任意のスタックで
> 使えます。本文に出てくる Laravel / Sail 等は「数ある例の一つ」であり前提では
> ありません。特定スタックに踏み込んだ資産は後述の「特定スタック前提」で分離し、
> opt-out できるようにしています。

## このリポで管理するもの

| 項目 | 配置先 | 役割 |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | global ルール（言語・コード discovery 方針 等） |
| `settings.json` | `~/.claude/settings.json` | env / permissions / hooks のサンプル設定 |
| `statusline.sh` | `~/.claude/statusline.sh` | 最大 3 行構成のカスタム statusline（pending review 行を含む） |
| `hooks/` | `~/.claude/hooks/` | PreToolUse / PostToolUse / PermissionRequest / UserPromptSubmit / SessionStart / Notification / Stop の hook スクリプト |
| `skills/global/` | `~/.claude/skills/` | プロジェクト非依存の global skill |
| `tmux-grid.sh` | （リポ直下で直接実行） | 並走 worktree を 3×2 の tmux グリッドで起動するランチャ（symlink せず `./tmux-grid.sh` で使う。`DIR_PREFIX` 等は環境変数で上書き） |

## 前提ツール

### Required（最低限必要）

- **`git`** — clone / pull に使用
- **`python3`**（3.9 以降） — 全 hook スクリプトの実行ランタイム
- **`gh`** CLI — `create-issue` / `edit-issue` / `create-pr` / `issue` skill が `gh` を呼ぶ
- **`jq`** — `statusline.sh` が Claude Code からの JSON 入力をパースするのに使用

### Optional（特定の skill / hook 使用時のみ）

| ツール | 必要な skill / hook |
|---|---|
| `npx` (Node.js) | `pdf` skill が `md-to-pdf` を呼ぶ |
| `drawio` CLI + `Xvfb` | `run-drawio-export.sh` hook（drawio → SVG 変換） |
| `powershell.exe`（WSL2、任意） | `notify-sound.sh` hook が WSL2 で Windows の通知音を鳴らす場合（native Linux では `paplay` 等で代替、無ければ無音） |
| `tmux` | `tmux-grid.sh` / `tmux-pane-awaiting.sh`（並走ペインのボーダーで応答待ち/完了を表示） |
| Google Chrome / Chromium | `pdf` skill の PDF レンダリング（md-to-pdf 経由） |
| `fonts-ipafont-gothic` | `pdf` skill で日本語マニュアル生成時の文字化け回避 |
| `pip` (Python パッケージマネージャ) | `pdf-read` skill が初回実行時に `pypdfium2` / `Pillow` / `pdfplumber` を自動 install |

### MCP サーバー（任意）

下記 MCP を利用する場合は別途 `~/.claude.json` 等で設定する。本リポは MCP 設定は同梱しない。

| MCP | 関連する skill / hook |
|---|---|
| `serena` | `serena-enforcer.py` hook（コード discovery 誘導）、各 skill のコード探索 |
| `playwright` | `playwright-error-detection` skill、`create-manual` skill のスクショ撮影 |
| `context7` | `livewire-v3-syntax` skill が最新仕様確認に使用 |
| `laravel-boost` | `pre-implementation-research` / `create-manual` skill（Laravel + Sail 環境のみ） |

> **設置前にバックアップ推奨**: 既に `~/.claude/CLAUDE.md` / `~/.claude/settings.json` 等を持っている場合、本リポからの symlink で上書きされる。事前に退避すること。

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
| `destructive-guard.py` | PreToolUse / Bash | broad allowlist 下でも自動承認されうる「git でも復旧不可 / 高被害」なコマンド形（`find -delete` / force push / `git clean -f` / `~/.claude`・`~/.ssh`・システムパスへの上書き等）だけを block する二重防御。末尾に `# via:destructive-ok: <理由>` を付ければ bypass | 汎用 |
| `sail-env-inline-block.py` | PreToolUse / Bash | `COMPOSE_PROJECT_NAME=... ./vendor/bin/sail ...` のインライン環境変数指定を block | Laravel Sail 利用時のみ意味あり（他環境では空振り） |
| `sql-schema-check.py` | PreToolUse / Write | `.sql` ファイル書き込み時に参照テーブルが事前確認済みかバリデート | 汎用（SQL を書く Claude セッション向け） |
| `sql-schema-record.py` | PostToolUse / Bash | スキーマ照会クエリを検出してセッション内 state に記録（上の check と対） | 同上 |
| `notify-sound.sh` | Notification / PermissionRequest / Stop | クロスプラットフォームな通知音（WSL2 は powershell.exe で Windows 音、native Linux は `paplay`/`pw-play`/`ffplay`/`aplay`）。常に exit 0 | 汎用（再生手段が無ければ無音で no-op） |
| `permission-request-logger.py` | PermissionRequest | 許可ダイアログの内容を `~/.claude/logs/permission-requests.jsonl` に JSONL 記録（`/review-permissions` skill でまとめてレビューする用）。秘密値を含みうるため 0o600 で書き込み | 汎用（`/review-permissions` skill と対） |
| `tmux-pane-awaiting.sh` | UserPromptSubmit / PostToolUse / PermissionRequest / Stop / SessionStart | tmux 6 ペイングリッド（`tmux-grid.sh`）運用時、発火ペインのボーダー色で状態を示す（応答待ち=赤 / 完了=緑 / 作業中=無印）。statusline は各ペイン最下部で埋もれるため、ボーダー側に出す | tmux 6 ペイングリッド運用向け（tmux 外では何もしない） |
| `run-drawio-export.sh` | （手動 / skill から） | drawio → SVG 変換ラッパー（Xvfb + drawio） | drawio CLI が必要 |

## skill 一覧

### フレームワーク非依存

| Skill | 用途 |
|---|---|
| `create-issue` | GitHub Issue 作成（一時ファイル経由で本文中 `#` 行のエスケープ問題を回避） |
| `edit-issue` | 既存 Issue 本文の編集（`--body-file` で許可確認を回避） |
| `create-pr` | 現在のブランチから PR 作成 |
| `pdf` | Markdown → PDF 生成（SVG を base64 インライン化、相対パス画像、日本語マニュアル向け CSS テンプレ対応） |
| `pdf-read` | PDF を全ページ PNG にレンダリング + テキスト抽出。PowerPoint 由来 PDF の図表内文字（SmartArt / 表セル内）を視覚確認するため（pypdfium2 / Apache 2.0 + Pillow + pdfplumber） |
| `commit-workflow` | コミット指示の判定と `[カテゴリ] 概要` 形式のメッセージ規約、デバッグログ削除確認 |
| `affected-area-testing` | 改修後テストの 4 段階（基本機能 / 新機能 / 統合 / 回帰）と Playwright での実機確認 |
| `playwright-error-detection` | Playwright MCP でのブラウザ検証直後に画面エラーを必ず検出する関数 |
| `pre-implementation-research` | 実装着手前の DB スキーマ実取得 + 仕様書確認 + serena 優先での既存実装把握 |
| `documentation-standards` | docs/ 配下のディレクトリ構造・命名規則・顧客向け/開発者向けの書き分けと PDF 生成手順 |
| `create-manual` | feature PR とセットで現場向け操作マニュアルを作成。物理名 → 業務語の置換ルール / レビュー観点チェックリスト / スクショ撮影手順 / マニュアル雛形を内包 |
| `issue` | Issue 番号指定で「main 取得 → 設計書ゲート → 実装 → テスト → PR → レビュー → マニュアル → ブラウザテスト」を一括実行（手順自体はフレームワーク非依存。テスト/PR 等の具体例として Laravel + Sail 等を併記） |
| `parallel-setup` | 並走 clone（worktree でない独立 clone を 4〜7 本）を立てる pattern と手順。役割（feature/hotfix/PoC/refactor 等）別の分担、COMPOSE_PROJECT_NAME / ポート / .mcp.json の isolation、通知（tmux ペインボーダー / 通知音）の wiring、共有 DB の扱い、運用 Tips |
| `review-permissions` | 蓄積された許可要求ログ（`permission-request-logger.py` が記録）をクラスタ単位で対話レビューし、allowlist 追加 / skill 化 / hook 化 / スクリプト化 / 都度確認継続 を判断 |
| `add-hook` | 新しい hook を本リポに追加し `settings.json` への配線・検証・テストまでを型化。「settings 参照 hook がファイル欠落で全 tool を block する」致命事故を防ぐ |
| `review-pr` | 指定 PR をセルフレビュー。Reviewer A/B + Fact-checker の 3 エージェント並列構成（worktree 分離）。自分が author の PR は最大 5 巡で auto-fix モード、collaborator の PR は自動的に review-only モードで GitHub に summary review コメントを投稿（`--review-only` / `--fix` で明示 override 可）|
| `handoff` | 作業状態を `~/.claude/handoff/` の Markdown に保存し、後で読み込んで続きから再開（`save` / `load` / `list`）。セッション跨ぎの引き継ぎやタスク切り替えに使う。`save` デフォルトタスク名は `/rename` 由来のセッション名（`~/.claude/sessions/`）を参照し、未設定でも会話文脈から推測して動作する |
| `systematic-debugging` | バグ原因究明の系統的規律。根本原因を掴む前に修正しない大原則 + 4 フェーズ（計測でデータフロー遡及 → working/broken 差分 → 単一仮説 1 変数検証 → 失敗テスト先行で 1 点修正）。「3 回失敗したらアーキを疑う」等。serena / 既存の検証手段と接続。スタック固有のデータ調査 skill があればフェーズ 1 の具体手段として併用 |
| `tdd` | test-first（RED→GREEN→REFACTOR）の既定手順。失敗（RED）を必ず観測してから最小実装。superpowers の「テスト前コード全削除」絶対ルールは不採用（「シンプル第一」と衝突しうるため）。後追いで固める場合も RED を一度は観測する |
| `large-feature-execution` | 大型機能を永続プラン（`docs/development/plans/`）+ タスク単位 subagent + レビューゲートで遂行。context 圧縮を跨いで方針が揮発・散逸するのを防ぐ。大型機能のときだけ使う |
| `writing-skills` | SKILL.md 作成規約。description=auto-load トリガー仕様として書く / frontmatter・本文構成 / README・settings.json への登録 / dead link を作らない検証 |

### 特定スタック前提

| Skill | 前提スタック | 用途 |
|---|---|---|
| `livewire-v3-syntax` | Laravel + Livewire 3.x | v3 構文の徹底（v2 構文の検出と修正、context7 MCP で仕様確認） |
| `tailwind-enforcement` | Tailwind CSS | style 属性禁止、Tailwind utility class 必須 |
| `debug-bar-investigation` | Laravel Debug Bar | データ取得問題の 3 段階調査（再現 → Messages → Queries） |
| `route-management` | Laravel + Context 構成（DDD / モジュラーモノリス） | `routes/web.php` 直書き禁止、Context の ServiceProvider に集約 |

各 skill は `skills/global/<name>/SKILL.md` 自体に詳細な進め方が書かれている。Claude Code が auto-load してその手順に従う。

#### 不要なスタック固有 skill の opt-out

PHP/Laravel を使わない場合など、上表の「特定スタック前提」skill が不要なら、以下で無効化する。**手順 1（symlink を消す）が主**で、これだけで `~/.claude/` 側の symlink が外れ auto-load も止まる（skill の実体はリポに残るだけで消えない）。手順 2 は補助。

1. **symlink を張らない / 消す（主）** — 前述「セットアップ」の global skill ループは `for d in .../skills/global/*/` の glob 展開なので、特定ディレクトリだけを除外するより、**ループは全張りし、後から `rm ~/.claude/skills/<name>` で外す**運用が確実（例: `rm ~/.claude/skills/livewire-v3-syntax`）。これで symlink が外れ、当該 skill は読み込まれなくなる（実体はリポに残る）。ただし `rm` 後にセットアップループを再実行すると symlink は復活するため、**恒久的に除外したいときは setup ループ側で当該ディレクトリを除外する**（例: `for d in $(ls -d .../skills/global/*/ | grep -v '/livewire-v3-syntax/'); do ...; done`、または対象を明示列挙する）か、`rm` をセットアップ手順に組み込む
2. **`settings.json` の `permissions.allow` から該当行を消す（補助）** — 例: `Skill(livewire-v3-syntax)` / `Skill(route-management)` / `Skill(debug-bar-investigation)` / `Skill(tailwind-enforcement)` を削除。これは「skill 実行時に確認を挟まない」allowlist を外すだけで、auto-load 自体を止める保証は Claude Code の内部挙動依存。確実に無効化したいときは手順 1 を使う

hook 側も同様に、Laravel Sail 専用の `sail-env-inline-block.py` や SQL ワークフロー用の `sql-schema-check.py` / `sql-schema-record.py` が不要なら、**symlink を張らない**（前述「セットアップ」の hook ループで除外、または `rm ~/.claude/hooks/<name>.py`）か、**`settings.json` の `hooks` 配列から該当エントリを外す**（他環境では空振りするだけなので、残しても害はない）。

#### 言語別に fork しない方針

「他言語で使いたい」場合でも **言語ごとにリポを fork しない**ことを推奨する。fork すると `commit-workflow` / `create-pr` のような全言語共通の改善が各 fork に伝播せず drift（同期ズレ）し、二重メンテになる。**単一リポで「言語非依存の core ＋ オプトインな stack 層」** を維持し、必要なスタック固有資産だけを足し引きする運用にする。

将来、特定言語向けの skill / hook を増やす場合も、core を汚さずに `skills/global/` 配下へ「特定スタック前提」として追加し、上記 opt-out 手順で取捨選択できる形を保つ。

## statusline

`statusline.sh` は最大 3 行構成（3 行目は該当が無ければ非表示）:

- **1 行目**: セッション名 / Git ブランチ / カレントディレクトリ
- **2 行目**: モデル名 / コンテキスト使用率バー（70% で黄・90% で赤）/ セッションコスト / レートリミット
- **3 行目**: 未レビュー許可要求の件数（`permission-request-logger.py` が記録したログの行数。`/review-permissions` で棚卸し）

依存: `jq`、`git`。

> 並走 clone を tmux 6 ペイングリッドで動かす場合の「どのペインが応答待ちか」は、
> statusline ではなく `tmux-grid.sh` + `tmux-pane-awaiting.sh` によるペインボーダー表示で扱う。

## 運用ポリシー

- skill / hook / settings の中身は本リポで一元管理し、`~/.claude/` 側は symlink にする
- `~/.claude/settings.local.json` はマシン固有の allow リストや env を入れる用途なので、本リポでは追跡しない（`.gitignore` で除外済み）
- 新規 skill を追加するときは `skills/global/<name>/SKILL.md` を書き、必要なら `settings.json` の `permissions.allow` に `Skill(<name>)` を追加

## ライセンス

[MIT License](./LICENSE)。利用や fork は自由にどうぞ。設定例のテンプレートとして使えるよう、固有情報は含めていません。
