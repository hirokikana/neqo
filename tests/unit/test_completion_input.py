from unittest.mock import Mock

import pytest
from prompt_toolkit.document import Document

from neqo.catalog import ColumnInfo
from neqo.cli.repl import SQLCompleter
from neqo.completion import CompletionEngine
from neqo.engines.base import Engine


@pytest.fixture(params=["duckdb", "trino"])
def engine(request):
    engine = Mock(spec=Engine)
    engine.dialect = request.param
    engine.columns.return_value = [ColumnInfo("request_id"), ColumnInfo("status")]
    engine.tables.return_value = []
    engine.functions.return_value = []
    engine.native_complete.return_value = []
    return engine


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM access_logs WHERE request_id\n = '",
        "SELECT * FROM access_logs WHERE request_id = 'req-000",
        'SELECT * FROM access_logs WHERE "request_',
        "SELECT * FROM access_logs /* unfinished",
    ],
)
def test_unclosed_tokens_skip_completion_and_recover(engine, sql):
    completer = SQLCompleter(CompletionEngine(engine))
    assert list(completer.get_completions(Document(sql), None)) == []
    engine.columns.assert_not_called()
    engine.tables.assert_not_called()
    engine.functions.assert_not_called()
    engine.native_complete.assert_not_called()

    completed = "SELECT * FROM access_logs WHERE request_id = 'req-000042' AND st"
    candidates = list(completer.get_completions(Document(completed), None))
    assert any(c.text == "status" and c.start_position == -2 for c in candidates)


def test_completion_during_each_keystroke(engine):
    completer = SQLCompleter(CompletionEngine(engine))
    sql = "SELECT * FROM access_logs WHERE request_id\n = 'req-000042';"
    for position in range(len(sql) + 1):
        list(completer.get_completions(Document(sql[:position]), None))
