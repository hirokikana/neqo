"""Build the deterministic local playground without overwriting an existing database."""

from pathlib import Path

import duckdb


def main() -> None:
    root = Path(__file__).resolve().parent
    database = root / "demo.duckdb"
    if database.exists():
        raise SystemExit(f"Already exists; leaving unchanged: {database}")
    sql = (root / "setup.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(database)) as connection:
        connection.begin()
        try:
            connection.execute(sql)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        tables = connection.execute(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "ORDER BY table_schema, table_name"
        ).fetchall()
        for schema, name, kind in tables:
            print(f"{schema}.{name}: {kind}")
    print(f"\nCreated: {database}")


if __name__ == "__main__":
    main()
