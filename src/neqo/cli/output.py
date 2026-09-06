from rich.console import Console
from rich.table import Table

from neqo.result import QueryResult


def print_result(result: QueryResult, *, json_output: bool = False) -> None:
    console = Console()
    if json_output:
        console.print(result.to_json(), markup=False, highlight=False, soft_wrap=True)
        return
    table = Table(*result.columns)
    for row in result.rows:
        from rich.text import Text

        table.add_row(*(Text("NULL" if cell is None else str(cell)) for cell in row))
    console.print(table)
    console.print(f"{len(result.rows)} rows", markup=False)
    if result.metadata.get("truncated"):
        console.print("Result truncated at configured max_rows.")
    if "scanned_bytes" in result.metadata:
        console.print(
            f"Scanned: {result.metadata['scanned_bytes']} bytes; "
            f"execution: {result.metadata.get('execution_time_ms', 0)} ms"
        )
