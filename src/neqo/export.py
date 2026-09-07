from __future__ import annotations

import csv
import json
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TextIO

from neqo.errors import QueryError
from neqo.result import QueryResult, _json_value


@contextmanager
def output_stream(destination: str | Path | TextIO) -> Iterator[TextIO]:
    """Publish path output only on success; caller-owned streams remain open."""
    if hasattr(destination, "write"):
        yield destination
        return
    target = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            yield stream
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _cell(value: Any) -> Any:
    value = _json_value(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_csv(
    pages: Iterable[QueryResult], destination: str | Path | TextIO, *, include_header: bool = True
) -> int:
    """Write LF-delimited CSV with an optional header; return the data row count.

    NULL is an empty field. Caller-owned text streams should use newline="".
    """
    count = 0
    columns = None
    with output_stream(destination) as stream:
        writer = csv.writer(stream, lineterminator="\n")
        cr_writer = csv.writer(stream, lineterminator="\n", quoting=csv.QUOTE_ALL)

        def write_row(values: list[Any]) -> None:
            # With an LF terminator, csv.writer no longer automatically quotes bare CR.
            selected = cr_writer if any("\r" in str(value) for value in values) else writer
            selected.writerow(values)

        for page in pages:
            if page.metadata.get("truncated"):
                raise QueryError("Cannot export a truncated result; use a streaming engine API")
            if columns is None:
                columns = page.columns
                if include_header:
                    write_row(columns)
            elif page.columns != columns:
                raise QueryError("Result columns changed during CSV export")
            for row in page.rows:
                write_row([_cell(value) for value in row])
                count += 1
    return count
