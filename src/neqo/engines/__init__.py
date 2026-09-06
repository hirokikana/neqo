from collections.abc import Callable
from typing import Any

from neqo.engines.base import Engine
from neqo.errors import ConfigError

_factories: dict[str, Callable[..., Engine]] = {}
_dialects: dict[str, str | None] = {"athena": "trino", "duckdb": "duckdb"}


def register_engine(
    name: str, factory: Callable[..., Engine], *, replace: bool = False, dialect: str | None = None
) -> None:
    if not replace and (name in _factories or name in {"athena", "duckdb"}):
        raise ConfigError(f"Engine already registered: {name}")
    _factories[name] = factory
    _dialects[name] = dialect


def engine_dialect(name: str) -> str | None:
    if name not in _dialects:
        raise ConfigError(f"Unknown engine: {name}")
    return _dialects[name]


def create_engine(name: str, **options: Any) -> Engine:
    if name in _factories:
        return _factories[name](**options)
    if name == "duckdb":
        from neqo.engines.duckdb import DuckDBEngine

        return DuckDBEngine(**options)
    if name == "athena":
        from neqo.engines.athena import AthenaEngine

        return AthenaEngine(**options)
    raise ConfigError(f"Unknown engine: {name}")


__all__ = ["Engine", "create_engine", "register_engine"]
