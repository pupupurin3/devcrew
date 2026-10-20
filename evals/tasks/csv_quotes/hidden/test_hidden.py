import pathlib
from csvlite import parse_line


def test_quoted_comma():
    assert parse_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_escaped_quote():
    assert parse_line('"say ""hi""",x') == ['say "hi"', "x"]


def test_empty_fields():
    assert parse_line("a,,c") == ["a", "", "c"]
    assert parse_line('"",x') == ["", "x"]


def test_trailing_empty():
    assert parse_line("a,b,") == ["a", "b", ""]


def test_no_stdlib_csv():
    src = (pathlib.Path(__file__).parent / "csvlite.py").read_text()
    assert "import csv" not in src
