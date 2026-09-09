from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from neqo.errors import ConfigError


def _layers(location: Path, ancestors: tuple[Path, ...] = ()) -> list[tuple[Path, dict[str, Any]]]:
    location = location.expanduser().resolve()
    if location in ancestors:
        raise ConfigError(f"Circular config import: {location}")
    if len(ancestors) >= 16:
        raise ConfigError("Config imports exceed maximum depth of 16")
    try:
        data = yaml.safe_load(location.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot load config: {location}") from exc
    data = {} if data is None else data
    if not isinstance(data, dict) or data.keys() - {
        "default_engine",
        "engines",
        "macros",
        "imports",
    }:
        raise ConfigError("Config must contain only default_engine, engines, macros and imports")
    for key in ("engines", "macros"):
        if not isinstance(data.get(key, {}), dict):
            raise ConfigError(f"{key} must be a mapping")
    if "default_engine" in data and not isinstance(data["default_engine"], str):
        raise ConfigError("default_engine must be a connection profile or engine name")
    imports = data.pop("imports", [])
    if not isinstance(imports, list):
        raise ConfigError("imports must be a list of paths or {path, optional} mappings")
    layers = [(location.parent, data)]
    for entry in imports:
        optional = False
        if isinstance(entry, dict):
            if entry.keys() - {"path", "optional"} or not isinstance(
                entry.get("optional", False), bool
            ):
                raise ConfigError("Invalid config import; expected path and optional boolean")
            optional = entry.get("optional", False)
            entry = entry.get("path")
        if not isinstance(entry, str) or not entry:
            raise ConfigError("Config import path must be a nonempty string")
        target = location.parent / Path(entry).expanduser()
        if optional:
            try:
                target.stat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ConfigError(f"Cannot access config: {target}") from exc
        layers.extend(_layers(target, (*ancestors, location)))
        if len(layers) > 128:
            raise ConfigError("Config imports exceed maximum of 128 files")
    return layers


def _macro_definitions(raw: dict[str, Any], base: Path) -> dict[str, Any]:
    directory = raw.get("path", "macros")
    if not isinstance(directory, str):
        raise ConfigError("macros.path must be a directory path")
    directory = base / Path(directory).expanduser()
    definitions: dict[str, Any] = {
        p.stem: {"file": str(p.resolve())} for p in sorted(directory.glob("*.sql")) if p.is_file()
    }
    for name, definition in raw.items():
        if name == "path":
            continue
        if (
            not isinstance(name, str)
            or not isinstance(definition, dict)
            or not isinstance(definition.get("file"), str)
        ):
            raise ConfigError("Each macro requires a name and file path")
        definitions[name] = definition | {"file": str(base / Path(definition["file"]).expanduser())}
    return definitions


@dataclass
class Config:
    base: Path = field(default_factory=Path.cwd)
    default_engine: str = "duckdb"
    engines: dict[str, dict[str, Any]] = field(default_factory=dict)
    macros: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        location = Path(path).expanduser() if path is not None else Path.cwd() / "neqo.yaml"
        if not location.exists() and path is None:
            return cls()
        data: dict[str, Any] = {"engines": {}, "macros": {}}
        for index, (base, layer) in enumerate(_layers(location)):
            if "default_engine" in layer:
                data["default_engine"] = layer["default_engine"]
            for name, options in layer.get("engines", {}).items():
                if not isinstance(name, str) or not isinstance(options, dict):
                    raise ConfigError("Connection profiles must be named mappings")
                if set(options) & {
                    "aws_access_key_id",
                    "aws_secret_access_key",
                    "aws_session_token",
                    "password",
                }:
                    raise ConfigError("Use the engine's standard credential provider")
                previous = data["engines"].get(name, {})
                if "type" in options and options["type"] != previous.get("type"):
                    previous = {}
                merged = previous | options
                if "database" in options and merged.get("type") == "duckdb":
                    database = options["database"]
                    if not isinstance(database, str):
                        raise ConfigError("DuckDB database must be a path or :memory:")
                    if database != ":memory:":
                        merged["database"] = str(base / Path(database).expanduser())
                data["engines"][name] = merged
            if index == 0 or "macros" in layer:
                data["macros"].update(_macro_definitions(layer.get("macros", {}), base))
            if "path" in layer.get("macros", {}):
                data["macros"]["path"] = str(base / Path(layer["macros"]["path"]).expanduser())
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
