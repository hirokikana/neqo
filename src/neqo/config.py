from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from neqo.errors import ConfigError


@dataclass
class Config:
    base: Path = field(default_factory=Path.cwd)
    default_engine: str = "duckdb"
    engines: dict[str, dict[str, Any]] = field(default_factory=dict)
    macros: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        location = Path(path) if path is not None else Path.cwd() / "neqo.yaml"
        if not location.exists() and path is None:
            return cls()
        try:
            data = yaml.safe_load(location.read_text(encoding="utf-8"))
            if data is None:
                data = {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"Cannot load config: {location}") from exc
        if not isinstance(data, dict) or data.keys() - {"default_engine", "engines", "macros"}:
            raise ConfigError("Config must contain only default_engine, engines and macros")
        for key in ("engines", "macros"):
            if not isinstance(data.get(key, {}), dict):
                raise ConfigError(f"{key} must be a mapping")
        if not isinstance(data.get("default_engine", "duckdb"), str):
            raise ConfigError("default_engine must be a connection profile or engine name")
        for name, options in data.get("engines", {}).items():
            if not isinstance(options, dict) or not isinstance(options.get("type"), str):
                raise ConfigError(f"Connection profile {name} requires a type")
            if any(
                k in options
                for k in (
                    "aws_access_key_id",
                    "aws_secret_access_key",
                    "aws_session_token",
                    "password",
                )
            ):
                raise ConfigError("Use the engine's standard credential provider")
        return cls(base=location.resolve().parent, **data)

    def connection(self, engine: str | None, profile: str | None) -> tuple[str, dict[str, Any]]:
        selected = profile or engine or self.default_engine
        if (
            not profile
            and engine
            and engine not in self.engines
            and self.engines.get(self.default_engine, {}).get("type") == engine
        ):
            selected = self.default_engine
        if profile and profile not in self.engines:
            raise ConfigError(f"Unknown connection profile: {profile}")
        options = dict(self.engines.get(selected, {}))
        kind = options.pop("type", selected)
        if profile and engine and engine not in {kind, profile}:
            raise ConfigError("Requested engine does not match the connection profile")
        if kind == "duckdb" and "database" in options and options["database"] != ":memory:":
            options["database"] = str(self.base / options["database"])
        return kind, options
