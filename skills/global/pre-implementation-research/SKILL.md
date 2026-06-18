---
name: pre-implementation-research
description: |
  機能実装・改修・バグ修正に着手する直前。コードを書き始める前。
  特にデータベースのテーブル・カラムを扱う実装の前は必須。
---

# 実装前リサーチ

## DB スキーマは実 DB から取得する

リポジトリ内のスキーマダンプ（`./schema/` のような事前生成ファイル）は
古くなっている可能性が高い。最新の確実な情報は実 DB にしかない。

例（フレームワーク・DB ごとに読み替え）:

### MySQL

```bash
# DB クライアントで直接（最も汎用的）
mysql -u <user> -p -e "SHOW CREATE TABLE <table_name>;" <database>
mysql -u <user> -p -e "DESCRIBE <table_name>;" <database>

# コンテナ越しに叩く場合の一例（Laravel Sail）
./vendor/bin/sail mysql -e "SHOW CREATE TABLE <table_name>;"
```

### PostgreSQL

```bash
psql -d <database> -c "\d+ <table_name>"
```

### SQL Server

```bash
# INFORMATION_SCHEMA はベンダ非依存。任意のクライアントから同じ SQL を実行できる
# 認証は統合認証 -E（Windows）を第一候補に。Linux/Docker では -U <user> のみ指定し
# パスワードはプロンプト入力させる。-P <password> の CLI 平文渡しはシェル履歴・ps に露出するため避ける
sqlcmd -S <server> -d <database> -E -Q "
  SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_NAME = '<table_name>';
"
```

ORM/フレームワークによっては DB クライアントを直接持たず、アプリ経由でスキーマを
ワンショット取得するほうが楽な場合もある（例: Laravel なら `artisan tinker`、
Rails なら `rails runner`。`INFORMATION_SCHEMA` は任意の SQL クライアントから実行可）。
Laravel + laravel-boost MCP を使っているなら `mcp__laravel-boost__database-schema`
/ `database-query` がより便利。

## 関連仕様書の確認

`docs/` 配下に該当する仕様書がある場合は事前に確認する。
仕様書の内容を再調査しない（仕様書に書かれていない場合のみ追加調査）。

## 既存実装の確認（コード discovery は serena 優先）

Serena MCP で関連シンボルを探索:
- `mcp__serena__find_symbol` で対象クラス・メソッドを探す
- `mcp__serena__find_referencing_symbols` で呼び出し元を確認
- 既存パターンを把握してから新規実装を始める

`grep` / `find` / `cat` でのコード探索は **serena に置き換える**。
（user-level の `~/.claude/hooks/serena-enforcer.py` がこれを誘導する）

## リサーチが済んだら test-first で実装する

スキーマ・仕様書・既存実装の把握が済み、いよいよ機能を実装するときは、
**いきなり本番コードを書き始めず test-first で進める**。テストフレームワークのある
プロジェクトでは、先に失敗するテストを書いて RED を観測してから実装する。

具体的な手順（RED→GREEN→REFACTOR、「全削除」絶対ルールは不採用など）は
`tdd` skill に従う。設定・インフラ・自明な変更には強制しない（適用範囲は `tdd` skill 参照）。
