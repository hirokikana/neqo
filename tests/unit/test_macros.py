from datetime import date

import pytest

from neqo.errors import ConfigError, MacroError
from neqo.macros import Macro, MacroRegistry, MacroRenderer, Parameter
from neqo.macros.loader import load_macros


@pytest.mark.parametrize("dialect", ["duckdb", "trino"])
@pytest.mark.parametrize(
    "value,kind,expected",
    [
        ("O'Reilly", "string", "'O''Reilly'"),
        ("x'; DROP TABLE users; --", "string", "'x''; DROP TABLE users; --'"),
        ("main.logs", "identifier", '"main"."logs"'),
        ("500", "integer", "500"),
        (date(2026, 9, 5), "date", "DATE '2026-09-05'"),
        ("false", "boolean", "FALSE"),
        (2.5, "float", "2.5"),
    ],
)
def test_typed_render(dialect, value, kind, expected):
    macro = Macro("m", "SELECT {{ value }}", {"value": Parameter(kind)})
    assert MacroRenderer().render(macro, {"value": value}, dialect) == "SELECT " + expected


@pytest.mark.parametrize(
    "value,kind",
    [
        ("a; DROP TABLE x", "identifier"),
        ("a..b", "identifier"),
        ("1 OR 1=1", "integer"),
        (True, "integer"),
        (float("nan"), "float"),
        (True, "float"),
        ("2026-02-30", "date"),
        ("yes", "boolean"),
        (None, "string"),
        ("a\x00b", "string"),
        ("x", "unknown"),
    ],
)
def test_reject_invalid_values(value, kind):
    with pytest.raises(MacroError):
        MacroRenderer().render(
            Macro("m", "{{ x }}", {"x": Parameter(kind)}), {"x": value}, "duckdb"
        )


def test_defaults_required_unknown():
    renderer = MacroRenderer()
    macro = Macro("m", "{{ x }}", {"x": Parameter("integer", 500)})
    assert renderer.render(macro, {}, "duckdb") == "500"
    with pytest.raises(MacroError, match="Unknown"):
        renderer.render(macro, {"y": 1}, "duckdb")
    with pytest.raises(MacroError, match="Missing"):
        renderer.render(Macro("m", "{{ x }}", {"x": Parameter()}), {}, "duckdb")


@pytest.mark.parametrize(
    "sql",
    [
        "{{ x | safe }}",
        "{{ x.upper() }}",
        "{% for i in x %}{{ i }}{% endfor %}",
        "{{ x.__class__ }}",
        "{{ missing }}",
    ],
)
def test_no_arbitrary_jinja(sql):
    with pytest.raises(MacroError):
        MacroRenderer().render(Macro("m", sql, {"x": Parameter()}), {"x": "v"}, "duckdb")


def test_registry_alias_and_duplicate():
    registry = MacroRegistry()
    macro = Macro("investigate_request", "SELECT 1")
    registry.register(macro)
    assert registry.get("investigate-request") is macro
    with pytest.raises(MacroError, match="Duplicate"):
        registry.register(Macro("investigate-request", "SELECT 2"))
    with pytest.raises(MacroError, match="Unknown"):
        registry.get("missing")


def test_loading(tmp_path):
    (tmp_path / "macros").mkdir()
    (tmp_path / "macros/hello.sql").write_text("SELECT {{ name }}")
    registry = load_macros({"path": "macros"}, tmp_path)
    assert registry.get("hello").signature == "hello(name)"
    assert registry.get("hello").params["name"].type == "string"
    with pytest.raises(ConfigError):
        load_macros({"bad": {"file": "missing.sql"}}, tmp_path)


def test_explicit_loading(tmp_path):
    (tmp_path / "query.sql").write_text("SELECT {{ limit }}")
    registry = load_macros(
        {
            "m": {
                "file": "query.sql",
                "params": {
                    "limit": {"type": "integer", "default": 10},
                },
            }
        },
        tmp_path,
    )
    assert registry.get("m").signature == "m(limit=10)"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT '{{ x }}'",
        'SELECT "{{ x }}"',
        "SELECT pre{{ x }}",
        "SELECT 1 -- {{ x }}",
        "SELECT 1 /* {{ x }} */",
        "SELECT $tag${{ x }}$tag$",
    ],
)
def test_reject_quoted_or_partial_placeholders(sql):
    with pytest.raises(MacroError, match="standalone"):
        MacroRenderer().render(Macro("m", sql, {"x": Parameter()}), {"x": "'; --"}, "duckdb")
