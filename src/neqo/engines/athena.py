from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from neqo.catalog import ColumnInfo, FunctionInfo, TableInfo
from neqo.catalog.cache import MetadataCache
from neqo.engines.base import Engine
from neqo.errors import ConfigError, QueryError
from neqo.result import QueryHandle, QueryResult, QueryState


class AthenaEngine(Engine):
    name = "athena"
    dialect = "trino"

    def __init__(
        self,
        database: str = "default",
        *,
        catalog: str = "AwsDataCatalog",
        workgroup: str = "primary",
        region: str | None = None,
        output_location: str | None = None,
        aws_profile: str | None = None,
        max_rows: int = 10000,
        poll_interval: float = 1.0,
        timeout: float = 300,
        cache_dir: str | Path | None = None,
        cache_ttl: float = 300,
        client: Any = None,
    ):
        if max_rows < 1 or poll_interval <= 0 or timeout <= 0 or cache_ttl < 0:
            raise ConfigError("Invalid row limit, polling interval, timeout or cache TTL")
        self._session = None
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ConfigError("Install Athena support: pip install 'neqo[athena]'") from exc
            self._session = boto3.Session(profile_name=aws_profile, region_name=region)
            client = self._session.client("athena")
        self.client = client
        self.database, self.catalog, self.workgroup = database, catalog, workgroup
        self.output_location = output_location
        self.max_rows, self.poll_interval, self.timeout = max_rows, poll_interval, timeout
        self._cache_options = {"directory": cache_dir, "ttl": cache_ttl}
        self._cache: MetadataCache | None = None
        self._region = region or getattr(getattr(client, "meta", None), "region_name", None)

    @property
    def cache(self) -> MetadataCache:
        if self._cache is None:
            identity = str(uuid4())
            if self._session is not None:
                sts = self._session.client("sts")
                try:
                    identity = sts.get_caller_identity()["Arn"]
                finally:
                    sts.close()
            namespace = json.dumps(
                [str(self._region), identity, self.catalog, self.database, self.workgroup]
            )
            self._cache = MetadataCache(namespace, **self._cache_options)
        return self._cache

    def submit(self, sql: str) -> QueryHandle:
        request = {
            "QueryString": sql,
            "WorkGroup": self.workgroup,
            "QueryExecutionContext": {"Database": self.database, "Catalog": self.catalog},
        }
        if self.output_location:
            request["ResultConfiguration"] = {"OutputLocation": self.output_location}
        response = self.client.start_query_execution(**request)
        return QueryHandle(response["QueryExecutionId"], self.name)

    def _execution(self, query_id: str) -> dict[str, Any]:
        return self.client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]

    def status(self, query_id: str) -> QueryState:
        return QueryState(self._execution(query_id)["Status"]["State"])

    def execute(self, sql: str) -> QueryResult:
        handle = self.submit(sql)
        self._wait(handle.query_id)
        return self.result(handle.query_id)

    def execute_iter(self, sql: str) -> Iterator[QueryResult]:
        handle = self.submit(sql)
        self._wait(handle.query_id)
        yield from self.iter_results(handle.query_id)

    def _wait(self, query_id: str) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            state = self.status(query_id)
            if state == QueryState.SUCCEEDED:
                return
            if state in {QueryState.FAILED, QueryState.CANCELLED}:
                raise QueryError(f"Athena query {state.lower()}", query_id)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise QueryError("Athena wait timed out; query continues remotely", query_id)
            time.sleep(min(self.poll_interval, remaining))

    def cancel(self, query_id: str) -> None:
        self.client.stop_query_execution(QueryExecutionId=query_id)

    @staticmethod
    def _value(value: str | None, kind: str) -> Any:
        if value is None:
            return None
        if kind in {"tinyint", "smallint", "integer", "int", "bigint"}:
            return int(value)
        if kind in {"float", "real", "double"}:
            return float(value)
        if kind.startswith("decimal"):
            return Decimal(value)
        if kind == "boolean":
            return value.lower() == "true"
        if kind == "date":
            return date.fromisoformat(value)
        if kind == "timestamp":
            return datetime.fromisoformat(value)
        return value

    def iter_results(self, query_id: str) -> Iterator[QueryResult]:
        execution = self._execution(query_id)
        state = execution["Status"]["State"]
        if state != QueryState.SUCCEEDED:
            raise QueryError(f"Athena result unavailable: {state}", query_id)
        statistics = execution.get("Statistics", {})
        metadata = {
            "query_id": query_id,
            "state": state,
            "scanned_bytes": statistics.get("DataScannedInBytes", 0),
            "execution_time_ms": statistics.get("EngineExecutionTimeInMillis", 0),
            "output_location": execution.get("ResultConfiguration", {}).get("OutputLocation"),
        }
        token = None
        first = True
        while True:
            request = {"QueryExecutionId": query_id, "MaxResults": 1000}
            if token:
                request["NextToken"] = token
            response = self.client.get_query_results(**request)
            result_set = response.get("ResultSet", {})
            info = result_set.get("ResultSetMetadata", {}).get("ColumnInfo", [])
            names = [c.get("Label", c["Name"]) for c in info]
            rows = result_set.get("Rows", [])
            # SELECT can include UpdateCount=0; identify its first-page header by names.
            if first and rows:
                header = [c.get("VarCharValue") for c in rows[0].get("Data", [])]
                if header in (names, [c["Name"] for c in info]):
                    rows = rows[1:]
            converted = []
            for row in rows:
                cells = row.get("Data", [])
                converted.append(
                    tuple(
                        self._value(
                            cells[i].get("VarCharValue") if i < len(cells) else None, column["Type"]
                        )
                        for i, column in enumerate(info)
                    )
                )
            token = response.get("NextToken")
            yield QueryResult(
                names,
                converted,
                metadata
                | {
                    "next_token": token,
                    "update_count": response.get("UpdateCount"),
                    "truncated": False,
                },
            )
            if not token:
                break
            first = False

    def result(self, query_id: str) -> QueryResult:
        result = QueryResult([], [])
        for page in self.iter_results(query_id):
            remaining = self.max_rows - len(result.rows)
            result.columns, result.metadata = page.columns, dict(page.metadata)
            result.rows.extend(page.rows[:remaining])
            if len(page.rows) > remaining or (
                len(result.rows) == self.max_rows and page.metadata.get("next_token")
            ):
                result.metadata["truncated"] = True
                break
        return result

    def _list(self, method: str, key: str, **kwargs: Any) -> list[dict[str, Any]]:
        output = []
        while True:
            response = getattr(self.client, method)(**kwargs)
            output.extend(response.get(key, []))
            token = response.get("NextToken")
            if not token:
                return output
            kwargs["NextToken"] = token

    def databases(self) -> list[str]:
        return self.cache.get(
            "databases",
            lambda: [
                d["Name"]
                for d in self._list(
                    "list_databases",
                    "DatabaseList",
                    CatalogName=self.catalog,
                    WorkGroup=self.workgroup,
                )
            ],
        )

    def schemas(self) -> list[str]:
        return self.databases()

    def _table_metadata(self) -> list[dict[str, Any]]:
        def load():
            return [
                {
                    "Name": t["Name"],
                    "TableType": t.get("TableType", ""),
                    "Columns": t.get("Columns", []),
                    "PartitionKeys": t.get("PartitionKeys", []),
                }
                for t in self._list(
                    "list_table_metadata",
                    "TableMetadataList",
                    CatalogName=self.catalog,
                    DatabaseName=self.database,
                    WorkGroup=self.workgroup,
                )
            ]

        return self.cache.get("tables", load)

    def tables(self) -> list[TableInfo]:
        return [
            TableInfo(
                t["Name"],
                self.database,
                self.catalog,
                "view" if t["TableType"] == "VIRTUAL_VIEW" else "table",
            )
            for t in self._table_metadata()
        ]

    def columns(self, table: str) -> list[ColumnInfo]:
        from sqlglot import exp, parse_one

        parsed = parse_one(table, read=self.dialect, into=exp.Table)
        schema, catalog = parsed.db or self.database, parsed.catalog or self.catalog
        if schema == self.database and catalog == self.catalog:
            for item in self._table_metadata():
                if item["Name"] == parsed.name:
                    return [
                        ColumnInfo(c["Name"], c.get("Type", ""))
                        for c in item["Columns"] + item["PartitionKeys"]
                    ]

        def load():
            item = self.client.get_table_metadata(
                CatalogName=catalog,
                DatabaseName=schema,
                TableName=parsed.name,
                WorkGroup=self.workgroup,
            )["TableMetadata"]
            return item.get("Columns", []) + item.get("PartitionKeys", [])

        columns = self.cache.get(f"columns:{catalog}.{schema}.{parsed.name}", load)
        return [ColumnInfo(c["Name"], c.get("Type", "")) for c in columns]

    def functions(self) -> list[FunctionInfo]:
        return [
            FunctionInfo(name, f"{name}(...)")
            for name in (
                "count",
                "sum",
                "avg",
                "min",
                "max",
                "coalesce",
                "date_trunc",
                "approx_distinct",
                "json_extract",
                "json_extract_scalar",
                "regexp_like",
                "cast",
                "try_cast",
            )
        ]

    def refresh(self) -> None:
        self.cache.clear()

    def close(self) -> None:
        if self._session is not None:
            self.client.close()
