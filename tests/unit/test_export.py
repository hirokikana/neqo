import csv
import io
import json
from datetime import date
from decimal import Decimal

import pytest

from neqo.errors import QueryError
from neqo.export import write_csv
from neqo.result import QueryResult


def test_csv_values_and_single_header():
    output = io.StringIO(newline="")
    pages = [
        QueryResult(["value", "value"], [('a,"quoted"\nline', None), ("日本語", "")]),
        QueryResult(["value", "value"], [(date(2026, 9, 5), Decimal("123.450"))]),
        QueryResult(["value", "value"], [({"nested": [1, 2]}, b"hi")]),
    ]
    assert write_csv(iter(pages), output) == 4
    rows = list(csv.reader(io.StringIO(output.getvalue())))
    assert rows[0] == ["value", "value"]
    assert rows[1] == ['a,"quoted"\nline', ""]
    assert rows[2] == ["日本語", ""]
    assert rows[3] == ["2026-09-05", "123.450"]
    assert json.loads(rows[4][0]) == {"nested": [1, 2]}
    assert rows[4][1] == "aGk="
    assert not output.closed


def test_empty_result_has_header(tmp_path):
    path = tmp_path / "empty.csv"
    assert QueryResult(["id", "name"], []).to_csv(path) == 0
    assert path.read_text() == "id,name\n"


@pytest.mark.parametrize("existing", [True, False])
def test_failed_export_does_not_publish_partial_file(tmp_path, existing):
    path = tmp_path / "result.csv"
    if existing:
        path.write_text("previous data")

    def pages():
        yield QueryResult(["id"], [(1,)])
        raise QueryError("Page fetch failed")

    with pytest.raises(QueryError, match="Page fetch failed"):
        write_csv(pages(), path)
    if existing:
        assert path.read_text() == "previous data"
    else:
        assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_truncated_or_inconsistent_results_rejected(tmp_path):
    with pytest.raises(QueryError, match="truncated"):
        QueryResult(["id"], [(1,)], {"truncated": True}).to_csv(tmp_path / "bad.csv")
    with pytest.raises(QueryError, match="columns changed"):
        write_csv([QueryResult(["id"], []), QueryResult(["name"], [])], tmp_path / "bad.csv")
    assert not (tmp_path / "bad.csv").exists()
