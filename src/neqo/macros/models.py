from dataclasses import dataclass, field
from typing import Any


class _Missing:
    pass


MISSING = _Missing()


@dataclass(frozen=True)
class Parameter:
    type: str = "string"
    default: Any = MISSING


@dataclass(frozen=True)
class Macro:
    name: str
    sql: str
    params: dict[str, Parameter] = field(default_factory=dict)
    description: str = ""

    @property
    def signature(self) -> str:
        args = [
            name if param.default is MISSING else f"{name}={param.default!r}"
            for name, param in self.params.items()
        ]
        return f"{self.name}({', '.join(args)})"
