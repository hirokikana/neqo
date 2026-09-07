"""Optional terminal graphs. SQL remains responsible for aggregation and ordering."""

from __future__ import annotations

import io
import math
import os
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, replace
from decimal import Decimal
from threading import RLock
from typing import TextIO

from neqo.errors import NeqoError
from neqo.result import QueryResult

PALETTE = ("green", "yellow", "red", "cyan", "magenta", "blue")
_render_lock = RLock()


class GraphError(NeqoError, ValueError):
    pass


@dataclass(frozen=True)
class GraphSpec:
    kind: str = "auto"
    x: str = ""
    y: tuple[str, ...] = ()
    colors: tuple[str, ...] = ()
    width: int = 40

    def __post_init__(self) -> None:
        if self.kind not in {"auto", "bar", "stacked"}:
            raise GraphError("Graph kind must be auto, bar or stacked")
        if (self.kind != "auto" and (not self.x or not self.y)) or (
            len(set(self.y)) != len(self.y) or self.x in self.y
        ):
            raise GraphError("Specify --x and distinct --y columns")
        if len(self.y) > 6:
            raise GraphError("Graphs support at most 6 series")
        if not 1 <= self.width <= 200:
            raise GraphError("Graph width must be between 1 and 200")
        if self.colors and (
            (bool(self.y) and len(self.colors) != len(self.y))
            or any(c not in PALETTE for c in self.colors)
        ):
            raise GraphError("Provide one color per series: " + ", ".join(PALETTE))


def infer_graph(result: QueryResult, spec: GraphSpec | None = None) -> GraphSpec:
    """Infer columns without changing row order, aggregating, or assuming additivity."""
    spec = spec or GraphSpec()
    if spec.kind != "auto":
        return spec
    if result.metadata.get("truncated") or len(result.rows) > 100:
        raise GraphError("Automatic graphs require a complete result of at most 100 rows")
    if len(set(result.columns)) != len(result.columns):
        raise GraphError("Graph columns must be unambiguous; use SQL aliases")
    if any(len(row) != len(result.columns) for row in result.rows):
        raise GraphError("Result row does not match its columns")
    numeric = []
    for index, name in enumerate(result.columns):
        values = [row[index] for row in result.rows if row[index] is not None]
        if values and all(
            isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in values
        ):
            numeric.append(name)
    labels = [name for name in result.columns if name not in numeric]
    x = spec.x
    if not x:
        if len(labels) == 1:
            x = labels[0]
        elif not labels and len(result.columns) >= 2:
            x = result.columns[0]
        else:
            raise GraphError("Cannot infer a label column; specify --x (and --y if needed)")
    y = spec.y or tuple(name for name in numeric if name != x)
    if not y:
        raise GraphError("Cannot infer numeric series; specify --y or aggregate the SQL")
    return replace(spec, kind="bar", x=x, y=y)


@dataclass
class GraphData:
    labels: list[str]
    values: list[list[float]]
    series: list[str]

    @classmethod
    def from_result(cls, result: QueryResult, spec: GraphSpec) -> GraphData:
        if result.metadata.get("truncated"):
            raise GraphError("Cannot graph a truncated result; aggregate or LIMIT the SQL")
        if len(result.rows) > 100:
            raise GraphError("Graphs support at most 100 rows; aggregate or LIMIT the SQL")
        for name in (spec.x, *spec.y):
            if result.columns.count(name) != 1:
                raise GraphError(f"Graph column must exist and be unambiguous: {name}")
        indices = [result.columns.index(name) for name in spec.y]
        x_index = result.columns.index(spec.x)
        labels, values = [], []
        for row in result.rows:
            if len(row) != len(result.columns):
                raise GraphError("Result row does not match its columns")
            labels.append(_label("NULL" if row[x_index] is None else str(row[x_index])))
            numbers = []
            for index in indices:
                value = row[index]
                if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                    raise GraphError("Graph values must be numeric and non-NULL; use SQL COALESCE")
                try:
                    number = float(value)
                except (ValueError, OverflowError) as exc:
                    raise GraphError("Graph values must be finite and nonnegative") from exc
                if not math.isfinite(number) or number < 0:
                    raise GraphError("Graph values must be finite and nonnegative")
                numbers.append(number)
            if not math.isfinite(sum(numbers)):
                raise GraphError("Graph row total is too large")
            values.append(numbers)
        return cls(labels, values, [_label(name) for name in spec.y])


def _label(value: str) -> str:
    # Never let query data inject terminal control sequences or extra output lines.
    return "".join(c if c.isprintable() else " " for c in value)


def check_graph_dependency() -> None:
    try:
        import termgraph  # noqa: F401
    except ImportError as exc:
        raise GraphError("Install graph support: pip install 'neqo[graphs]'") from exc


def draw_graph(
    result: QueryResult,
    spec: GraphSpec,
    *,
    stream: TextIO | None = None,
    color: bool | None = None,
) -> None:
    """Draw a result without executing SQL.

    termgraph writes to process stdout. Rendering is serialized and captured, but
    unrelated threads must not write stdout concurrently with this function.
    """
    check_graph_dependency()
    from rich.text import Text
    from termgraph import Args, BarChart, Data, StackedChart
    from termgraph.constants import AVAILABLE_COLORS
    from wcwidth import wcswidth

    target = stream if stream is not None else sys.stdout
    if spec.kind == "auto" and not result.rows and not result.metadata.get("truncated"):
        target.write("No rows to graph.\n")
        return
    spec = infer_graph(result, spec)
    data = GraphData.from_result(result, spec)
    if not data.values:
        target.write("No rows to graph.\n")
        return
    use_color = (
        bool(getattr(target, "isatty", lambda: False)()) if color is None else color
    ) and not os.environ.get("NO_COLOR")
    # Monochrome stacked blocks would hide series boundaries; use grouped bars instead.
    stacked = spec.kind == "stacked" and use_color
    maximum = max(map(sum, data.values)) if stacked else max(map(max, data.values))

    def fit(label: str) -> str:
        if wcswidth(label) <= 24:
            return label
        text = ""
        for char in label:
            if wcswidth(text + char) > 21:
                break
            text += char
        return text + "..."

    labels = [fit(label) for label in data.labels]
    label_width = max(wcswidth(label) for label in labels)
    labels = [label + " " * (label_width - wcswidth(label)) for label in labels]

    class TerminalData(Data):
        def normalize(self, width):
            return [[v / maximum * width if maximum else 0 for v in row] for row in self.data]

        def find_max_label_length(self):
            return 0  # Labels are already padded by display cells, not Python string length.

    colors = spec.colors or PALETTE[: len(spec.y)]
    args = Args(
        width=spec.width,
        colors=[AVAILABLE_COLORS[c] for c in colors] if use_color else None,
        format="{:.6g}",
        no_readable=True,
    )
    graph_data = TerminalData(data.values, labels, data.series)
    with _render_lock, redirect_stdout(io.StringIO()) as output:
        (StackedChart if stacked else BarChart)(graph_data, args).draw()
        rendered = output.getvalue()
    if not use_color:
        rendered = Text.from_ansi(rendered).plain
    # termgraph indents continuation rows by code points; correct to display cells.
    lines = rendered.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(" ") and line.lstrip().startswith(("\x1b", "▇", "▏")):
            lines[i] = " " * (label_width + 2) + line.lstrip()
    rendered = "\n".join(lines) + "\n"
    if spec.kind == "stacked" and not stacked:
        target.write("Monochrome: showing series as grouped bars in legend order.\n")
    target.write(rendered)
