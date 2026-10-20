from pathlib import Path

from fakes import ScriptedBackend, response, tool

from devcrew.evals import Setup, run_benchmark, summarize
from devcrew.pipeline import run_solo

TASKS = Path(__file__).parent.parent / "evals" / "tasks"

FIXED_PAGER = '''\
def paginate(items, page, per_page):
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be >= 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def page_count(items, per_page):
    return -(-len(items) // per_page)
'''


def scripted_solo(*edits):
    """A fake agent that applies fixed edits, then reports success."""
    def fn(params):
        step = (len(params["messages"]) - 1) // 2
        if step < len(edits):
            return response(tool("write_file", path=edits[step][0], content=edits[step][1]))
        return response(tool("submit_work", summary="done", tests_passing=True))
    return Setup("fake", lambda r, t, b: run_solo(r, t, ScriptedBackend(fn=fn)))


def test_every_task_starts_unsolved():
    # Sanity check on the benchmark itself: doing nothing must fail every task.
    noop = scripted_solo()
    summary = run_benchmark(TASKS, None, [noop], log=lambda _: None)
    assert summary[0]["runs"] == len(list(TASKS.glob("*/task.md")))
    assert summary[0]["pass_rate"] == 0


def test_correct_fix_passes():
    rows = []
    run_benchmark(TASKS, None, [scripted_solo(("pager.py", FIXED_PAGER))],
                  only=["pagination"], log=rows.append)
    assert "PASS" in rows[0]


def test_tampering_with_visible_tests_fails_even_if_green():
    cheat = scripted_solo(("pager.py", FIXED_PAGER), ("tests/test_pager.py", "def test_ok():\n    pass\n"))
    summary = run_benchmark(TASKS, None, [cheat], only=["pagination"], log=lambda _: None)
    assert summary[0]["pass_rate"] == 0 and summary[0]["tampered"] == 1


def test_summarize_math():
    rows = [
        {"setup": "a", "approved": True, "wall_s": 10, "total": {"cost_usd": 1.0},
         "grade": {"passed": True, "tampered_tests": []}},
        {"setup": "a", "approved": True, "wall_s": 20, "total": {"cost_usd": 3.0},
         "grade": {"passed": False, "tampered_tests": []}},
    ]
    (s,) = summarize(rows)
    assert s["pass_rate"] == 0.5 and s["self_reported_ok"] == 1.0 and s["mean_cost_usd"] == 2.0
