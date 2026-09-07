import io
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from rich.text import Text
from typer.testing import CliRunner

from neqo.cli.graphs import parse_graph_command
from neqo.cli.main import app
from neqo.cli.repl import repl
from neqo.graphs import GraphData, GraphError, GraphSpec, draw_graph, infer_graph
from neqo.result import QueryResult


@pytest.fixture(autouse=True)
def clean_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NO_COLOR", raising=False)


def result():
    return QueryResult(["city", "ok", "error"], [("東京", Decimal("12.5"), 2), ("Osaka", 0, 3)])


@pytest.mark.parametrize("kind", ["bar", "stacked"])
@pytest.mark.parametrize("color", [True, False])
def test_actual_termgraph(kind, color):
    output = io.StringIO()
    draw_graph(result(), GraphSpec(kind, "city", ("ok", "error")), stream=output, color=color)
    text = output.getvalue()
    assert "東京" in text and "Osaka" in text and "ok" in text and "error" in text
    assert ("\x1b[" in text) == color


@pytest.mark.parametrize("kind", ["bar", "stacked"])
@pytest.mark.parametrize("number", [0, 1000000])
def test_constant_values_respect_width(kind, number):
    output = io.StringIO()
    data = QueryResult(["x", "a", "b"], [("A", number, number)])
    draw_graph(data, GraphSpec(kind, "x", ("a", "b"), width=20), stream=output, color=True)
    lines = Text.from_ansi(output.getvalue()).plain.splitlines()[2:]
    assert all(line.count("▇") <= 20 for line in lines)


@pytest.mark.parametrize("value", [None, "12", True, -1, float("nan"), float("inf")])
def test_bad_values(value):
    with pytest.raises(GraphError):
        GraphData.from_result(
            QueryResult(["x", "y"], [("a", value)]), GraphSpec("bar", "x", ("y",))
        )


def test_validation():
    with pytest.raises(GraphError, match="truncated"):
        GraphData.from_result(
            QueryResult([], [], {"truncated": True}), GraphSpec("bar", "x", ("y",))
        )
    with pytest.raises(GraphError, match="unambiguous"):
        GraphData.from_result(result(), GraphSpec("bar", "city", ("missing",)))
    with pytest.raises(GraphError, match="color"):
        GraphSpec("stacked", "city", ("ok", "error"), ("green",))
    with pytest.raises(GraphError, match="width"):
        GraphSpec("bar", "x", ("y",), width=0)


def test_empty_and_no_color(monkeypatch):
    output = io.StringIO()
    spec = GraphSpec("bar", "city", ("ok",))
    draw_graph(QueryResult(["city", "ok"], []), spec, stream=output)
    assert output.getvalue() == "No rows to graph.\n"
    monkeypatch.setenv("NO_COLOR", "1")
    draw_graph(result(), spec, stream=output, color=True)
    assert "\x1b" not in output.getvalue()


def test_missing_optional_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "termgraph", None)
    with pytest.raises(GraphError, match="neqo\\[graphs\\]"):
        draw_graph(result(), GraphSpec("bar", "city", ("ok",)))


def test_labels_cannot_inject_terminal_controls():
    data = QueryResult(["x", "y"], [("a\x1b[31m\nb", 1)])
    output = io.StringIO()
    draw_graph(data, GraphSpec("bar", "x", ("y",)), stream=output, color=False)
    assert "\x1b" not in output.getvalue()
    assert "a [31m b" in output.getvalue()


def test_cli_and_invalid_options():
    sql = "SELECT 'Tokyo' AS city, 12 AS ok, 2 AS error"
    cli = CliRunner()
    output = cli.invoke(
        app,
        [
            "query",
            sql,
            "--graph",
            "stacked",
            "--x",
            "city",
            "--y",
            "ok",
            "--y",
            "error",
            "--no-color",
        ],
    )
    assert output.exit_code == 0, output.output
    assert "Tokyo" in output.stdout and "ok" in output.stdout
    for extra in [["--csv", "out.csv"], ["--json"], ["--colors", "invalid"]]:
        output = cli.invoke(
            app, ["query", sql, "--graph", "bar", "--x", "city", "--y", "ok", *extra]
        )
        assert output.exit_code == 2


def test_repl_reuses_result_and_recovers(monkeypatch, capsys):
    session = Mock()
    session.prompt.side_effect = [
        ":graph --help",
        ":graph bar --x city --y ok",
        "SELECT something;",
        ":graph bad",
        ":graph stacked --x city --y ok --y error --no-color",
        ":quit",
    ]
    monkeypatch.setattr("neqo.cli.repl.PromptSession", Mock(return_value=session))
    runner = Mock()
    runner.engine.name = "duckdb"
    runner.macros = []
    runner.execute.return_value = result()
    repl(runner, history=False)
    runner.execute.assert_called_once_with("SELECT something;")
    output = capsys.readouterr().out
    assert "Execute a query before :graph" in output
    assert "Invalid :graph arguments" in output
    assert "Monochrome" in output
    assert "automatic when omitted" in output


def test_meta_parser():
    spec, no_color = parse_graph_command('stacked --x "my day" --y ok --y error --colors green,red')
    assert spec.x == "my day" and spec.colors == ("green", "red") and not no_color
    with pytest.raises(GraphError):
        parse_graph_command("--help")


def test_auto_inference():
    spec = infer_graph(result())
    assert (spec.kind, spec.x, spec.y) == ("bar", "city", ("ok", "error"))
    spec = infer_graph(QueryResult(["year", "count"], [(2026, 12)]))
    assert spec.x == "year" and spec.y == ("count",)
    assert infer_graph(result(), GraphSpec(x="city", y=("error",))).y == ("error",)
    data = QueryResult(["city", "day", "count"], [("Tokyo", "Monday", 1)])
    with pytest.raises(GraphError, match="--x"):
        infer_graph(data)
    assert infer_graph(data, GraphSpec(x="day")).y == ("count",)
    output = io.StringIO()
    draw_graph(QueryResult([], []), GraphSpec(), stream=output)
    assert output.getvalue() == "No rows to graph.\n"


@pytest.mark.parametrize("extra", [["--json"], ["--csv", "x.csv"]])
def test_graph_incompatible_options(extra):
    output = CliRunner().invoke(app, ["query", "SELECT 1", "--graph", *extra])
    assert output.exit_code == 2


@pytest.mark.parametrize("flag", [["--graph"], ["--graph", "auto"], ["--graph=auto"]])
def test_auto_cli(flag):
    output = CliRunner().invoke(app, ["query", "SELECT 'Tokyo' AS city, 12 AS count", *flag])
    assert output.exit_code == 0, output.output
    assert "Tokyo" in output.stdout and "count" in output.stdout


def test_auto_macro_and_repl(monkeypatch, capsys):
    config = Path(__file__).resolve().parents[2] / "examples/graphs.yaml"
    output = CliRunner().invoke(app, ["--config", str(config), "run", "daily_status", "--graph"])
    assert output.exit_code == 0, output.output
    assert "success" in output.stdout and "2026-09-05" in output.stdout
    session = Mock()
    session.prompt.side_effect = ["SELECT data;", ":graph", ":quit"]
    monkeypatch.setattr("neqo.cli.repl.PromptSession", Mock(return_value=session))
    runner = Mock()
    runner.engine.name = "duckdb"
    runner.macros = []
    runner.execute.return_value = result()
    repl(runner, history=False)
    runner.execute.assert_called_once()
    assert "12.5" in capsys.readouterr().out


def test_example_macro():
    config = Path(__file__).resolve().parents[2] / "examples/graphs.yaml"
    output = CliRunner().invoke(
        app,
        [
            "--config",
            str(config),
            "run",
            "daily_status",
            "--graph",
            "stacked",
            "--x",
            "day",
            "--y",
            "success",
            "--y",
            "client_error",
            "--y",
            "server_error",
        ],
    )
    assert output.exit_code == 0, output.output
    assert "2026-09-05" in output.stdout


def test_plain_query_without_termgraph(monkeypatch):
    monkeypatch.setitem(sys.modules, "termgraph", None)
    output = CliRunner().invoke(app, ["query", "SELECT 42", "--json"])
    assert output.exit_code == 0, output.output


def test_data_order_and_safety_limits():
    spec = GraphSpec("bar", "city", ("ok",))
    data = GraphData.from_result(result(), spec)
    assert data.labels == ["東京", "Osaka"] and data.values == [[12.5], [0.0]]
    with pytest.raises(GraphError, match="100 rows"):
        GraphData.from_result(QueryResult(["city", "ok"], [("a", 1)] * 101), spec)
    with pytest.raises(GraphError, match="unambiguous"):
        GraphData.from_result(QueryResult(["city", "ok", "ok"], []), spec)
