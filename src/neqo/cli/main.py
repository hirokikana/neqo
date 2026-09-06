from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from neqo.cli.output import print_result
from neqo.errors import NeqoError, QueryError
from neqo.export import output_stream
from neqo.runner import Runner

app = typer.Typer(no_args_is_help=False, help="NEQO - Nimble Engine Query Orchestrator")


@contextmanager
def _runner(ctx: typer.Context, **overrides):
    try:
        with Runner(**(ctx.obj | overrides)) as runner:
            yield runner
    except NeqoError as exc:
        typer.echo(f"Error: {exc}", err=True)
        if isinstance(exc, QueryError) and exc.query_id:
            typer.echo(f"Query ID: {exc.query_id}", err=True)
        raise typer.Exit(1) from None
    except OSError:
        typer.echo(
            "Cannot write output; check the path, permissions and available disk space.", err=True
        )
        raise typer.Exit(1) from None
    except Exception:
        typer.echo("Operation failed; check connection settings, SQL and permissions.", err=True)
        raise typer.Exit(1) from None


@app.callback(invoke_without_command=True)
def configure(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    profile: Annotated[str | None, typer.Option()] = None,
    engine: Annotated[str | None, typer.Option()] = None,
    database: Annotated[str | None, typer.Option()] = None,
    verbose: Annotated[bool, typer.Option()] = False,
    no_history: Annotated[bool, typer.Option()] = False,
):
    if verbose:
        handler = logging.StreamHandler()
        logger = logging.getLogger("neqo")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.debug("NEQO debug logging enabled (query text and credentials excluded)")
    ctx.obj = {"config": config, "profile": profile, "engine": engine}
    if database is not None:
        ctx.obj["database"] = database
    ctx.meta["history"] = not no_history
    if ctx.invoked_subcommand is None:
        _interactive(ctx)


def _interactive(ctx: typer.Context, **options):
    from neqo.cli.repl import repl

    with _runner(ctx, **options) as runner:
        repl(runner, history=ctx.meta.get("history", True))


@app.command()
def query(
    ctx: typer.Context,
    sql: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    csv_output: Annotated[
        str | None, typer.Option("--csv", help="Export all rows to FILE; - for stdout.")
    ] = None,
):
    """Execute raw SQL."""
    _validate_output(json_output, csv_output)
    with _runner(ctx) as runner:
        _execute(runner, sql, json_output, csv_output)


def _validate_output(json_output: bool, csv_output: str | None) -> None:
    if json_output and csv_output is not None:
        raise typer.BadParameter("--json and --csv are mutually exclusive")


def _execute(runner: Runner, sql: str, json_output: bool, csv_output: str | None) -> None:
    if csv_output is None:
        print_result(runner.execute(sql), json_output=json_output)
    else:
        count = runner.export_csv(sql, sys.stdout if csv_output == "-" else Path(csv_output))
        if csv_output != "-":
            typer.echo(f"Exported {count} rows to {csv_output}", err=True)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(
    ctx: typer.Context,
    macro: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    csv_output: Annotated[
        str | None, typer.Option("--csv", help="Export all rows to FILE; - for stdout.")
    ] = None,
):
    """Run a macro with --parameter value or --parameter=value arguments."""
    _validate_output(json_output, csv_output)
    parameters = _parameters(ctx.args)
    with _runner(ctx) as runner:
        _execute(runner, runner.render(macro, **parameters), json_output, csv_output)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def render(
    ctx: typer.Context,
    macro: str,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write SQL to a file.")
    ] = None,
):
    """Render a macro as SQL without executing it or connecting to Athena/DuckDB."""
    parameters = _parameters(ctx.args)
    with _runner(ctx) as runner:
        sql = runner.render(macro, **parameters)
        if output is None:
            typer.echo(sql)
        else:
            with output_stream(output) as stream:
                stream.write(sql.rstrip() + "\n")


def _parameters(arguments: list[str]) -> dict[str, str]:
    parameters = {}
    args = iter(arguments)
    for argument in args:
        if not argument.startswith("--"):
            raise typer.BadParameter("Expected --parameter value")
        key, separator, value = argument[2:].partition("=")
        if not separator:
            value = next(args, None)
        if value is None or not key:
            raise typer.BadParameter("Each parameter needs a value")
        key = key.replace("-", "_")
        if key in parameters:
            raise typer.BadParameter(f"Duplicate parameter: {key}")
        parameters[key] = value
    return parameters


@app.command()
def duckdb(ctx: typer.Context, database: str | None = None):
    """Open the DuckDB SQL REPL."""
    options = {"engine": "duckdb"}
    if database is not None:
        options["database"] = database
    _interactive(ctx, **options)


@app.command()
def athena(ctx: typer.Context):
    """Open the Athena SQL REPL using boto3's credential provider chain."""
    _interactive(ctx, engine="athena")


def main() -> None:
    app()
