from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from neqo.catalog import ColumnInfo, FunctionInfo, TableInfo
from neqo.engines.base import Engine
from neqo.errors import ConfigError, QueryError
from neqo.result import QueryHandle, QueryResult, QueryState


class DuckDBEngine(Engine):
    name = "duckdb"
    dialect = "duckdb"

    def __init__(
        self,
        database: str = ":memory:",
        *,
        max_rows: int = 10000,
        retained_results: int = 32,
        read_only: bool = False,
    ):
        try:
            import duckdb
        except ImportError as exc:
            raise ConfigError("Install DuckDB support: pip install 'neqo[duckdb]'") from exc
        if max_rows < 1 or retained_results < 1:
            raise ConfigError("max_rows and retained_results must be positive")
        self.database = database
        self.max_rows = max_rows
        self.retained_results = retained_results
        self.connection = duckdb.connect(database, read_only=read_only)
        self._results: OrderedDict[str, QueryResult] = OrderedDict()

    def execute(self, sql: str) -> QueryResult:
        try:
            cursor = self.connection.execute(sql)
            columns = [c[0] for c in (cursor.description or [])]
            rows = cursor.fetchmany(self.max_rows + 1)
        except Exception as exc:
            raise QueryError("DuckDB query failed; check SQL and database objects") from exc
        return QueryResult(
            columns,
            rows[: self.max_rows],
            {
                "state": QueryState.SUCCEEDED,
                "truncated": len(rows) > self.max_rows,
            },
        )

    def execute_iter(self, sql: str) -> Iterator[QueryResult]:
        """Yield all rows in bounded batches; consume before reusing this connection."""
        try:
            cursor = self.connection.execute(sql)
            columns = [c[0] for c in (cursor.description or [])]
            while True:
                rows = cursor.fetchmany(1000)
                yield QueryResult(
                    columns, rows, {"state": QueryState.SUCCEEDED, "truncated": False}
                )
                if len(rows) < 1000:
                    break
        except Exception as exc:
            raise QueryError("DuckDB query failed; check SQL and database objects") from exc

    def submit(self, sql: str) -> QueryHandle:
        result = self.execute(sql)
        query_id = str(uuid4())
        result.metadata["query_id"] = query_id
        self._results[query_id] = result
        if len(self._results) > self.retained_results:
            self._results.popitem(last=False)
        return QueryHandle(query_id, self.name)

    def status(self, query_id: str) -> QueryState:
        self.result(query_id)
        return QueryState.SUCCEEDED

    def result(self, query_id: str) -> QueryResult:
        try:
            return self._results[query_id]
        except KeyError as exc:
            raise QueryError("Unknown or expired DuckDB query handle", query_id) from exc

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        return self.connection.execute(sql, params or []).fetchall()

    def databases(self) -> list[str]:
        return [r[0] for r in self._rows("SELECT database_name FROM duckdb_databases()")]

    def schemas(self) -> list[str]:
        return [
            r[0] for r in self._rows("SELECT DISTINCT schema_name FROM duckdb_schemas() ORDER BY 1")
        ]

    def tables(self) -> list[TableInfo]:
        return [
            TableInfo(name, schema, catalog, "view" if kind == "VIEW" else "table")
            for catalog, schema, name, kind in self._rows(
                "SELECT table_catalog, table_schema, table_name, table_type "
                "FROM information_schema.tables ORDER BY 1, 2, 3"
            )
        ]

    def columns(self, table: str) -> list[ColumnInfo]:
        from sqlglot import exp, parse_one

        try:
            parsed = parse_one(table, read="duckdb", into=exp.Table)
            parts = [p.name for p in parsed.parts]
        except Exception as exc:
            raise ConfigError("Invalid table identifier") from exc
        predicates = ["table_name = ?"]
        params = [parts[-1]]
        for field, value in zip(
            ["table_schema", "table_catalog"], reversed(parts[:-1]), strict=False
        ):
            predicates.append(f"{field} = ?")
            params.append(value)
        rows = self._rows(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE "
            + " AND ".join(predicates)
            + " ORDER BY ordinal_position",
            params,
        )
        return [ColumnInfo(n, t, nullable == "YES") for n, t, nullable in rows]

    def functions(self) -> list[FunctionInfo]:
        return [
            FunctionInfo(
                n, f"{n}({', '.join(p or [])})", "macro" if "macro" in kind else "function"
            )
            for n, p, kind in self._rows(
                "SELECT function_name, parameters, function_type FROM duckdb_functions()"
            )
        ]

    def native_complete(self, sql: str) -> list[tuple[str, int]]:
        # Only use an already loaded extension: completion must never install code.
        loaded = self._rows(
            "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'autocomplete'"
        )
        if not loaded or not loaded[0][0]:
            return []
        return self._rows("SELECT suggestion, suggestion_start FROM sql_auto_complete(?)", [sql])

    def close(self) -> None:
        self.connection.close()
