import logging
import time
from collections.abc import Callable
from typing import Any

from sqlglot.errors import TokenError

from neqo.completion.context import context_at
from neqo.completion.models import Completion
from neqo.engines.base import Engine
from neqo.macros import MacroRegistry

logger = logging.getLogger(__name__)
KEYWORDS = (
    "SELECT FROM WHERE JOIN LEFT RIGHT INNER OUTER ON GROUP BY ORDER LIMIT HAVING AS "
    "AND OR NOT NULL IS DISTINCT UNION ALL WITH INSERT INTO UPDATE DELETE CREATE TABLE "
    "VIEW COUNT SUM AVG"
).split()


class CompletionEngine:
    def __init__(self, engine: Engine, macros: MacroRegistry | None = None, *, ttl: float = 300):
        self.engine = engine
        self.macros = macros if macros is not None else MacroRegistry()
        self.ttl = ttl
        self._cache: dict[str, tuple[float, list]] = {}

    def _get(self, key: str, loader: Callable[[], list[Any]]) -> list[Any]:
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.ttl:
            return cached[1]
        value = loader()
        self._cache[key] = (time.monotonic(), value)
        return value

    def refresh(self) -> None:
        self._cache.clear()
        self.engine.refresh()

    def complete(self, sql: str, cursor_position: int) -> list[Completion]:
        if not 0 <= cursor_position <= len(sql):
            raise ValueError("cursor_position is outside SQL")
        try:
            context = context_at(sql, cursor_position, self.engine.dialect)
        except TokenError:
            # Unclosed quotes and comments are normal while entering SQL.
            return []
        start = -len(context.prefix)
        candidates = [Completion(m.name, "macro", m.signature, start) for m in self.macros]
        try:
            if context.table_context:
                tables = self._get("tables", self.engine.tables)
                candidates.extend(
                    Completion(t.name, t.kind, start_position=start)
                    for t in tables
                    if not context.qualifier or t.schema == context.qualifier
                )
            else:
                candidates.extend(Completion(k, "keyword", start_position=start) for k in KEYWORDS)
                tables = context.tables
                if context.qualifier:
                    tables = {context.qualifier: tables.get(context.qualifier, context.qualifier)}
                for table in tables.values():
                    columns = self._get("columns:" + table, lambda t=table: self.engine.columns(t))
                    candidates.extend(
                        Completion(c.name, "column", c.data_type, start) for c in columns
                    )
                if not context.qualifier:
                    functions = self._get("functions", self.engine.functions)
                    candidates.extend(
                        Completion(f.name, f.kind, f.signature, start) for f in functions
                    )
            if not context.qualifier:
                candidates.extend(
                    Completion(value, "native", start_position=offset - cursor_position)
                    for value, offset in self.engine.native_complete(sql[:cursor_position])
                )
        except Exception:
            # Metadata failure must not prevent SQL entry, and may contain credentials or SQL.
            logger.debug("Completion metadata unavailable")
        if context.qualifier and not context.table_context:
            candidates = [c for c in candidates if c.kind == "column"]
        unique = {}
        for candidate in candidates:
            if candidate.value.lower().startswith(context.prefix.lower()):
                unique.setdefault((candidate.value.lower(), candidate.kind), candidate)
        return sorted(unique.values(), key=lambda c: (c.value.lower(), c.kind))
