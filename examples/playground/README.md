# NEQO playground

補完と macro を試すための、固定の合成データを使ったローカル環境です。
AWS 接続は不要です。実際の個人情報・認証情報は含みません。

## 起動

プロジェクトルートから実行します。

```bash
uv sync --locked
source .venv/bin/activate
python examples/playground/build_demo.py
cd examples/playground
neqo --no-history duckdb
```

`demo.duckdb` がすでにあれば生成コマンドは上書きせず終了します。
生成された DB は Git やインストール済みパッケージには含まれません。
新しい checkout では上記の生成コマンドを実行してください。

DB はファイルに永続化されます。REPL 内で加えた変更も残ります。
再生成するときは REPL を終了し、既存 DB を別名へ移してから生成してください。
`setup.sql` は空の DB 用です。

## データ

| スキーマ | テーブル・ビュー | 内容 |
| --- | --- | --- |
| main | access_logs | 6,000 件、18 カラムのアクセスログ |
| main | access_logs_archive | 2,000 件の過去ログ |
| main | access_errors | サービス名を JOIN したエラービュー |
| commerce | customers / products | 顧客 100 件、商品 30 件 |
| commerce | orders / order_items / payments | 注文 300 件、明細 600 件、決済 300 件 |
| ops | services / service_metrics | サービス 4 件、メトリクス 500 件 |
| audit | deployments | デプロイ履歴 20 件 |
| analytics | daily_service_health / order_summary | 集計ビュー |

日付は `2026-09-03` から `2026-09-05`。ログには JSON の `attributes`、
配列の `tags`、STRUCT の `client`、NULL を含むエラー情報があります。
設定上の表示上限は 100 行です。

## Tab 補完

以下の `<Tab>` は文字として入力せず、Tab キーを押してください。
SQL を実行するときは末尾に `;` を付けます。
補完候補を表示している間の Enter は候補の確定です。候補が閉じた状態で
Enter を押すと、SQL を実行するか、未完成の SQL を次の行へ続けます。

```text
SELECT * FROM access_<Tab>
  access_logs / access_logs_archive / access_errors

SELECT * FROM commerce.or<Tab>
  orders / order_items

SELECT * FROM access_logs WHERE request_<Tab>
  request_id / request_timestamp / request_method / request_path / request_time

SELECT * FROM access_logs l WHERE l.err<Tab>
  error_code / error_message

SELECT * FROM commerce.orders o
JOIN commerce.customers c ON o.customer_id = c.customer_id
WHERE c.acc<Tab>
  account_tier

SELECT * FROM analytics.da<Tab>
  daily_service_health

SELECT error_cl<Tab>
  error_class (DuckDB native macro)

invest<Tab>
  investigate_request (NEQO macro の候補。SQL としての実行は不可)
```

複雑な CTE の派生カラム、入れ子の SELECT のスコープ、STRUCT フィールドの
補完は v0.1 では保証しません。これらの型を含むテーブルの通常カラムは補完対象です。

```text
:tables
:schema main.access_logs
:schema commerce.orders
:macros
:refresh
:quit
```

## Macro の実行

REPL を `:quit` で終了してから、同じ `examples/playground` ディレクトリの
シェルで実行してください。別プロセスが同じ DuckDB を開いているとロック競合します。

```bash
neqo run errors
neqo run errors --date 2026-09-05 --status 400 --limit 5
neqo run slow-requests --threshold 4.5 --limit 5
neqo run investigate-request --request-id req-000042
neqo run customer-orders --customer-id 43
neqo run service-health --date 2026-09-05
neqo run preview-table --table analytics.order_summary --limit 3
neqo run preview-table --table ops.services --limit 4 --json
```

CSV 出力と、実行しない SQL 展開も同じディレクトリで試せます。

```bash
neqo query 'SELECT * FROM access_logs' --csv logs.csv
neqo run errors --limit 5 --csv errors.csv
neqo render errors --date 2026-09-05
neqo render errors --date 2026-09-05 --output errors.sql
```

`logs.csv` は表示上限の 100 行ではなく全 6,000 行を含みます。
`render` は DB 接続もクエリ実行もしないため、REPL で DB を開いていても使えます。
CSV と SQL の出力先に既存ファイルがある場合は、成功時に置き換えます。

6 個の macro はすべて引数なしでも試せるよう、デフォルト値を設定しています。
`preview_table` は identifier 型、それ以外は string / date / integer / float 型の例です。
同じ名前の既存サンプル macro は、このディレクトリの設定には混ざりません。

DuckDB native macro は REPL 内で直接実行できます。

```sql
SELECT status, error_class(status), count(*)
FROM access_logs GROUP BY status ORDER BY status;

SELECT request_id, client.browser, tags, attributes
FROM access_logs LIMIT 3;
```

## Python

プロジェクトルートから使用する場合の設定パスです。

```python
from neqo import Runner
from neqo.completion import CompletionEngine

with Runner(config="examples/playground/neqo.yaml") as runner:
    print(runner.run("investigate_request", request_id="req-000042").to_json())
    sql = "SELECT l. FROM access_logs l"
    completion = CompletionEngine(runner.engine, runner.macros)
    for item in completion.complete(sql, len("SELECT l.")):
        print(item.value, item.kind, item.signature)
```
