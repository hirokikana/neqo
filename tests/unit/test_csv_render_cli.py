import csv
import io
import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from neqo import Runner
from neqo.cli.main import app


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "macros").mkdir()
    (tmp_path / "macros/lookup.sql").write_text("SELECT {{ name }} AS name")
    (tmp_path / "neqo.yaml").write_text(
        "default_engine: local\nengines:\n"
        "  local: {type: duckdb, database: demo.duckdb, max_rows: 1}\n"
        "  remote: {type: athena, database: analytics}\n"
        "macros:\n  path: macros\n"
    )
    return tmp_path


def test_csv_query_bypasses_display_cap(project):
    result = CliRunner().invoke(app, ["query", "SELECT * FROM range(2501)", "--csv", "out.csv"])
    assert result.exit_code == 0, result.output
    rows = list(csv.reader((project / "out.csv").open(newline="")))
    assert len(rows) == 2502
    assert rows[-1] == ["2500"]
    assert result.stdout == ""
    assert "2501 rows" in result.stderr


def test_csv_macro_stdout(project):
    result = CliRunner().invoke(app, ["run", "lookup", "--name", 'a,"b"\nc', "--csv", "-"])
    assert result.exit_code == 0, result.output
    assert list(csv.reader(io.StringIO(result.stdout))) == [["name"], ['a,"b"\nc']]
    assert result.stderr == ""


def test_incompatible_flags_do_not_execute(project):
    result = CliRunner().invoke(app, ["query", "SELECT 1", "--csv", "out.csv", "--json"])
    assert result.exit_code == 2
    assert not (project / "demo.duckdb").exists()
    assert not (project / "out.csv").exists()


@pytest.mark.parametrize("profile", ["local", "remote"])
def test_render_is_offline(project, monkeypatch, profile):
    factory = Mock(side_effect=AssertionError("Must not construct an engine"))
    monkeypatch.setattr("neqo.runner.create_engine", factory)
    result = CliRunner().invoke(
        app, ["--profile", profile, "render", "lookup", "--name", "O'Reilly"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "SELECT 'O''Reilly' AS name"
    assert not (project / "demo.duckdb").exists()
    with Runner(profile=profile) as runner:
        assert runner.render("lookup", name="abc") == "SELECT 'abc' AS name"
    factory.assert_not_called()


def test_render_file_and_validation(project):
    cli = CliRunner()
    result = cli.invoke(app, ["render", "lookup", "--name=abc", "-o", "lookup.sql"])
    assert result.exit_code == 0, result.output
    assert (project / "lookup.sql").read_text() == "SELECT 'abc' AS name\n"
    result = cli.invoke(app, ["render", "lookup", "-o", "lookup.sql"])
    assert result.exit_code == 1
    assert (project / "lookup.sql").read_text() == "SELECT 'abc' AS name\n"
    assert not (project / "demo.duckdb").exists()


def test_existing_json_option(project):
    result = CliRunner().invoke(app, ["query", "SELECT 1", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["rows"] == [[1]]
