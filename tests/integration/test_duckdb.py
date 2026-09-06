import pytest

from neqo import Runner
from neqo.completion import CompletionEngine
from neqo.engines.duckdb import DuckDBEngine
from neqo.errors import QueryError
from neqo.macros import Macro, MacroRegistry, Parameter

pytestmark = pytest.mark.integration


@pytest.fixture
def engine():
    with DuckDBEngine() as engine:
        engine.execute("CREATE TABLE access_logs(request_id VARCHAR, status INTEGER)")
        engine.execute("INSERT INTO access_logs VALUES ('abc123', 503)")
        engine.execute("CREATE VIEW failures AS SELECT * FROM access_logs WHERE status >= 500")
        yield engine


def test_execution_catalog(engine):
    assert engine.execute("SELECT * FROM access_logs").rows == [("abc123", 503)]
    assert "main" in engine.schemas()
    assert engine.databases()
    assert {(t.name, t.kind) for t in engine.tables()} >= {
        ("access_logs", "table"),
        ("failures", "view"),
    }
    assert [c.name for c in engine.columns("main.access_logs")] == ["request_id", "status"]
    engine.execute("CREATE MACRO plus_one(x) AS x + 1")
    assert any(f.name == "plus_one" and f.kind == "macro" for f in engine.functions())


def test_runner_and_handle(engine):
    registry = MacroRegistry()
    registry.register(
        Macro(
            "lookup", "SELECT * FROM access_logs WHERE request_id = {{ id }}", {"id": Parameter()}
        )
    )
    with Runner(engine=engine, macros=registry) as runner:
        assert runner.run("lookup", id="abc123").rows == [("abc123", 503)]
        assert runner.run("lookup", id="x' OR 1=1 --").rows == []
        handle = runner.submit("lookup", id="abc123")
        assert runner.status(handle.query_id) == "SUCCEEDED"
        assert runner.result(handle.query_id).rows == [("abc123", 503)]
    assert engine.execute("SELECT 1").rows == [(1,)]


def test_result_bounds():
    with DuckDBEngine(max_rows=2, retained_results=1) as engine:
        handle = engine.submit("SELECT * FROM range(3)")
        assert len(engine.result(handle.query_id).rows) == 2
        assert engine.result(handle.query_id).metadata["truncated"]
        engine.submit("SELECT 1")
        with pytest.raises(QueryError, match="expired"):
            engine.result(handle.query_id)


@pytest.mark.parametrize(
    "sql,cursor,expected",
    [
        ("SELECT * FROM ac", None, "access_logs"),
        ("SELECT * FROM access_logs WHERE st", None, "status"),
        ("SELECT l. FROM access_logs l", len("SELECT l."), "request_id"),
        ("SELECT * FROM main.ac", None, "access_logs"),
        ("SELECT cou", None, "count"),
    ],
)
def test_completion(engine, sql, cursor, expected):
    candidates = CompletionEngine(engine).complete(sql, len(sql) if cursor is None else cursor)
    assert expected in {c.value for c in candidates}


def test_macro_completion(engine):
    registry = MacroRegistry()
    registry.register(Macro("errors", "SELECT 1", {"status": Parameter("integer", 500)}))
    candidates = CompletionEngine(engine, registry).complete("err", 3)
    assert any(
        c.kind == "macro" and c.signature == "errors(status=500)" and c.start_position == -3
        for c in candidates
    )


@pytest.mark.parametrize(
    "value", ["\\'; DROP TABLE access_logs; --", "line\n'break", "日本語", "[bold]x"]
)
def test_string_parameters_round_trip(engine, value):
    registry = MacroRegistry()
    registry.register(Macro("echo", "SELECT {{ value }}", {"value": Parameter()}))
    runner = Runner(engine=engine, macros=registry)
    assert runner.run("echo", value=value).rows == [(value,)]
    assert engine.execute("SELECT count(*) FROM access_logs").rows == [(1,)]
