import json
import subprocess
import sys
from datetime import date
from decimal import Decimal

import pytest

from neqo.config import Config
from neqo.engines import create_engine, register_engine
from neqo.errors import ConfigError
from neqo.result import QueryResult


def test_configuration(tmp_path):
    path = tmp_path / "neqo.yaml"
    path.write_text(
        "default_engine: local\nengines:\n  local:\n    type: duckdb\n    database: a.duckdb\n"
    )
    config = Config.load(path)
    assert config.connection(None, None) == ("duckdb", {"database": str(tmp_path / "a.duckdb")})
    with pytest.raises(ConfigError):
        config.connection(None, "missing")


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "engines: []",
        "default_engine: 5",
        "extra: true",
        "engines: {bad: {type: athena, aws_secret_access_key: secret}}",
        "engines: {x: {}}",
    ],
)
def test_invalid_config(tmp_path, content):
    path = tmp_path / "neqo.yaml"
    path.write_text(content)
    with pytest.raises(ConfigError):
        Config.load(path)


def test_missing_explicit_config(tmp_path):
    with pytest.raises(ConfigError):
        Config.load(tmp_path / "none.yaml")


def test_registry():
    with pytest.raises(ConfigError):
        create_engine("missing")
    with pytest.raises(ConfigError):
        register_engine("duckdb", lambda: None)
    sentinel = object()
    register_engine("test-custom", lambda **options: sentinel, replace=True)
    assert create_engine("test-custom") is sentinel


def test_result_json():
    result = QueryResult(["d", "n", "b", "n"], [(date(2026, 9, 5), Decimal("1.20"), b"hi", None)])
    output = result.to_dict()
    assert output["rows"] == [["2026-09-05", "1.20", "aGk=", None]]
    assert json.loads(result.to_json()) == output


def test_core_import_isolation():
    code = (
        "import neqo, sys; "
        "assert not set(['typer', 'rich', 'prompt_toolkit', 'boto3', 'duckdb']) "
        "& sys.modules.keys()"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_default_profile_applies_to_named_engine():
    config = Config(
        default_engine="prod",
        engines={
            "prod": {
                "type": "athena",
                "database": "analytics",
            }
        },
    )
    assert config.connection("athena", None) == ("athena", {"database": "analytics"})
    with pytest.raises(ConfigError, match="does not match"):
        config.connection("duckdb", "prod")


def test_nonfinite_results_are_json():
    result = QueryResult(["n"], [(float("nan"),), (float("inf"),)])
    assert json.loads(result.to_json(allow_nan=False))["rows"] == [["nan"], ["inf"]]
