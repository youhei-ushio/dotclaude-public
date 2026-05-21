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
# Laravel Sail の場合
./vendor/bin/sail mysql -e "SHOW CREATE TABLE <table_name>;"
./vendor/bin/sail mysql -e "DESCRIBE <table_name>;"

# または Tinker 経由
./vendor/bin/sail artisan tinker --execute="
  print_r(DB::select('SHOW CREATE TABLE <table_name>'));
"

# Sail を使っていない環境
mysql -u <user> -p -e "SHOW CREATE TABLE <table_name>;" <database>
```

### PostgreSQL

```bash
psql -d <database> -c "\d+ <table_name>"
```

### SQL Server

```bash
# 例: 別 DB を Laravel から参照しているケース（コネクション名で指定）
./vendor/bin/sail artisan tinker --execute="
  print_r(DB::connection('<connection-name>')->select(\"
    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = '<table_name>'
  \"));
"
```

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
