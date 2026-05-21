---
name: route-management
description: |
  Laravel のルートを追加・変更・削除するとき。
  routes/web.php を編集しようとしているとき。
  Route::get, Route::post 等を書く前に必ず確認。
---

# ルート追加の絶対ルール

DDD / モジュラーモノリス的に `app/Contexts/<ContextName>/` で機能を区切る
Laravel プロジェクトを想定したルール。プロジェクト構造が違う場合は配置先を
読み替える。

## routes/web.php に直書きしない

`routes/web.php` への直接編集は禁止。
ルートは必ず Context (機能ドメイン) の `ServiceProvider` に書く。

理由: ルート定義が `web.php` に集中するとファイルが肥大化し、機能境界が
不明瞭になる。Context ごとに `ServiceProvider` で `$this->loadRoutesFrom()`
または `Route::group(...)` で登録すると、機能とルートが同じディレクトリに
収まる。

## 配置場所の決定

例:

- `app/Contexts/<ContextName>/ServiceProvider.php`
- バージョニングするなら `app/Contexts/v3/<ContextName>/ServiceProvider.php`
  のように切る（自プロジェクトの方針に合わせる）

新規 Context の `ServiceProvider` は `config/app.php` の `providers` 配列に
登録する。

## 記述パターン

```php
public function boot(): void
{
    Route::middleware(['web'])->prefix('/<context-prefix>')->group(function () {
        Route::middleware(['auth'])->group(function () {
            Route::get('/<resource>/<action>', Presentation\View\<Action>::class)
                ->name('<context>.<resource>.<action>');
        });
    });
}
```

## 既存ルートの確認

新規追加前に必ず該当 `ServiceProvider.php` で既存のルート構造を確認する。
重複や命名衝突を避ける。

## 違反時の対応

`routes/web.php` を誤って編集してしまった場合:
1. 即座に元の状態に戻す（または該当行を削除）
2. 適切な Context の `ServiceProvider` に移動

「動いているから大丈夫」は理由にならない。
