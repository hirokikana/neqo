from __future__ import annotations

import argparse
import shlex

from neqo.graphs import GraphError, GraphSpec, check_graph_dependency


def graph_options(
    kind: str | None,
    x: str | None,
    y: list[str] | None,
    colors: str | None,
    width: int,
    no_color: bool,
) -> GraphSpec | None:
    if kind is None:
        if x or y or colors or width != 40 or no_color:
            raise GraphError("Graph options require --graph")
        return None
    spec = GraphSpec(
        kind, x or "", tuple(y or ()), tuple(colors.split(",")) if colors else (), width
    )
    check_graph_dependency()
    return spec


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise GraphError(f"Invalid :graph arguments: {message}")


def _graph_parser() -> _Parser:
    parser = _Parser(prog=":graph", add_help=False)
    parser.add_argument("kind", choices=["auto", "bar", "stacked"], nargs="?", default="auto")
    parser.add_argument("--x", help="Label column; inferred in auto mode")
    parser.add_argument(
        "--y", action="append", help="Numeric column; repeat for series; inferred in auto mode"
    )
    parser.add_argument("--colors", help="Comma-separated series colors; automatic when omitted")
    parser.add_argument("--width", type=int, default=40, help="Maximum bar width (default: 40)")
    parser.add_argument("--no-color", action="store_true", help="Disable color")
    return parser


def graph_help() -> str:
    return _graph_parser().format_help()


def parse_graph_command(argument: str) -> tuple[GraphSpec, bool]:
    parser = _graph_parser()
    try:
        args = parser.parse_args(shlex.split(argument))
    except GraphError:
        raise
    except ValueError as exc:
        raise GraphError("Invalid quoting in :graph arguments") from exc
    return graph_options(
        args.kind, args.x, args.y, args.colors, args.width, args.no_color
    ), args.no_color
