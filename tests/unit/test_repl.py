import asyncio
from unittest.mock import Mock

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from neqo import Runner
from neqo.cli.repl import SQLCompleter, _key_bindings, repl
from neqo.completion import CompletionEngine
from neqo.macros import Macro, MacroRegistry


def test_repl_queries_meta_and_recovery(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    session = Mock()
    session.prompt.side_effect = [
        "",
        "SELECT",
        "SELECT\n42 AS answer;",
        ":tables",
        ":schema logs",
        ":macros",
        ":refresh",
        ":engine",
        ":unknown",
        "SELECT missing;",
        KeyboardInterrupt(),
        "SELECT 1;",
        ":quit",
    ]
    factory = Mock(return_value=session)
    monkeypatch.setattr("neqo.cli.repl.PromptSession", factory)
    registry = MacroRegistry()
    registry.register(Macro("one", "SELECT 1"))
    with Runner(engine="duckdb", macros=registry) as runner:
        runner.execute("CREATE TABLE logs(id INTEGER)")
        repl(runner, history=False)
    output = capsys.readouterr().out
    assert "42" in output
    assert "main.logs" in output
    assert "id: INTEGER" in output
    assert "one()" in output
    assert "Metadata cache cleared" in output
    assert "DuckDB query failed" in output
    assert factory.call_args.kwargs["history"] is None
    assert session.prompt.call_args_list[2].kwargs["default"] == "SELECT\n"


def test_history_and_eof(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    session = Mock()
    session.prompt.side_effect = EOFError()
    monkeypatch.setattr("neqo.cli.repl.PromptSession", Mock(return_value=session))
    with Runner(engine="duckdb") as runner:
        repl(runner)
    assert (tmp_path / "neqo/history").exists()
    assert (tmp_path / "neqo/history").stat().st_mode & 0o777 == 0o600


def test_prompt_completion_adapter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with Runner(engine="duckdb") as runner:
        runner.execute("CREATE TABLE logs(id INTEGER)")
        completer = SQLCompleter(CompletionEngine(runner.engine))
        candidates = list(completer.get_completions(Document("SELECT * FROM lo"), None))
        assert any(c.text == "logs" and c.start_position == -2 for c in candidates)


@pytest.mark.parametrize("selected_index", [None, 0, 1])
def test_enter_accepts_completion_without_submitting(selected_index):
    async def wait_until(predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    async def interact():
        with create_pipe_input() as pipe:
            session = PromptSession(
                input=pipe,
                output=DummyOutput(),
                completer=WordCompleter(["request_id", "request_path"]),
                key_bindings=_key_bindings(),
            )
            prompt = asyncio.create_task(session.prompt_async())
            try:
                pipe.send_text("req")
                buffer = session.default_buffer
                await wait_until(lambda: buffer.complete_state is not None)
                buffer.go_to_completion(selected_index)
                pipe.send_text("\r")
                await wait_until(lambda: buffer.complete_state is None or prompt.done())
                assert not prompt.done(), "Accepting a candidate must not submit the SQL"
                expected = "request_path" if selected_index == 1 else "request_id"
                assert buffer.text == expected
                assert buffer.cursor_position == len(expected)

                pipe.send_text("\r")
                assert await asyncio.wait_for(prompt, timeout=3) == expected
            finally:
                if not prompt.done():
                    prompt.cancel()
                await asyncio.gather(prompt, return_exceptions=True)

    asyncio.run(interact())
