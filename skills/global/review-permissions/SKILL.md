---
name: review-permissions
description: 並走環境で蓄積された許可要求ログ (~/.claude/logs/permission-requests.jsonl) をクラスタ単位で対話的にレビューし、allowlist 追加 / skill 化 / hook 化 / スクリプト化 / 都度確認継続 を判断する。「/review-permissions」「許可要求レビュー」「pending review」のような自然言語で起動。
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion
---

# 許可要求レビュー

`~/.claude/logs/permission-requests.jsonl` に蓄積された未レビュー許可要求を、
クラスタ単位で対話的に査読し、適切な運用形態に振り分ける。

## 重要原則

- **一括 yes 禁止**: 必ず 1 クラスタずつ判断を仰ぐ。`AskUserQuestion` を使う
- **危険パターンガード**: 後述の DANGER_PATTERNS にマッチする提案は、追加前に必ず警告し再確認を取る
- **allow の書込先は `~/.claude/settings.local.json`**: 累積する個人 allowlist は gitignore 対象の local 設定に書く（`settings.local.json` は Claude Code が user-level の権限設定として `settings.json` とマージ・有効化して読み込むため、gitignore 対象でも allow は効く）。`~/.claude/settings.json` は dotclaude リポへ symlink されている場合があり、そこへ書くと個人 path や machine 固有の allow が公開リポに焼き込まれてしまう。local が無ければ `{"permissions": {"allow": []}}` で新規作成する（hook 登録のような共有 config は引き続き `settings.json` 側）
- **書き換え前にバックアップ**: `~/.claude/settings.local.json` を編集する前に必ず `.bak.YYYYMMDDHHMMSS` を作る
- **既存ファイル絶対上書き禁止**: skill/hook/script 雛形の生成時、同名既存があれば timestamp suffix で別ファイル名にする

## 動作フロー

### Step 1: ログ読み込み

```bash
LOG=~/.claude/logs/permission-requests.jsonl
[ -s "$LOG" ] || echo "未レビュー件数: 0 (何もすることがありません)"
```

`LOG` を全行読み込んで JSON 配列にする。1 行も無ければ「未レビュー件数: 0」を表示して終了。

### Step 2: クラスタリング

`tool_name` と `tool_input` から正規化キーを計算してクラスタ化する。

```
tool_name == "Bash":
    cmd = tool_input["command"].strip()
    # 最初の 2-3 トークンをキーにする(オプションは捨てる)
    # 例: "./vendor/bin/sail artisan migrate --pretend"
    #     → key = "./vendor/bin/sail artisan migrate"
    # 例: "gh pr view 42 --json title,body"
    #     → key = "gh pr view"
    tokens = []
    for token in cmd.split():
        if token.startswith("-"):
            break
        tokens.append(token)
        if len(tokens) >= 3:
            break
    key = f"Bash({' '.join(tokens)})"

tool_name.startswith("mcp__"):
    key = tool_name  # MCP は tool 名自体で十分に細かい

その他 (Write, Edit, Read, ...):
    # tool_input 内の主要パスをキーに含める
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    key = f"{tool_name}({path})"
```

同じキーのエントリを 1 クラスタにまとめる。

### Step 3: サマリ表示

```
未レビュー: 15 件 (8 クラスタ)
影響 parallel: P1(5), P3(7), P5(3)
直近: 2026-05-26 14:32
```

### Step 4: クラスタごとの対話

各クラスタについて、以下の情報を AskUserQuestion で提示:

- パターン (正規化キー)
- 件数 / parallel 内訳 / 直近時刻
- 具体的なコマンド例 (重複除去して最大 5 件)
- 関連 transcript から前後 tool_use を 3 件抜粋 (= 「その時 Claude が何をしようとしていたか」)。
  ログエントリ自体に `transcript_path` が埋まっているので、そのファイルを Read して直近の tool_use を集める。session_id からの逆引きは不要。
- 候補アクション (4 つまでが UI 上限なので、上位 3 つ + その他 で組む):
  - (a) **allow パターン追加** — 具体 glob 案を提示 (例: `Bash(./vendor/bin/sail artisan:*)`)
  - (b) **skill 化** — 多段手順なら skill 雛形を生成
  - (c) **その他 (hook/script/都度確認/次回送り/離脱)** — 自由入力で詳細聞く

「その他」を選んだら次の AskUserQuestion で以下の細分化に進む:

- hook 化 / script 化 / 都度確認 / 次回送り / **残り全件を次回送りで離脱**

「残り全件を次回送りで離脱」を選んだ場合、その時点で未処理だったクラスタ全てを次回送り扱いとし、即 Step 6 (アーカイブ) へ進む。判断が続かないときに無理に最後まで通さなくて済むようにする運用導線。

### Step 5: アクション実行

#### (a) allow パターン追加

1. `~/.claude/settings.local.json` の有無を確認し、あれば Read（無ければ `{"permissions": {"allow": []}}` を起点とし、実ファイルは手順 5 の Python で生成）
2. `permissions.allow` 配列を取得
3. DANGER_PATTERNS チェック:
   ```
   # コマンド本体 (Bash(...) の先頭トークン) を限定して偽陽性を抑える。
   # `--force-with-lease` や `grep -rf pattern` のような無害な部分文字列を
   # 誤検出しないよう、コマンド名や危険オプションは単語境界 \b で固定する。
   DANGER_PATTERNS = [
       r"^Bash\(rm\b",                       # rm コマンド本体
       r"^Bash\(sudo\b",                     # sudo コマンド本体
       r"^Bash\([^)]*\brm\s+-[A-Za-z]*[rf]", # rm -rf / rm -fr 等 (パイプ後も)
       r"^Bash\([^)]*--force\b(?!-with-lease)",  # --force (but not --force-with-lease)
       r"^Bash\([^)]*\s>\s*/(?!tmp/|var/tmp/|dev/null)",  # / 直下 redirect (tmp等は除外)
       r"^Bash\([^)]*\bcurl\b[^)]*\|\s*(sh|bash)\b",      # curl | sh
       r"^Bash\([^)]*\bwget\b[^)]*\|\s*(sh|bash)\b",      # wget | sh
       r"^Write\(/[^/)]+/?\)",               # / 直下 1 階層への Write
       r"^mcp__[^_]+__[^(]*delete",          # MCP delete 系
       r"^mcp__[^_]+__[^(]*drop",            # MCP drop 系
   ]
   ```
   いずれかにマッチしたら AskUserQuestion で「本当に追加するか」を再確認

4. バックアップ: ファイルが既存なら `cp ~/.claude/settings.local.json ~/.claude/settings.local.json.bak.$(date +%Y%m%d%H%M%S)`（新規作成時はバックアップ不要）
5. JSON 読み書きは Python で:
   ```python
   import json
   from pathlib import Path
   p = Path.home() / ".claude" / "settings.local.json"
   text = p.read_text() if p.exists() else ""
   data = json.loads(text) if text.strip() else {}   # 空ファイル(0 byte)でも壊れない
   allow = data.setdefault("permissions", {}).setdefault("allow", [])
   if new_pattern not in allow:
       allow.append(new_pattern)
   p.parent.mkdir(parents=True, exist_ok=True)
   p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
   ```
   既存のフォーマット維持のため `indent=2` で揃える (新規作成時も同じ indent で出力)

#### (b) skill 化

1. skill 名をユーザーに聞く (kebab-case)
2. 配置先: `~/repos/dotclaude/skills/global/<name>/SKILL.md` (既存 skill が dotclaude 配下にあるため。同 dir に既存名があれば中止)
3. シンボリックリンク: `~/.claude/skills/<name>` → `~/repos/dotclaude/skills/global/<name>`
4. SKILL.md 雛形:
   ```markdown
   ---
   name: <name>
   description: <ユーザーが入力>。「<トリガー>」のような自然言語で起動。
   allowed-tools: Read, Bash
   ---

   # <タイトル>

   <!-- TODO: ここに skill の説明を書く -->

   ## 手順

   <!-- TODO: 具体的な手順 -->
   ```
5. 「あとでロジックを詰めてください」とユーザーに伝える

#### (c-1) hook 化

1. hook 名 (kebab-case) と matcher (Bash / Write / etc) をユーザーに聞く
2. 配置先: `~/.claude/hooks/<name>.py` (既存があれば timestamp suffix)
3. PreToolUse 用の最小雛形を書く (既存 `serena-enforcer.py` のヘッダを参考に)
4. settings.json の `hooks.PreToolUse` に登録するかは別途確認

#### (c-2) スクリプト化

1. スクリプト名 (kebab-case) と概要をユーザーに聞く
2. 配置先: `~/.claude/scripts/<name>.sh` (dir が無ければ作成)
3. シェル雛形 (TODO コメント込み) を生成
4. allow パターンとして `Bash(~/.claude/scripts/<name>.sh:*)` を settings.local.json に追加（(a) と同じ書込先）

#### (c-3) 都度確認継続

何もしない。ただしログからは reviewed へ移す (明示的判断として記録)。

#### (c-4) 次回送り

該当クラスタの全エントリは `permission-requests.jsonl` に残す。

### Step 6: アーカイブ

すべてのクラスタを処理したら:

1. 処理済みエントリ (次回送り以外) を `~/.claude/logs/permission-requests-reviewed.jsonl` に append
2. `~/.claude/logs/permission-requests.jsonl` を未処理分のみで上書き
3. atomic 化のため `.new` で書いてから `mv -f`

```python
import json, shutil
from pathlib import Path

LOG = Path.home() / ".claude" / "logs" / "permission-requests.jsonl"
REVIEWED = Path.home() / ".claude" / "logs" / "permission-requests-reviewed.jsonl"

# processed_entries は (entry_dict, action_label) のリスト
# pending_entries は次回送りの entry_dict のリスト

with REVIEWED.open("a", encoding="utf-8") as f:
    for entry, action in processed_entries:
        entry["_reviewed_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        entry["_action"] = action
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

tmp = LOG.with_suffix(".jsonl.new")
with tmp.open("w", encoding="utf-8") as f:
    for entry in pending_entries:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
shutil.move(str(tmp), str(LOG))
```

### Step 7: 完了報告

処理結果を 1 画面に要約:

```
レビュー完了

allowlist 追加: 3 件
  - Bash(gh pr view:*)
  - Bash(./vendor/bin/sail artisan:*)
  - mcp__laravel-boost__database-query

skill 化: 1 件
  - sail-artisan-recipe (雛形: ~/repos/dotclaude/skills/global/sail-artisan-recipe/SKILL.md)

hook 化: 0 件
スクリプト化: 0 件
都度確認継続: 2 件
次回送り: 1 件

settings.local.json バックアップ: ~/.claude/settings.local.json.bak.20260526145501
```

## エラーハンドリング

- `permission-requests.jsonl` が空 → 「未レビュー件数: 0」で終了
- JSON パース失敗行はスキップして警告のみ
- 既存 settings.local.json のバックアップに失敗したら処理中止 (allow 追加はやらない)。新規作成パスはバックアップ対象外なので本ルールは適用されない
- 既存 settings.local.json が壊れた JSON で `json.loads` が例外を投げたら、上書きせず処理中止してユーザーに報告 (空ファイルは `text.strip()` ガードで `{}` 起点として扱う)
- 雛形ファイル作成時、既存があれば timestamp suffix で別ファイル化し、その旨を表示
