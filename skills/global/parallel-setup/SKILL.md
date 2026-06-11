---
name: parallel-setup
description: |
  並走 clone（worktree でない独立 clone を 4〜7 本）を役割別に立てる pattern と手順。
  「parallel セットアップして」「並走環境について教えて」のような自然言語で起動。
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
---

# 並走開発環境（Parallel Development）

git worktree ではなく、**独立した clone を複数（典型的に 4〜7 本）並走** させて、
role 別に作業を割り当てるパターン。docker-compose ベースの開発で特に有効。

> **本 skill はフレームワーク非依存**です。考え方（命名規約・isolation・
> 通知 hook の wiring 等）は docker-compose で動く任意のスタック（Node /
> .NET / Go / Rails / Laravel 等）に適用できます。本文中のコマンドは
> 素の `docker compose` で書いていますが、Laravel Sail なら
> `./vendor/bin/sail`、その他のラッパーがあればそれぞれに読み替えてください。

## なぜ worktree でなく独立 clone か

worktree は `.git` 本体 + 場合により `vendor/` / `node_modules/` / DB volume を
共有する設計。共有していると、ある clone で

- 破壊的マイグレーション
- 依存パッケージの大幅更新
- DB schema の実験

を試そうとした瞬間に他の clone が壊れる。

並走 clone は **完全独立**。各 clone が独自の docker-compose stack を持ち、
ある clone での実験が他に波及しない。

代償:

- ディスク使用量増（並走数倍）
- メモリ使用量増（並走数分の DB コンテナ等）
- 同期作業が必要（一括 git pull / 再ビルド）

費用対効果が合う条件:

- 開発機が SSD 1TB クラス + RAM 32GB 以上
- 短期間に複数の異なる文脈（feature / hotfix / PoC）を切り替える必要がある
- DB / 依存 / インフラに破壊実験を伴う作業が出てくる

## ディレクトリ命名規約

```
~/repos/
├── <project>-parallel-1/   # role: feature
├── <project>-parallel-2/   # role: hotfix
├── <project>-parallel-3/   # role: poc
├── <project>-parallel-4/   # role: issue-authoring
├── <project>-parallel-5/   # role: feature (本流 2 本目)
├── <project>-parallel-6/   # role: refactor
└── <project>-parallel-7/   # role: docs-curation
```

**`<project>-parallel-N` 形式**。同梱の `parallel-notification.py` hook が
`PARALLEL_RE = re.compile(r"-parallel-(\d+)")` でディレクトリ名から N を
抽出する設計。命名を変える場合は hook 側の正規表現も合わせて書き換える。

## 役割テンプレ (CLAUDE.local.md)

各 parallel に **CLAUDE.local.md** を置き、その clone の役割と運用ルールを宣言する。

役割例（自プロジェクトに合わせて取捨選択）:

| 役割 | 用途 |
|---|---|
| feature | 通常の機能開発・改修・PR 作成。本流が忙しいときは複数 parallel に同じ feature 役割を割り当てて 2 本走らせることもある（上のツリー例の parallel-1 と parallel-5）|
| hotfix | 緊急バグ対応。最小 diff の原則 |
| poc | PoC・実験。マージしない前提、破壊的変更 OK |
| issue-authoring | Issue 起票・調査専用 |
| refactor | リファクタ専用 |
| docs-curation | ドキュメント整備専用 |
| reviewer | 他 parallel の PR レビュー専用 |

CLAUDE.local.md テンプレ:

```markdown
## このワークスペースの役割

ここは **<役割>** の作業ディレクトリです。parallel-N。

### 開発URL
http://localhost:<port>   # 例: parallel-1 なら http://localhost:8081

### 構成上の注意
- Compose Project 名: `<project><N>`
- ホスト側ポート: app=<app-port>, vite=<vite-port>, db=<db-port>

### 行動原則
- <役割固有のルールを書く>
```

CLAUDE.local.md は **git 管理外** (`.gitignore`) に置き、各 parallel 専用。
`.local.md` は Claude Code が CLAUDE.md と並んで読む「マシン別 / clone 別の
上書きファイル」用の命名 convention で、`.gitignore` に登録すれば各 parallel
で異なる内容を持てる。配布時に sed で `<project><N>` / `<port>` / `<役割>`
等のプレースホルダーを置換する想定。

## Isolation のコツ

並走 clone が互いに干渉しないための要素を 4 点に整理:

### 1. COMPOSE_PROJECT_NAME を機械式に固定

各 parallel で `<project><N>` を使う（例: `myapp1`, `myapp2`, ...）。

**推奨**: `.claude/settings.local.json` の `env.COMPOSE_PROJECT_NAME` で設定。

```json
{
  "env": {
    "COMPOSE_PROJECT_NAME": "myapp1"
  }
}
```

インライン指定（`COMPOSE_PROJECT_NAME=... ./vendor/bin/sail ...`）は同梱の
`sail-env-inline-block.py` hook がブロックする。インライン指定は
`Bash(./vendor/bin/sail *)` 等の permission rule にマッチせず毎回許可確認が
出るためで、settings.local.json で env 固定する方が摩擦が少ない。

### 2. ポート番号を機械式に割り当て

**サービスごとにベースポートを決め、parallel 番号 N をオフセットとして
加える**。例:

| parallel | APP_PORT (8080+N) | VITE_PORT (5270+N) | DB_PORT (3400+N) | MAILPIT_SMTP (1120+N) | MAILPIT_UI (8120+N) |
|---|---|---|---|---|---|
| 1 | 8081 | 5271 | 3401 | 1121 | 8121 |
| 2 | 8082 | 5272 | 3402 | 1122 | 8122 |
| 3 | 8083 | 5273 | 3403 | 1123 | 8123 |
| ... | ... | ... | ... | ... | ... |

各 parallel の `.env` / `.env.testing` をこのルールで機械式に生成する。
ベースポートは自プロジェクトのデフォルトに合わせる（上の例は Laravel Sail
の標準ポート `APP_PORT=80` / `VITE_PORT=5173` / `FORWARD_DB_PORT=3306` を
それぞれ `8080+N` / `5270+N` / `3400+N` 形式に置き換えたもの）。

### 3. .mcp.json は各 parallel で実体化

`.mcp.json` はプロジェクト直下に置く Claude Code の project-scope MCP
設定。Claude Code がセッション開始時に読み込み、その内容に従って MCP
サーバー群を起動する。中身には serena の `--project <絶対パス>` 引数や、
laravel-boost の `env.COMPOSE_PROJECT_NAME=<projectN>` のように
**各 parallel で違う値** が含まれるため、**リポジトリ追跡せず各 parallel
で実体化** する。

プロジェクトの `.gitignore` に以下を追記:

```gitignore
.mcp.json
```

テンプレ `.mcp.json.example` のみ追跡し、各 parallel で `cp + sed` で
プレースホルダーを置換して生成:

```bash
sed \
  -e "s|<ABSOLUTE_PATH_TO_THIS_PARALLEL>|/home/$USER/repos/myapp-parallel-1|g" \
  -e "s|<COMPOSE_PROJECT_NAME>|myapp1|g" \
  .mcp.json.example > .mcp.json
```

テンプレ変更（`.mcp.json.example` 編集）は PR 経由で全 parallel に届くが、
**`.mcp.json` 実体は各 parallel で個別に再生成する必要がある**（git pull
だけでは更新されない）。

### 4. 役割テンプレに特定 N をハードコードしない

複数 parallel で同じ役割（例: parallel-1 と parallel-5 がどちらも feature）を
共用するときは、role-templates 内に `COMPOSE_PROJECT_NAME=myapp1` のような
**特定 N をハードコードしないこと**。

これは事故の温床になる。実例: 共用テンプレに `myapp1` がハードコードされて
いて、parallel-5 で Claude Code が CLAUDE.local.md を読んだ結果
`COMPOSE_PROJECT_NAME=myapp1 docker compose down` を parallel-5 のディレクトリで
実行し、**parallel-1 のコンテナを意図せず停止する** という事故が起きうる。

回避策: テンプレはプレースホルダー（`<COMPOSE_PROJECT_NAME>`、`<APP_PORT>` 等）
で書き、各 parallel に配布する時点で sed で具体値に置換する。

## parallel-notification.py の wiring

同梱の `parallel-notification.py` hook が Notification / Stop イベントで
WPF ポップアップを上げる。並走中に「どの parallel が完了したか」「どれが
ユーザー応答待ちか」を視覚的に区別できる。

**WSL2 + Windows Terminal + powershell.exe 前提**。Linux / macOS ネイティブ
環境では別途通知 hook を書く必要がある（例: `notify-send` /
`terminal-notifier`）。

設定ポイント:

```python
# parallel-notification.py の冒頭
PARALLEL_CONFIG: dict[int, tuple[str, str]] = {
    1: ("feature",         "#2563EB"),   # blue
    2: ("hotfix",          "#DC2626"),   # red
    3: ("poc",             "#7C3AED"),   # purple
    4: ("issue-authoring", "#0D9488"),   # teal
    5: ("feature",         "#0891B2"),   # cyan
    6: ("refactor",        "#EA580C"),   # orange
    7: ("docs-curation",   "#16A34A"),   # green
    8: ("reviewer",        "#475569"),   # gray
}

PARALLEL_TO_TAB_INDEX: dict[int, int] = {
    1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7,
}
```

- `PARALLEL_CONFIG` のラベル・色を自プロジェクトの役割に合わせて編集
- `PARALLEL_TO_TAB_INDEX` は Windows Terminal の各タブのインデックス（タブを
  並び替えたらここを更新）
- ポップアップをクリックすると該当タブに focus する仕組み（`wt -w 0 focus-tab`）

## セットアップフロー

新規プロジェクトで初めて parallel を立てる場合の最小手順。

### Phase 0: 前提確認

- Docker Desktop / Docker Engine が動く OS（本 skill の例は WSL2 + Docker
  Desktop を想定。Linux / macOS ネイティブでも動作するが、後述の
  `parallel-notification.py` hook だけは WSL2 + Windows Terminal 固有）
- 開発機のメモリ余裕（負荷時最大で 並走数 × 3GB 程度。idle 時はもっと少ない。
  詳細は後述「メモリ使用量の目安」参照）
- ディスク余裕（並走数 × プロジェクトの clone サイズ）

### Phase 1: 全 parallel の clone + 設定生成

各 parallel を **`for` ループで一括生成** する。各イテレーションをサブ
シェル `(...)` で囲み、末尾に `&` を付けてバックグラウンド並列実行する。
N=1 を「先に動かして動作確認したい」ときは下記 `for N in 1 2 3 4 5 6 7`
を `for N in 1` に絞って先に流すと良い。

> **`cp -r ~/repos/<project>-parallel-1 ...` で `.git` ごと複製する方法は、
> remote tracking branch や git hooks の状態が共有されてしまう副作用がある
> ため非推奨**。各 parallel は新規 `git clone` する方が安全。

```bash
PROJECT=myapp
REPO_URL=<repo-url>

for N in 1 2 3 4 5 6 7; do
  (
    # 新規 clone
    git clone "${REPO_URL}" ~/repos/${PROJECT}-parallel-${N}

    # Compose Project 名の固定
    mkdir -p ~/repos/${PROJECT}-parallel-${N}/.claude
    cat > ~/repos/${PROJECT}-parallel-${N}/.claude/settings.local.json <<EOF
{
  "env": {
    "COMPOSE_PROJECT_NAME": "${PROJECT}${N}"
  }
}
EOF

    # ポート番号を BASE_PORT + N で書き換え
    cd ~/repos/${PROJECT}-parallel-${N}
    sed -i "s|^APP_PORT=.*|APP_PORT=$((8080 + N))|" .env
    sed -i "s|^VITE_PORT=.*|VITE_PORT=$((5270 + N))|" .env
    sed -i "s|^DB_PORT=.*|DB_PORT=$((3400 + N))|" .env
    # ... 他ポートも同様の式で

    # .mcp.json の実体化（テンプレ .mcp.json.example から sed で生成）
    sed \
      -e "s|<ABSOLUTE_PATH_TO_THIS_PARALLEL>|$HOME/repos/${PROJECT}-parallel-${N}|g" \
      -e "s|<COMPOSE_PROJECT_NAME>|${PROJECT}${N}|g" \
      .mcp.json.example > .mcp.json
  ) &
done
wait
```

サブシェル化により各イテレーションの `cd` は外側に漏れず、ループ終了時に
ユーザーは元のディレクトリに残る。

> **git サーバーへの並列 fetch に注意**: 同じリポを 7 本同時に clone すると、
> 自前 git サーバーの rate-limit や GitHub の abuse detection に引っかかる
> 可能性がある。引っかかったら `) &` を `)` に変更し末尾 `wait` を削って
> シリアル実行に戻す。

### Phase 2: 全 parallel の起動

各 parallel を直列に起動すると 1 つあたり 30〜90 秒、7 並走で 3〜10 分の
シリアル実行になる。**バックグラウンド並列起動 → 最後に一括で health 確認**
する方が速い:

```bash
PROJECT=myapp

# 1. 全 parallel をバックグラウンドで起動（並列）
for N in 1 2 3 4 5 6 7; do
  (cd ~/repos/${PROJECT}-parallel-${N} && docker compose up -d) &
done
wait

# 2. 全コンテナの health 状態をまとめて確認
docker ps --format 'table {{.Names}}\t{{.Status}}' \
  | grep -E "^${PROJECT}[0-9]+-"
```

`(... ) &` でサブシェル化してバックグラウンド実行、最後に `wait` で全完了
を待つ。docker daemon 側で並列にイメージビルド・コンテナ起動が走る。

### Phase 3: 役割テンプレ配布

各 parallel に CLAUDE.local.md を配置する。テンプレ自体（プレースホルダー
入りの `.md` 雛形群）は **プロジェクトリポの `.claude/role-templates/`
等に置く想定**。役割テンプレ自体は branch 共有で全 parallel に届くが、
**どの parallel にどの役割を割り当てるかは parallel 固有**:

```bash
# 例: parallel-N に role 'feature' を割り当てる
ROLE=feature
sed \
  -e "s|<COMPOSE_PROJECT_NAME>|${PROJECT}${N}|g" \
  -e "s|<APP_PORT>|$((8080 + N))|g" \
  -e "s|<役割>|${ROLE}|g" \
  .claude/role-templates/${ROLE}.md > CLAUDE.local.md
```

CLAUDE.local.md は git 管理外（前述）なので、各 parallel で自由に書き
換えてよい。テンプレ側（`role-templates/`）を変更した場合は各 parallel
で再生成が必要（`git pull` だけでは CLAUDE.local.md は更新されない）。

### Phase 4: Windows Terminal タブ整列

並走中の視認性を上げるため、各 parallel のターミナルを Windows Terminal
の別タブで開く。`PARALLEL_TO_TAB_INDEX` で指定したインデックス順序と物理的な
タブ位置を一致させる:

1. Windows Terminal を起動、parallel-1 のディレクトリに `cd`（タブ index = 0）
2. `Ctrl+Shift+T` で新規タブを開き、parallel-2 のディレクトリに `cd`（index = 1）
3. parallel-3 以降も同様に新規タブで開く
4. タブを並び替えるには **Ctrl+Shift+PgUp / PgDn** でタブを左右に移動

タブを並び替えたら `parallel-notification.py` の `PARALLEL_TO_TAB_INDEX`
を実際の並び順に合わせて更新する（更新を怠るとポップアップクリックの
focus 先がズレる）。

### Phase 5: 動作確認

各 parallel が isolation されていることを機械的に確認:

```bash
PROJECT=myapp

# 1. 各 parallel が割り当てたポートで応答する
for N in 1 2 3 4 5 6 7; do
  PORT=$((8080 + N))
  echo -n "parallel-${N}: "
  curl -sI -o /dev/null -w "http://localhost:${PORT} → %{http_code}\n" \
    "http://localhost:${PORT}"
done

# 2. 全 parallel のコンテナが見える
docker ps --format '{{.Names}}' | grep -E "^${PROJECT}[0-9]+-"

# 3. isolation テスト: 適当な 1 parallel を止めても他は動く
TARGET_N=3   # 検証対象（自由に選ぶ）
EXPECTED=$(docker ps --filter "name=${PROJECT}${TARGET_N}-" -q | wc -l)
BEFORE=$(docker ps -q | wc -l)
(cd ~/repos/${PROJECT}-parallel-${TARGET_N} && docker compose stop)
AFTER=$(docker ps -q | wc -l)
DIFF=$((BEFORE - AFTER))

echo "停止前: ${BEFORE} 件、停止後: ${AFTER} 件、差分: ${DIFF}"
echo "期待値: ${EXPECTED}（parallel-${TARGET_N} のコンテナ数）"
[ "${DIFF}" -eq "${EXPECTED}" ] && echo "✅ isolation OK" || echo "❌ 想定外: 他 parallel に影響が出ている"
```

## 運用 Tips

### master / main 直接 push 禁止 + PR フロー徹底

並走中は **どの parallel でどのブランチを触っているか** が混乱の元。
master / main への直 push は禁止し、必ず PR 経由でマージするルールを敷く。
同梱の `git-push-merged-pr-check.py` hook が「MERGED PR を持つ branch への
追加 push」をブロックする。

### parallel 切替前の clean 確認

ある parallel に入る前に必ず `git status` で clean 確認、どのブランチに
いるかを確認する習慣。feature/hotfix 作業中の parallel に間違って入って
別ブランチを切ると、後で「あれ、この変更はどの parallel で作ったんだっけ」
となる。

### docker compose down -v 禁止

`-v` オプションは named volume を削除する。共有 DB（後述）を持つ構成では
他 parallel のデータを巻き込んで消し飛ばす事故になる。停止は
`docker compose stop` または `docker compose down`（オプションなし）のみ。

### 共有 DB の扱い

各 parallel で完全独立 DB を持つ前提なら、自 parallel 内では破壊操作
（`migrate:fresh` / `TRUNCATE` / `DROP DATABASE`）は自由。

共有 DB（例: 共通マスタを別コンテナで持つ場合）を持つ構成では、共有 DB に
対する破壊操作は禁止。共有 DB を持つ構成は **共有 DB 専用コンテナ + 各
parallel 専用コンテナ** の二段配置にすると安全:

```
<shared>-db          ← 全 parallel で共有（マスタデータ等）
<project>1-db        ← parallel-1 専用（トランザクション・実験データ）
<project>2-db        ← parallel-2 専用
...
```

### メモリ使用量の目安

実測値はプロジェクト構成（DB / app のメモリプロファイル）に大きく依存
する。Laravel + MySQL + 共有 SQL Server 構成での観測例: 7 並走で idle 時
**総コンテナメモリ 1〜3GB**、負荷時に parallel あたり 3GB 程度。WSL2 の
総メモリ予算が 64GB の環境なら余裕がある。

自プロジェクトでは初回構築後に `docker stats` で実測し、並走数の上限を
逆算すること。

### 並走数の上限

ディスクとメモリの制約で **8〜10 が現実的**。それを超えると Docker のネット
ワーク（特に external network）が増え過ぎて管理が破綻する。役割と並走数を
最初に決めてから着手することを推奨。

### parallel 削除の手順

不要になった parallel は以下の順で削除:

```bash
# 1. コンテナ停止 + 削除
cd ~/repos/<project>-parallel-N
docker compose down  # -v は付けない

# 2. ディレクトリ削除
cd ~
rm -rf ~/repos/<project>-parallel-N

# 3. Windows Terminal タブを閉じる
# 4. parallel-notification.py の PARALLEL_TO_TAB_INDEX を更新（任意）
```

## 注意事項

- 本 skill は **方法論を説明するもの**。具体的な構築スクリプトは自プロジェクト
  固有なので、本 skill は雛形を示すだけ
- 完全な自動化スクリプトを作るなら、プロジェクト側に
  `docs/parallel-setup-runbook.md` のような手順書を別途用意する（本 skill
  名と同名 `docs/parallel-setup.md` は紛らわしいので避ける）
- `parallel-notification.py` は WSL2 + Windows Terminal 前提。Linux / macOS
  ネイティブ環境では別途通知 hook を書く必要がある

## 関連 skill / hook

- `parallel-notification.py` hook（同梱）— 並走中の役割別ポップアップ通知
- `sail-env-inline-block.py` hook（同梱）— COMPOSE_PROJECT_NAME のインライン
  指定を block
- `git-push-merged-pr-check.py` hook（同梱）— MERGED PR ブランチへの追加
  push を block
