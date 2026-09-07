# NEQO

**Nimble Engine Query Orchestrator**

A lightweight, unified query and macro layer for Athena, DuckDB, and beyond.

Pronounced "neko". Python 3.11+. MIT licensed. Version 0.1 is an early API: expect
changes before 1.0.

NEQO brings Athena and DuckDB behind a Python API, with reusable SQL macros,
context-aware autocomplete, and a CLI / REPL. Its core can run in applications
and AWS Lambda without importing the CLI. Engines and completion are extensible.

It is intended for ad-hoc analysis, operational investigation and reusable team
queries. It is not a terminal SQL IDE or a dbt replacement.

## Quick start

Install DuckDB support for a local query session:

```bash
pip install 'neqo[duckdb]'
neqo --engine duckdb query 'SELECT 42 AS answer'
neqo --no-history duckdb ./analytics.duckdb
```

For both engines, use `pip install 'neqo[all]'`, or install the CLI with uv:

```bash
uv tool install 'neqo[all]'
```

`pip install neqo` installs the library and CLI but no engine drivers. Choose
`neqo[duckdb]`, `neqo[athena]`, or `neqo[all]` for query execution. With no
`neqo.yaml` in the current directory, the default engine is in-memory DuckDB.

To develop NEQO or try its sample data, clone the repository:

```bash
git clone https://github.com/hirokikana/neqo.git
cd neqo
uv sync --locked
uv run neqo --help
uv run neqo query 'SELECT 42 AS answer'
```

Or `pip install -e '.[all]'` in a virtual environment. Engine drivers are optional;
install `neqo[athena]` for an Athena-only deployment.

### Try macros and completion locally

From the repository root, generate synthetic data and run a macro:

```bash
uv run python examples/playground/build_demo.py
uv run neqo --config examples/playground/neqo.yaml run errors --limit 5
uv run neqo --config examples/playground/neqo.yaml render errors --date 2026-09-05
uv run neqo --config examples/playground/neqo.yaml --no-history duckdb
```

In the REPL, enter `SELECT * FROM access_` and press Tab. Use `:quit` to close
the database before running another CLI process against it. The playground has
6,000 access logs, five schemas, views and six macros; its generated database is
not included in Git or the installed wheel. See the
[playground guide](https://github.com/hirokikana/neqo/blob/main/examples/playground/README.md).

## Configuration

CLI commands and Runner read `neqo.yaml` from the current working directory by
default. The following is a template for your own connection settings; the
`errors` macro also requires the SQL file shown in the next section.

```yaml
default_engine: local
engines:
  local:
    type: duckdb
    database: ./analytics.duckdb
    max_rows: 10000
  athena-prod:
    type: athena
    database: analytics
    catalog: AwsDataCatalog
    workgroup: primary
    region: ap-northeast-1
    # aws_profile: prod  # omit in Lambda; use its execution role
    # output_location: s3://your-query-results/prefix/
    cache_ttl: 300
    timeout: 300
macros:
  path: ./macros
  errors:
    file: macros/errors.sql
    params:
      date: {type: date}
      status: {type: integer, default: 500}
```

`default_engine` accepts a connection profile name or a registered engine name.
`--profile` selects a configured connection. `--engine` selects an engine or
connection by name. Explicit Python keyword arguments override connection
options. Relative macro paths and configured DuckDB database paths resolve from
the YAML file's directory. An explicit `database=` resolves from the process
working directory. Use `--config PATH` / `Runner(config=PATH)` for deterministic
configuration discovery. No parent-directory search takes place.

### Athena authentication

NEQO connection profiles and AWS credential profiles are separate:

| Setting | Purpose | Example |
| --- | --- | --- |
| `--profile` | Select an entry under `engines` in `neqo.yaml` | `athena-prod` |
| `aws_profile` in that entry, or `AWS_PROFILE` | Select the boto3/AWS authentication profile | `company-prod` |

For an AWS profile previously configured with `aws configure sso`:

```bash
pip install 'neqo[athena]'
aws sso login --profile company-prod
AWS_PROFILE=company-prod neqo --profile athena-prod query 'SELECT 1'
AWS_PROFILE=company-prod neqo --profile athena-prod --no-history athena
```

Alternatively, add `aws_profile: company-prod` to the `athena-prod` connection
above. After SSO login, `neqo --profile athena-prod ...` then uses that profile
without an `AWS_PROFILE` prefix. An explicit `aws_profile` takes precedence over
the environment selection. Do not put access keys or session tokens in the YAML.

Athena needs a region, query/catalog permissions, and access to the S3 query-result
location. Configure `output_location` in NEQO or configure it in the workgroup;
enforced workgroup settings take precedence. This S3 location is separate from
the local file written by `--csv`. For Lambda, EC2 and ECS, omit `aws_profile` to
use the execution/instance/task role through boto3's credential provider chain.

Keep personal connection settings in the repository-root `neqo.yaml` (ignored by
Git), or use `--config neqo.local.yaml`. Files under `examples/` are public samples.

## SQL macros

`macros/errors.sql`:

```sql
SELECT * FROM access_logs
WHERE dt = {{ date }} AND status >= {{ status }}
```

YAML keeps parameter schemas and defaults separate from executable SQL, leaves
SQL files usable by editors, and permits connection configuration in one place.
Files under `macros.path` are discovered automatically; undeclared variables
default to string parameters. Hyphens and underscores in macro names are aliases.

Types: `string`, `integer`, `float`, `boolean`, `date`, `identifier`. Values are
validated and rendered as dialect-specific SQL literals. Identifiers accept
dot-separated ASCII names and quote each component. They cannot contain SQL
fragments. Required and unknown parameters raise errors. Use `--name=value` for
CLI values that begin with `--`; booleans require explicit `true` or `false`.
`--json`, `--csv` and `--no-header` are reserved for execution output;
`render` reserves `--output` / `-o`.

Templates support only `{{ parameter }}` substitution. Jinja control flow,
filters, function calls and attribute access are rejected. Do not surround a
placeholder with quotes: the renderer supplies them. SQL templates and raw SQL
are trusted executable code; review them just like Python code. Value escaping
does not make arbitrary third-party templates safe.

```python
from neqo import Runner
from neqo.macros import Macro, MacroRegistry, Parameter

macros = MacroRegistry()
macros.register(Macro("lookup", "SELECT {{ name }} AS name", {"name": Parameter()}))
with Runner(engine="duckdb", macros=macros) as runner:
    result = runner.run("lookup", name="O'Reilly")
    print(result.to_dict())
```

Both initial engines expand macros through this same renderer. Native DuckDB
macro compilation and SQL table-function macro invocation are future features.

### Render SQL without execution

```bash
neqo render errors --date 2026-09-05
neqo --profile athena-prod render errors --date 2026-09-05 --output errors.sql
```

`render` writes plain SQL to stdout, or UTF-8 SQL to `--output`. It uses the same
typed parameters, defaults and validation as `run`. For Athena and DuckDB it does
not create an engine, open a database, fetch AWS credentials, or submit a query.
The selected profile determines the SQL dialect. Python uses
`runner.render("errors", date="2026-09-05")` for the same behavior.

### Export CSV

```bash
AWS_PROFILE=prod neqo --profile athena-prod query 'SELECT * FROM access_logs' --csv logs.csv
AWS_PROFILE=prod neqo --profile athena-prod run errors --date 2026-09-05 --csv errors.csv
neqo query 'SELECT 42 AS answer' --csv -
neqo query 'SELECT 42 AS answer' --csv - --no-header
```

`--csv FILE` exports all result rows, including those beyond `max_rows`. Athena
submits the query once, waits for success, and fetches result pages sequentially.
DuckDB also exports in batches. The export has one header, UTF-8 encoding and
standard CSV quoting for commas, quotes and embedded newlines. NULL and empty
strings both produce empty fields. Dates use ISO strings, decimals keep precision,
bytes use base64, and DuckDB nested values use JSON cells.

Use `--csv -` for pure CSV on stdout. `--json` and `--csv` cannot be combined.
CSV records use LF (`\n`) line endings. Headers are included by default; add
`--no-header` to `query` or `run` to omit them (requires `--csv`). Newlines inside
cell values are preserved. Python callers can pass `include_header=False` to
`runner.export_csv`, `result.to_csv`, or `write_csv`. Open caller-owned text streams
with `newline=""` to avoid platform-specific newline translation.
File paths are relative to the current working directory; the parent directory
must exist. Existing files are replaced only after the export succeeds. On failure,
the temporary file is removed and any previous output is retained. Stdout and
caller-supplied streams cannot be rolled back and can contain partial output on failure.

```python
from neqo import Runner
from neqo.export import write_csv

with Runner(profile="athena-prod") as runner:
    count = runner.export_csv("SELECT * FROM access_logs", "logs.csv")
    sql = runner.render("errors", date="2026-09-05")
    runner.export_csv(sql, "errors.csv")
    # For an existing, successfully completed Athena query, without rerunning it:
    # write_csv(runner.engine.iter_results(query_id), "existing.csv")
```

`result.to_csv(path_or_stream)` exports a materialized `QueryResult`, but rejects
results marked as truncated. Use `runner.export_csv` for full query results.

## Python API

With an existing `access_logs` table and the `errors` macro configured as above:

```python
from neqo import Runner

with Runner(engine="duckdb", database="analytics.duckdb") as runner:
    result = runner.execute("SELECT count(*) FROM access_logs")
    errors = runner.run("errors", date="2026-09-05")
    print(result.to_json())
```

`Runner(engine=an_engine)` accepts an existing `Engine`; its owner is responsible
for closing it. A Runner that creates its own engine closes it on context exit.
Connection creation is lazy: rendering alone does not open a connection. Accessing
`runner.engine` or executing a query initializes it and may raise connection errors.
Instances are intended for sequential use, not shared concurrent execution.

`QueryResult` has `columns`, tuple `rows`, and `metadata`. `to_dict()` is JSON-ready:
dates use ISO strings, decimals use lossless strings, bytes use base64, and tuples
become lists. Nonfinite floats become strings (`nan`, `inf`, `-inf`) for valid JSON.
Duplicate column names are preserved. Athena complex values remain
strings; numeric, boolean, date and timestamp columns use Python values.

### Asynchronous Athena and Lambda

```python
from neqo import Runner

runner = Runner(engine="athena", database="analytics", config="/var/task/neqo.yaml")


def lambda_handler(event, context):
    handle = runner.submit("errors", date=event["date"])
    return {"query_id": handle.query_id, "engine": handle.engine}
```

Bundle the YAML and SQL files with the deployment, install `neqo[athena]`, and
grant the execution role Athena, catalog and result-bucket permissions. NEQO
does not store credentials. AWS_PROFILE, instance/task roles and Lambda execution
roles work through boto3. Use `/tmp/neqo-cache` for `cache_dir` in Lambda.

Another invocation can use `runner.status(query_id)` and `runner.result(query_id)`.
`runner.submit_sql(sql)` submits raw SQL. For short synchronous Lambda queries,
`return runner.run("errors", date=event["date"]).to_dict()` works; set Athena's
`timeout` below the Lambda time limit. A wait timeout raises `QueryError` with
`query_id` and leaves the remote query running. Explicit cancellation is available
through `runner.engine.cancel(query_id)` on Athena.

### Results and limits

Default materialization is capped at 10,000 rows and reports `metadata.truncated`.
This is a client memory bound, not a SQL limit or Athena scan-cost bound. Use
SQL `LIMIT` / predicates to control work. A single very large cell may still be
large. Athena `engine.iter_results(query_id)` yields pages of at most 1,000 API
rows without applying the materialization cap:

```python
for page in runner.engine.iter_results(query_id):
    consume(page)  # application-defined sink
```

Pages report query ID, scanned bytes, execution time, output location and state.
Restart page iteration from the query ID to retrieve the entire result; a
truncated materialized result's token is not a row-exact resume cursor.
`runner.execute_iter(sql)` executes a query and yields all result batches on either
initial engine; consume the iterator before reusing or closing its Runner.
DuckDB submit is synchronous; handles live in that engine instance and the most
recent 32 results are retained. DuckDB page iteration currently yields its bounded
materialized result; use `execute_iter` for a new query's full streamed result.

## REPL and completion

Terminate SQL with `;`. Suggestions appear automatically while typing. Select a
candidate with Tab or arrow keys; Enter accepts it without submitting the input.
Otherwise, Enter continues incomplete input; Ctrl-C clears input and
Ctrl-D exits. Tab offers keywords, tables/views, columns, functions and macros.
When no candidate is selected, Enter submits the current input unchanged, even
if suggestions are visible.
To complete a SELECT column, write the FROM clause first and move the cursor back,
for example `SELECT l. FROM access_logs l` with the cursor after `l.`. Without a
FROM clause, v0.1 does not search all tables for column names. NEQO macro candidates
are suggestions only: run them with `neqo run` in the shell, not `FROM macro(...)`.

| Command | Action |
| --- | --- |
| `:tables` | List tables and views |
| `:schema TABLE` | List columns |
| `:macros` | List macro signatures |
| `:refresh` | Invalidate metadata caches |
| `:engine` | Show engine |
| `:quit` | Exit |

```python
from neqo.completion import CompletionEngine

completion = CompletionEngine(runner.engine, runner.macros)
sql = "SELECT l. FROM access_logs l"
items = completion.complete(sql, len("SELECT l."))
# Completion(value=..., kind="column", signature=..., start_position=...)
```

Completion uses SQLGlot plus a token fallback for incomplete SQL. Alias handling
is best effort; nested scopes, CTE-derived columns and quoted partial identifiers
are not fully resolved in v0.1. DuckDB's `sql_auto_complete()` is used when its
autocomplete extension is already loaded; NEQO never installs extensions on Tab.

Athena metadata comes from Athena catalog APIs, including partition columns and
views. Disk cache defaults to `$XDG_CACHE_HOME/neqo` or `~/.cache/neqo` with a
300-second TTL. Namespaces include the STS caller ARN, region, catalog, database
and workgroup. STS identity is fetched lazily once on metadata access, never on
query submission. Injected test clients use isolated cache namespaces. Disk
write failures fall back to memory. Athena's function suggestions are a small
static list; there is no claim of a complete remote function catalog.

History is stored in `$XDG_DATA_HOME/neqo/history` or `~/.local/share/neqo/history`.
**Query history may contain sensitive values.** Use `neqo --no-history ...` to
disable persistence. Cached catalog names may also be sensitive. Protect cache
and history directories, and do not share them between trust boundaries.

`--verbose` enables only NEQO debug messages. NEQO does not log SQL, parameter
values, credentials or raw SDK exception payloads. Applications should take the
same care when logging exceptions from their own code.

## Development

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
uv run twine check dist/*
```

CI runs lint, tests and packaging on Python 3.11, 3.12 and 3.13. Unit tests use
mock Athena clients / botocore Stubber and never need AWS credentials. DuckDB
integration tests use an in-memory database. No live AWS test runs by default.

See [architecture](https://github.com/hirokikana/neqo/blob/main/docs/architecture.md)
for extension contracts, workflow boundaries and next steps, and
[contributing](https://github.com/hirokikana/neqo/blob/main/CONTRIBUTING.md) for contributions.
Maintainers can follow the
[release guide](https://github.com/hirokikana/neqo/blob/main/docs/releasing.md)
for PyPI publication through `release.yml` and the `pypi` GitHub environment.

## References

Engine integrations follow the official [Athena boto3 API](https://docs.aws.amazon.com/boto3/latest/reference/services/athena.html)
and [DuckDB autocomplete extension](https://duckdb.org/docs/current/core_extensions/autocomplete)
documentation.
