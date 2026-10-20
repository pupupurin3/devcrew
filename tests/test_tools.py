import pytest

from devcrew.tools import ToolError, Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 1\n")
    return Workspace(tmp_path)


def test_path_escape_rejected(ws):
    with pytest.raises(ToolError):
        ws.read_file("../outside.txt")
    with pytest.raises(ToolError):
        ws.write_file("/etc/passwd", "nope")


def test_read_numbers_lines(ws):
    assert ws.read_file("a.py").splitlines()[1].strip() == "2  y = 1"


def test_edit_requires_unique_match(ws):
    with pytest.raises(ToolError, match="exactly once"):
        ws.edit_file("a.py", "= 1", "= 2")
    ws.edit_file("a.py", "x = 1", "x = 2")
    assert ws.root.joinpath("a.py").read_text() == "x = 2\ny = 1\n"
    assert ws.changed_files == {"a.py"}


def test_search(ws):
    assert ws.search(r"y =") == "a.py:2: y = 1"


def test_command_allowlist(ws):
    with pytest.raises(ToolError, match="not allowed"):
        ws.run_command("rm -rf .")
    # No shell: metacharacters are not interpreted, so chaining fails closed.
    with pytest.raises(ToolError):
        ws.run_command("ls; rm a.py")
    assert ws.root.joinpath("a.py").exists()


def test_git_is_read_only(ws):
    with pytest.raises(ToolError, match="read-only"):
        ws.run_command("git push origin main")


def test_run_command_reports_exit_code(ws):
    out = ws.run_command("python -c \"print('hi')\"")
    assert out.startswith("exit code: 0") and "hi" in out
