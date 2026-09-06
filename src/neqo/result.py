from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID


class QueryState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class QueryHandle:
    query_id: str
    engine: str


def _json_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_value({"columns": self.columns, "rows": self.rows, "metadata": self.metadata})

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    def to_csv(self, destination: str | Path | TextIO) -> int:
        from neqo.export import write_csv

        return write_csv([self], destination)
