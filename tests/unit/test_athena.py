import csv
from unittest.mock import Mock

import boto3
import pytest
from botocore.stub import Stubber

from neqo import Runner
from neqo.engines.athena import AthenaEngine
from neqo.errors import QueryError


def execution(state="SUCCEEDED"):
    return {
        "QueryExecution": {
            "Status": {"State": state},
            "Statistics": {
                "DataScannedInBytes": 123,
                "EngineExecutionTimeInMillis": 10,
            },
            "ResultConfiguration": {"OutputLocation": "s3://results/q.csv"},
        }
    }


def page(rows, token=None):
    result = {
        "ResultSet": {
            "ResultSetMetadata": {
                "ColumnInfo": [
                    {"Name": "name", "Type": "varchar"},
                    {"Name": "n", "Type": "integer"},
                ]
            },
            "Rows": [
                {"Data": [({} if v is None else {"VarCharValue": v}) for v in row]} for row in rows
            ],
        }
    }
    if token:
        result["NextToken"] = token
    return result


@pytest.mark.parametrize("update_count", [None, 0])
def test_real_sdk_contract(tmp_path, update_count):
    client = boto3.client(
        "athena",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    engine = AthenaEngine(database="analytics", client=client, cache_dir=tmp_path)
    with Stubber(client) as stub:
        stub.add_response(
            "start_query_execution",
            {"QueryExecutionId": "q"},
            {
                "QueryString": "SELECT 1",
                "WorkGroup": "primary",
                "QueryExecutionContext": {"Database": "analytics", "Catalog": "AwsDataCatalog"},
            },
        )
        stub.add_response("get_query_execution", execution(), {"QueryExecutionId": "q"})
        first_page = page([["name", "n"], ["x", "1"]], "next")
        if update_count is not None:
            first_page["UpdateCount"] = update_count
        stub.add_response(
            "get_query_results",
            first_page,
            {"QueryExecutionId": "q", "MaxResults": 1000},
        )
        stub.add_response(
            "get_query_results",
            page([["y", None]]),
            {"QueryExecutionId": "q", "MaxResults": 1000, "NextToken": "next"},
        )
        assert engine.submit("SELECT 1").query_id == "q"
        result = engine.result("q")
        assert result.rows == [("x", 1), ("y", None)]
        assert result.metadata["scanned_bytes"] == 123
        stub.assert_no_pending_responses()


def test_athena_csv_streams_all_pages_once(tmp_path):
    client = boto3.client(
        "athena",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    engine = AthenaEngine(client=client, max_rows=1)
    with Stubber(client) as stub:
        stub.add_response(
            "start_query_execution",
            {"QueryExecutionId": "q"},
            {
                "QueryString": "SELECT name, n FROM logs",
                "WorkGroup": "primary",
                "QueryExecutionContext": {"Database": "default", "Catalog": "AwsDataCatalog"},
            },
        )
        stub.add_response("get_query_execution", execution(), {"QueryExecutionId": "q"})
        stub.add_response("get_query_execution", execution(), {"QueryExecutionId": "q"})
        stub.add_response(
            "get_query_results",
            page([["name", "n"], ['a,"b"\nc', "1"]], "next"),
            {"QueryExecutionId": "q", "MaxResults": 1000},
        )
        stub.add_response(
            "get_query_results",
            page([["last", None]]),
            {"QueryExecutionId": "q", "MaxResults": 1000, "NextToken": "next"},
        )
        path = tmp_path / "athena.csv"
        with Runner(engine=engine) as runner:
            assert runner.export_csv("SELECT name, n FROM logs", path) == 2
        with path.open(newline="") as stream:
            assert list(csv.reader(stream)) == [["name", "n"], ['a,"b"\nc', "1"], ["last", ""]]
        stub.assert_no_pending_responses()


def test_polling_and_metadata(tmp_path):
    client = Mock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q"}
    client.get_query_execution.side_effect = [execution("RUNNING"), execution(), execution()]
    client.get_query_results.return_value = page([["name", "n"], ["x", "2"]])
    engine = AthenaEngine(
        client=client, cache_dir=tmp_path, poll_interval=0.001, output_location="s3://results/"
    )
    assert engine.execute("SELECT 2").rows == [("x", 2)]
    assert client.start_query_execution.call_args.kwargs["ResultConfiguration"] == {
        "OutputLocation": "s3://results/",
    }


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED", "RUNNING", "QUEUED"])
def test_unavailable_result(state, tmp_path):
    client = Mock()
    client.get_query_execution.return_value = execution(state)
    engine = AthenaEngine(client=client, cache_dir=tmp_path)
    with pytest.raises(QueryError) as caught:
        engine.result("q")
    assert caught.value.query_id == "q"
    client.get_query_results.assert_not_called()


def test_timeout_and_cancel(tmp_path):
    client = Mock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q"}
    client.get_query_execution.return_value = execution("RUNNING")
    engine = AthenaEngine(client=client, cache_dir=tmp_path, timeout=0.001, poll_interval=0.001)
    with pytest.raises(QueryError, match="timed out"):
        engine.execute("SELECT 1")
    client.stop_query_execution.assert_not_called()
    engine.cancel("q")
    client.stop_query_execution.assert_called_once_with(QueryExecutionId="q")


def test_materialization_cap(tmp_path):
    client = Mock()
    client.get_query_execution.return_value = execution()
    client.get_query_results.return_value = page([["name", "n"], ["x", "1"], ["y", "2"]], "next")
    result = AthenaEngine(client=client, cache_dir=tmp_path, max_rows=1).result("q")
    assert result.rows == [("x", 1)]
    assert result.metadata["truncated"]
    client.get_query_results.assert_called_once()


def test_catalog_cache_and_partitions(tmp_path):
    client = Mock()
    client.list_table_metadata.return_value = {
        "TableMetadataList": [
            {
                "Name": "logs",
                "TableType": "EXTERNAL_TABLE",
                "Columns": [{"Name": "id", "Type": "string"}],
                "PartitionKeys": [{"Name": "dt", "Type": "date"}],
            },
            {"Name": "failures", "TableType": "VIRTUAL_VIEW"},
        ]
    }
    engine = AthenaEngine(client=client, cache_dir=tmp_path)
    assert engine.tables()[1].kind == "view"
    assert [c.name for c in engine.columns("logs")] == ["id", "dt"]
    engine.tables()
    client.list_table_metadata.assert_called_once()
    engine.refresh()
    engine.tables()
    assert client.list_table_metadata.call_count == 2


def test_dml_count_is_not_header(tmp_path):
    client = Mock()
    client.get_query_execution.return_value = execution()
    client.get_query_results.return_value = {
        "UpdateCount": 12,
        "ResultSet": {
            "ResultSetMetadata": {
                "ColumnInfo": [
                    {"Name": "rows", "Type": "bigint"},
                ]
            },
            "Rows": [{"Data": [{"VarCharValue": "12"}]}],
        },
    }
    result = AthenaEngine(client=client, cache_dir=tmp_path).result("q")
    assert result.rows == [(12,)]
    assert result.metadata["update_count"] == 12
