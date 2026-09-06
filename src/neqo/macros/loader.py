from pathlib import Path
from typing import Any

from jinja2 import Environment, TemplateError, meta

from neqo.errors import ConfigError
from neqo.macros.models import MISSING, Macro, Parameter
from neqo.macros.registry import MacroRegistry


def load_macros(config: dict[str, Any], base: Path) -> MacroRegistry:
    registry = MacroRegistry()
    directory = base / config.get("path", "macros")
    definitions = {k: v for k, v in config.items() if k != "path"}
    if directory.is_dir():
        for path in sorted(directory.glob("*.sql")):
            definitions.setdefault(path.stem, {"file": str(path.resolve())})
    for name, definition in definitions.items():
        if not isinstance(definition, dict) or "file" not in definition:
            raise ConfigError(f"Macro {name} requires a file")
        try:
            sql = (base / definition["file"]).read_text(encoding="utf-8")
            variables = meta.find_undeclared_variables(Environment().parse(sql))
        except (OSError, ValueError, TemplateError) as exc:
            raise ConfigError(f"Cannot load macro: {name}") from exc
        raw_params = definition.get("params", {})
        if not isinstance(raw_params, dict) or any(
            not isinstance(p, dict) for p in raw_params.values()
        ):
            raise ConfigError(f"Invalid parameters for macro: {name}")
        params = {
            key: Parameter(value.get("type", "string"), value.get("default", MISSING))
            for key, value in raw_params.items()
        }
        for variable in sorted(variables):
            params.setdefault(variable, Parameter())
        registry.register(Macro(name, sql, params, definition.get("description", "")))
    return registry
