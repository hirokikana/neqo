from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, TextIO

from neqo.config import Config
from neqo.engines import Engine, create_engine, engine_dialect
from neqo.export import write_csv
from neqo.macros import MacroRegistry, MacroRenderer
from neqo.macros.loader import load_macros
from neqo.result import QueryHandle, QueryResult, QueryState


class Runner:
    def __init__(
        self,
        engine: str | Engine | None = None,
        *,
        config: str | Path | Config | None = None,
        profile: str | None = None,
        macros: MacroRegistry | None = None,
        **options: Any,
    ):
        settings = config if isinstance(config, Config) else Config.load(config)
        self.macros = macros if macros is not None else load_macros(settings.macros, settings.base)
        self.renderer = MacroRenderer()
        self._owns_engine = not isinstance(engine, Engine)
        self._engine: Engine | None = None
        if isinstance(engine, Engine):
            self._engine = engine
            self._dialect = engine.dialect
        else:
            name, configured = settings.connection(engine, profile)
            self._engine_name = name
            self._engine_options = configured | options
            self._dialect = engine_dialect(name)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(self._engine_name, **self._engine_options)
        return self._engine

    def render(self, macro: str, **parameters: Any) -> str:
        dialect = self._dialect or self.engine.dialect
        return self.renderer.render(self.macros.get(macro), parameters, dialect)

    def execute(self, sql: str) -> QueryResult:
        return self.engine.execute(sql)

    def execute_iter(self, sql: str) -> Iterator[QueryResult]:
        return self.engine.execute_iter(sql)

    def export_csv(
        self, sql: str, destination: str | Path | TextIO, *, include_header: bool = True
    ) -> int:
        return write_csv(self.execute_iter(sql), destination, include_header=include_header)

    def run(self, macro: str, **parameters: Any) -> QueryResult:
        return self.execute(self.render(macro, **parameters))

    def submit(self, macro: str, **parameters: Any) -> QueryHandle:
        return self.engine.submit(self.render(macro, **parameters))

    def submit_sql(self, sql: str) -> QueryHandle:
        return self.engine.submit(sql)

    def status(self, query_id: str) -> QueryState:
        return self.engine.status(query_id)

    def result(self, query_id: str) -> QueryResult:
        return self.engine.result(query_id)

    def close(self) -> None:
        if self._owns_engine and self._engine is not None:
            self._engine.close()

    def __enter__(self) -> Runner:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
