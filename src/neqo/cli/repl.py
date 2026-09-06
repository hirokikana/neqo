from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import Completer
from prompt_toolkit.completion import Completion as PromptCompletion
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from rich.console import Console

from neqo.cli.output import print_result
from neqo.completion import CompletionEngine
from neqo.errors import NeqoError, QueryError
from neqo.runner import Runner


class SQLCompleter(Completer):
    def __init__(self, completion: CompletionEngine):
        self.completion = completion

    def get_completions(self, document, complete_event):
        for candidate in self.completion.complete(document.text, document.cursor_position):
            yield PromptCompletion(
                candidate.value,
                start_position=candidate.start_position,
                display_meta=candidate.signature or candidate.kind,
            )


def _key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @Condition
    def completion_selected() -> bool:
        state = get_app().current_buffer.complete_state
        return state is not None and state.complete_index is not None

    @bindings.add("enter", filter=completion_selected)
    def accept_completion(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        state = buffer.complete_state
        if state is not None:
            # Navigation already inserts the candidate; keep it and close the menu.
            buffer.complete_state = None

    return bindings


def repl(runner: Runner, *, history: bool = True) -> None:
    console = Console()
    completion = CompletionEngine(runner.engine, runner.macros)
    file_history = None
    if history:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "neqo"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / "history"
        path.touch(mode=0o600, exist_ok=True)
        file_history = FileHistory(str(path))
    session: PromptSession = PromptSession(
        history=file_history,
        completer=SQLCompleter(completion),
        complete_while_typing=True,
        key_bindings=_key_bindings(),
    )
    console.print("NEQO", style="bold")
    console.print(f"Engine: {runner.engine.name}", markup=False)
    console.print(f"Database: {getattr(runner.engine, 'database', '')}", markup=False)
    if hasattr(runner.engine, "workgroup"):
        console.print(f"Workgroup: {runner.engine.workgroup}", markup=False)
    pending = ""
    while True:
        try:
            line = session.prompt("...> " if pending else "neqo> ", default=pending)
            if not line.strip():
                continue
            if line.startswith(":"):
                command, _, argument = line.strip().partition(" ")
                if command in {":quit", ":exit"}:
                    break
                if command == ":tables":
                    for table in runner.engine.tables():
                        console.print(f"{table.schema}.{table.name} ({table.kind})", markup=False)
                elif command == ":schema":
                    for column in runner.engine.columns(argument.strip()):
                        console.print(f"{column.name}: {column.data_type}", markup=False)
                elif command == ":macros":
                    for macro in runner.macros:
                        console.print(macro.signature, markup=False)
                elif command == ":refresh":
                    completion.refresh()
                    console.print("Metadata cache cleared.")
                elif command == ":engine":
                    console.print(runner.engine.name, markup=False)
                else:
                    console.print("Unknown meta command.")
                pending = ""
                continue
            if not line.rstrip().endswith(";"):
                pending = line + "\n"
                continue
            pending = ""
            print_result(runner.execute(line))
        except KeyboardInterrupt:
            pending = ""
        except EOFError:
            break
        except NeqoError as exc:
            pending = ""
            console.print(str(exc), markup=False)
            if isinstance(exc, QueryError) and exc.query_id:
                console.print(f"Query ID: {exc.query_id}", markup=False)
        except Exception:
            pending = ""
            console.print("Operation failed; check SQL, connection settings and permissions.")
