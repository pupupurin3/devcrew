from fakes import ScriptedBackend, response, tool

from devcrew.pipeline import run_crew, run_solo

PLAN = dict(summary="fix it", steps=["edit m.py"], acceptance_criteria=["tests pass"])


def test_crew_revises_until_reviewer_approves(tmp_path):
    (tmp_path / "m.py").write_text("x = 0\n")
    backend = ScriptedBackend([
        response(tool("submit_plan", **PLAN)),
        response(tool("write_file", path="m.py", content="x = 1\n")),
        response(tool("submit_work", summary="set x", tests_passing=True)),
        response(tool("submit_review", verdict="request_changes", issues=["x must be 2"], summary="wrong")),
        response(tool("edit_file", path="m.py", old_str="x = 1", new_str="x = 2")),
        response(tool("submit_work", summary="x is 2", tests_passing=True)),
        response(tool("submit_review", verdict="approve", issues=[], summary="good")),
    ])
    result = run_crew(tmp_path, "make x 2", backend)

    assert result.approved and result.rounds == 2 and result.error is None
    assert (tmp_path / "m.py").read_text() == "x = 2\n"
    assert result.changed_files == ["m.py"]
    # The second coder starts fresh but is handed the reviewer's issues.
    second_coder_prompt = backend.calls[4]["messages"][0]["content"]
    assert "x must be 2" in second_coder_prompt and "fix it" in second_coder_prompt
    # Planner and reviewer were never offered write tools.
    for i in (0, 3, 6):
        names = {t["name"] for t in backend.calls[i]["tools"]}
        assert not names & {"write_file", "edit_file"}
    assert set(result.usage) == {"planner", "coder", "reviewer"}


def test_crew_stops_after_max_rounds(tmp_path):
    reject = response(tool("submit_review", verdict="request_changes", issues=["no"], summary=""))
    work = response(tool("submit_work", summary="", tests_passing=False))
    backend = ScriptedBackend([response(tool("submit_plan", **PLAN)), work, reject, work, reject])
    result = run_crew(tmp_path, "t", backend)
    assert not result.approved and result.rounds == 2


def test_agent_failure_is_reported_not_raised(tmp_path):
    backend = ScriptedBackend([response(stop="refusal")])
    result = run_crew(tmp_path, "t", backend)
    assert not result.approved and "declined" in result.error


def test_solo(tmp_path):
    backend = ScriptedBackend([
        response(tool("write_file", path="new.py", content="")),
        response(tool("submit_work", summary="ok", tests_passing=True)),
    ])
    result = run_solo(tmp_path, "t", backend)
    assert result.approved and result.changed_files == ["new.py"]
