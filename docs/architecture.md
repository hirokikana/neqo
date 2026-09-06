# Architecture and v0.1 boundaries

NEQO is a query orchestration library with a terminal adapter. Imports of `neqo`
do not import Typer, Rich, prompt_toolkit, boto3 or DuckDB. Drivers load only when
their engine is constructed. CLI dependencies are installed with the base
distribution for `uv tool install` usability but are not part of core execution.

```text
Application / Lambda / CLI / REPL
                |
              Runner
         /      |      \
   Registry  Renderer  Engine
                       /  \
                  DuckDB  Athena

CompletionEngine -> SQL context + Engine catalog + MacroRegistry
Athena catalog -> identity-scoped MetadataCache -> Athena metadata APIs
```

## Public contracts

- `Engine`: execution, handles, status, results, metadata and lifecycle. Implement
  the abstract methods and expose `name` and a SQLGlot `dialect`.
- `register_engine(name, factory)`: register a custom engine factory; accidental
  replacement is rejected unless `replace=True` is explicit.
  Supply `dialect="..."` to support rendering without constructing the custom engine.
  Otherwise rendering falls back to the custom engine's `dialect` property.
- `Runner`: configuration selection, rendering and delegation. `run` and `submit`
  accept macro names; `execute` and `submit_sql` accept SQL. No SQL/name guessing.
  Engine construction is lazy, so built-in macro rendering is entirely offline.
  `execute_iter` yields result batches; `export_csv` consumes them into a file or stream.
- `MacroRegistry`: explicit registration and normalized lookup; duplicates fail.
- `MacroRenderer`: typed literal/identifier substitution, shared by CLI and Python.
- `QueryResult`: ordered column names, tuple rows and extensible metadata.
- `CompletionEngine.complete(sql, cursor_position)`: presentation-independent
  candidates with kind, signature and replacement offset relative to the cursor.

`Engine.register_macro` is a capability hook which defaults to unsupported.
SQL invocation expansion should be a separate SQLGlot AST transformation, not a
regular-expression rewrite of arbitrary SQL. Future dialect-specific compilation
must retain the same registry and parameter validation contracts.

## Execution and resource limits

Athena query IDs are remote, durable service identifiers; no local handle table is
needed for Lambda / Step Functions. Failure and cancellation are terminal states;
nonterminal results raise `QueryError`. Blocking execution has a deadline but does
not cancel implicitly. Boto3's SDK retries remain authoritative for service calls.
The wait deadline cannot preempt a blocking SDK request; configure deployment
network timeouts and Lambda budgets accordingly.

DuckDB uses one connection with synchronous execution. Its handle store is bounded
and process-local. Results are row-bounded in both engines, and Athena supports
page iteration. `execute_iter` supports full batch iteration on both initial engines;
DuckDB iterators must be consumed before reusing their connection. CSV export uses
Python's CSV writer, rejects truncated pages, and publishes filesystem output using
atomic replacement on success. Custom engines may override `execute_iter`; the base
implementation yields `execute`, and export rejects any truncated result it returns.
General Arrow/Parquet streaming is deferred. Native DuckDB execution errors and boto3 errors remain chained or
propagated for application debugging; CLI output suppresses raw payloads.

The metadata cache is best-effort, uses atomic replacement and excludes query
text and credentials. It is not a distributed cache or a concurrent invalidation
protocol. `:refresh` invalidates the current process and on-disk namespace; other
running processes may retain their own entries until TTL expiry. Cold metadata
completion may wait on a network request; subsequent completion uses cached data.

## Macro trust boundary

Parameters are data. Integer/float/boolean/date parameters are parsed, strings are
SQL literals, and identifiers use a restrictive grammar. Arbitrary expressions,
Jinja control flow, filters and attribute access are not part of the v0.1 format.
Templates remain trusted SQL, including any permissions or destructive operations
they contain. Identifier parameters permit choosing objects; applications must
apply their own allowlist when callers should only access specific tables.

## Workflow foundation

`Workflow(runners).run(steps)` executes explicitly named macros sequentially and
returns outputs keyed by step name. It validates all engine names, output names
and macro arguments before executing any step. It does not offer transactions
across engines, retries, dependencies or implicit result transfer. A failure stops
later steps; already completed statements are not rolled back.

```python
from neqo.workflows import Workflow, WorkflowStep

workflow = Workflow({"local": runner})
results = workflow.run(
    [
        WorkflowStep("local", "errors", "errors_today", {"date": "2026-09-05"}),
    ]
)
```

For Athena -> DuckDB, add a typed artifact contract (URI, format, schema, ownership)
and explicit import/export capabilities. Avoid transporting a large QueryResult
through JSON or implicitly downloading all of an S3 output. Arrow and Parquet are
natural transfer formats. No `--pipe` flag is advertised before this exists.

## Next steps

1. Real AWS integration testing across SELECT, CTAS, DML and federated catalogs.
2. More precise completion scopes, quoted identifiers and CTE-derived columns.
3. Arrow/Parquet streaming and native macro compilation.
4. Typed file artifacts for explicit Athena-to-DuckDB transfer.
5. Third-party engine entry points and optional Harlequin/editor integrations.

NEQO should remain a small execution and macro layer, rather than grow a SQL IDE
or a distributed scheduler. The library APIs allow separate integrations.
