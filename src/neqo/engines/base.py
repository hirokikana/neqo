from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from neqo.catalog import ColumnInfo, FunctionInfo, TableInfo
from neqo.result import QueryHandle, QueryResult, QueryState


class Engine(ABC):
    """Engine extension contract. Instances need not support concurrent use."""

    name: str
    dialect: str

    @abstractmethod
    def execute(self, sql: str) -> QueryResult: ...

    def execute_iter(self, sql: str) -> Iterator[QueryResult]:
        """Execute once and yield result batches. Adapters may override for full streaming."""
        yield self.execute(sql)

    @abstractmethod
    def submit(self, sql: str) -> QueryHandle: ...

    @abstractmethod
    def status(self, query_id: str) -> QueryState: ...

    @abstractmethod
    def result(self, query_id: str) -> QueryResult: ...

    def iter_results(self, query_id: str) -> Iterator[QueryResult]:
        yield self.result(query_id)

    @abstractmethod
    def databases(self) -> list[str]: ...

    @abstractmethod
    def schemas(self) -> list[str]: ...

    @abstractmethod
    def tables(self) -> list[TableInfo]: ...

    @abstractmethod
    def columns(self, table: str) -> list[ColumnInfo]: ...

    @abstractmethod
    def functions(self) -> list[FunctionInfo]: ...

    def native_complete(self, sql: str) -> list[tuple[str, int]]:
        return []

    def register_macro(self, name: str, sql: str) -> None:
        raise NotImplementedError("Native macro registration is not supported")

    def refresh(self) -> None:
        """Invalidate cached metadata."""
        return None

    def close(self) -> None:
        """Release engine resources."""
        return None

    def __enter__(self) -> Engine:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
