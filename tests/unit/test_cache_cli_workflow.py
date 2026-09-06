import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from neqo import Runner
from neqo.catalog.cache import MetadataCache
from neqo.cli.main import app
from neqo.errors import ConfigError
from neqo.macros import Macro, MacroRegistry
from neqo.workflows import Workflow, WorkflowStep


def test_cache_disk_ttl_refresh_corruption(tmp_path):
    loader = Mock(return_value=["logs"])
    cache = MetadataCache("test", directory=tmp_path)
    assert cache.get("tables", loader) == ["logs"]
    assert MetadataCache("test", directory=tmp_path).get("tables", loader) == ["logs"]
    loader.assert_called_once()
    assert MetadataCache("other", directory=tmp_path).get("tables", loader) == ["logs"]
    assert loader.call_count == 2
    cache.clear()
    cache.get("tables", loader)
    assert loader.call_count == 3
    MetadataCache("test", directory=tmp_path, ttl=0).get("tables", loader)
    assert loader.call_count == 4
    for file in cache.path.glob("*.json"):
        file.write_text("broken")
    MetadataCache("test", directory=tmp_path).get("tables", loader)
    assert loader.call_count == 5


def test_cli_help_query_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli = CliRunner()
    assert cli.invoke(app, ["--help"]).exit_code == 0
    result = cli.invoke(app, ["query", "SELECT 42 AS answer", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["rows"] == [[42]]
    assert cli.invoke(app, ["query", "SELECT missing"]).exit_code == 1
    assert cli.invoke(app, ["--profile", "missing", "query", "SELECT 1"]).exit_code == 1


def test_cli_macro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "macros").mkdir()
    (tmp_path / "macros/investigate_request.sql").write_text("SELECT {{ request_id }} AS id")
    cli = CliRunner()
    result = cli.invoke(app, ["run", "investigate-request", "--request-id", "abc123", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["rows"] == [["abc123"]]
    assert cli.invoke(app, ["run", "investigate_request"]).exit_code == 1
    assert cli.invoke(app, ["run", "investigate_request", "--request-id"]).exit_code == 2


def test_workflow_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = MacroRegistry()
    registry.register(Macro("one", "SELECT 1"))
    with Runner(engine="duckdb", macros=registry) as runner:
        workflow = Workflow({"local": runner})
        assert workflow.run([WorkflowStep("local", "one", "result")])["result"].rows == [(1,)]
        with pytest.raises(ConfigError):
            workflow.run([WorkflowStep("local", "one", "x"), WorkflowStep("local", "one", "x")])
