from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import sqlglot
from jinja2 import StrictUndefined, TemplateError, nodes
from jinja2.sandbox import SandboxedEnvironment
from sqlglot import exp
from sqlglot.errors import TokenError
from sqlglot.tokens import TokenType

from neqo.errors import MacroError
from neqo.macros.models import MISSING, Macro, Parameter


def sql_parameter(value: Any, parameter: Parameter, dialect: str) -> str:
    kind = parameter.type
    if kind == "identifier":
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", value
        ):
            raise MacroError("Identifiers must contain dot-separated SQL names")
        return ".".join(
            exp.Identifier(this=p, quoted=True).sql(dialect=dialect) for p in value.split(".")
        )
    if kind == "integer":
        if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value)):
            raise MacroError("Expected an integer parameter")
        return str(int(value))
    if kind == "float":
        if isinstance(value, bool):
            raise MacroError("Expected a finite numeric parameter")
        try:
            number = float(value)
        except (ValueError, TypeError) as exc:
            raise MacroError("Expected a finite numeric parameter") from exc
        if not math.isfinite(number):
            raise MacroError("Expected a finite numeric parameter")
        return str(number)
    if kind == "boolean":
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.upper()
        raise MacroError("Expected true or false")
    if kind == "date":
        try:
            parsed = date.fromisoformat(str(value))
        except ValueError as exc:
            raise MacroError("Expected an ISO date (YYYY-MM-DD)") from exc
        return f"DATE '{parsed.isoformat()}'"
    if kind != "string":
        raise MacroError(f"Unsupported parameter type: {kind}")
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise MacroError("Expected a string parameter")
    if "\x00" in str(value):
        raise MacroError("NUL characters are not allowed")
    return exp.Literal.string(str(value)).sql(dialect=dialect)


class MacroRenderer:
    """Typed substitution only; arbitrary Jinja expressions are intentionally rejected."""

    def __init__(self) -> None:
        self.environment = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)

    def render(self, macro: Macro, values: dict[str, Any], dialect: str) -> str:
        extra = values.keys() - macro.params.keys()
        if extra:
            raise MacroError(f"Unknown parameters: {', '.join(sorted(extra))}")
        converted = {}
        for name, parameter in macro.params.items():
            value = values.get(name, parameter.default)
            if value is MISSING:
                raise MacroError(f"Missing parameter: {name}")
            converted[name] = sql_parameter(value, parameter, dialect)
        try:
            tree = self.environment.parse(macro.sql)
            for node in tree.find_all(nodes.Node):
                if not isinstance(node, (nodes.Output, nodes.TemplateData, nodes.Name)):
                    raise MacroError("Only {{ parameter }} substitutions are supported")
            template = self.environment.from_string(macro.sql)
            markers = {name: "neqo_parameter_" + uuid4().hex for name in converted}
            probe = template.render(markers)
            tokens = sqlglot.tokenize(probe, read=dialect)
            for marker in markers.values():
                occurrences = probe.count(marker)
                standalone = sum(t.text == marker and t.token_type == TokenType.VAR for t in tokens)
                if standalone != occurrences:
                    raise MacroError("Placeholders must be standalone, unquoted SQL tokens")
            return template.render(converted)
        except (TemplateError, TokenError) as exc:
            raise MacroError("Invalid macro template or undeclared parameter") from exc
