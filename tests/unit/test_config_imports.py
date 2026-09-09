from pathlib import Path

import pytest
import yaml

from neqo import Runner
from neqo.config import Config
from neqo.errors import ConfigError
from neqo.macros.loader import load_macros


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))
    return path


def test_import_merge_and_relative_paths(tmp_path):
    root = write(
        tmp_path / "neqo.yaml",
        {
            "default_engine": "shared",
            "engines": {
                "shared": {"type": "athena", "database": "analytics", "region": "us-east-1"}
            },
            "macros": {"path": "shared_macros"},
            "imports": ["personal/settings.yaml"],
        },
    )
    (tmp_path / "shared_macros").mkdir()
    (tmp_path / "shared_macros/shared.sql").write_text("SELECT 1")
    (tmp_path / "shared_macros/unchanged.sql").write_text("SELECT 4")
    write(
        tmp_path / "personal/settings.yaml",
        {
            "default_engine": "local",
            "engines": {
                "shared": {"aws_profile": "personal"},
                "local": {"type": "duckdb", "database": "data.duckdb"},
            },
            "macros": {"path": "queries", "private": {"file": "private.sql"}},
        },
    )
    (tmp_path / "personal/queries").mkdir()
    (tmp_path / "personal/queries/shared.sql").write_text("SELECT 2")
    (tmp_path / "personal/private.sql").write_text("SELECT 3")
    config = Config.load(root)
    assert config.default_engine == "local"
    assert config.engines["shared"]["database"] == "analytics"
    assert config.engines["shared"]["aws_profile"] == "personal"
    assert config.connection(None, None)[1]["database"] == str(tmp_path / "personal/data.duckdb")
    with Runner(config=root, engine="duckdb", database=":memory:") as runner:
        assert runner.run("shared").rows == [(2,)]
        assert runner.run("private").rows == [(3,)]
        assert runner.run("unchanged").rows == [(4,)]


def test_import_depth_limit(tmp_path):
    for index in range(17):
        write(tmp_path / f"{index}.yaml", {"imports": [f"{index + 1}.yaml"]})
    with pytest.raises(ConfigError, match="maximum depth"):
        Config.load(tmp_path / "0.yaml")


def test_optional_permission_error_is_not_ignored(tmp_path, monkeypatch):
    root = write(tmp_path / "neqo.yaml", {"imports": [{"path": "private.yaml", "optional": True}]})
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path.name == "private.yaml":
            raise PermissionError("not readable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(ConfigError, match="Cannot access"):
        Config.load(root)


def test_order_nested_imports_and_optional(tmp_path):
    root = write(
        tmp_path / "neqo.yaml",
        {
            "default_engine": "root",
            "imports": ["a.yaml", {"path": "missing.yaml", "optional": True}, "b.yaml"],
        },
    )
    write(tmp_path / "a.yaml", {"default_engine": "a", "imports": ["nested.yaml"]})
    write(tmp_path / "nested.yaml", {"default_engine": "nested"})
    write(tmp_path / "b.yaml", {"default_engine": "b"})
    assert Config.load(root).default_engine == "b"


def test_connection_only_import_keeps_explicit_macro(tmp_path):
    (tmp_path / "macros").mkdir()
    (tmp_path / "macros/report.sql").write_text("SELECT 1")
    (tmp_path / "chosen.sql").write_text("SELECT 2")
    root = write(
        tmp_path / "neqo.yaml",
        {"macros": {"report": {"file": "chosen.sql"}}, "imports": ["local.yaml"]},
    )
    write(tmp_path / "local.yaml", {"default_engine": "duckdb"})
    with Runner(config=root) as runner:
        assert runner.run("report").rows == [(2,)]


def test_macro_replaced_as_whole(tmp_path):
    (tmp_path / "old.sql").write_text("SELECT {{ old }}")
    (tmp_path / "new.sql").write_text("SELECT 2")
    root = write(
        tmp_path / "neqo.yaml",
        {
            "macros": {"m": {"file": "old.sql", "params": {"old": {"type": "integer"}}}},
            "imports": ["local.yaml"],
        },
    )
    write(tmp_path / "local.yaml", {"macros": {"m": {"file": "new.sql"}}})
    config = Config.load(root)
    assert "params" not in config.macros["m"]
    assert len(list(load_macros(config.macros, config.base))) == 1


@pytest.mark.parametrize(
    "imports",
    ["local.yaml", [1], [{}], [{"path": "x", "optional": "yes"}], [{"path": "x", "unknown": True}]],
)
def test_invalid_imports(tmp_path, imports):
    root = write(tmp_path / "neqo.yaml", {"imports": imports})
    with pytest.raises(ConfigError):
        Config.load(root)


def test_cycle_and_missing(tmp_path):
    root = write(tmp_path / "neqo.yaml", {"imports": ["local.yaml"]})
    with pytest.raises(ConfigError, match="Cannot load"):
        Config.load(root)
    write(tmp_path / "local.yaml", {"imports": ["neqo.yaml"]})
    with pytest.raises(ConfigError, match="Circular"):
        Config.load(root)


def test_optional_invalid_file_is_not_ignored(tmp_path):
    root = write(tmp_path / "neqo.yaml", {"imports": [{"path": "local.yaml", "optional": True}]})
    write(
        tmp_path / "local.yaml",
        {"engines": {"bad": {"type": "athena", "aws_secret_access_key": "secret"}}},
    )
    with pytest.raises(ConfigError, match="credential"):
        Config.load(root)


def test_type_change_replaces_profile(tmp_path):
    root = write(
        tmp_path / "neqo.yaml",
        {
            "engines": {"main": {"type": "athena", "workgroup": "primary"}},
            "imports": ["local.yaml"],
        },
    )
    write(
        tmp_path / "local.yaml", {"engines": {"main": {"type": "duckdb", "database": ":memory:"}}}
    )
    assert Config.load(root).connection(None, "main") == ("duckdb", {"database": ":memory:"})
