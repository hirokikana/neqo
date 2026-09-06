from collections.abc import Iterator

from neqo.errors import MacroError
from neqo.macros.models import Macro


class MacroRegistry:
    def __init__(self) -> None:
        self._macros: dict[str, Macro] = {}

    @staticmethod
    def normalize(name: str) -> str:
        return name.replace("-", "_")

    def register(self, macro: Macro) -> None:
        key = self.normalize(macro.name)
        if key in self._macros:
            raise MacroError(f"Duplicate macro: {macro.name}")
        self._macros[key] = macro

    def get(self, name: str) -> Macro:
        try:
            return self._macros[self.normalize(name)]
        except KeyError as exc:
            raise MacroError(f"Unknown macro: {name}") from exc

    def __iter__(self) -> Iterator[Macro]:
        return iter(self._macros.values())
