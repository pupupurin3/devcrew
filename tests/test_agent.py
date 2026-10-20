import pytest
from fakes import ScriptedBackend, response, text, tool

from devcrew.agent import Agent, AgentError
from devcrew.llm import LLM
from devcrew.tools import READ_TOOLS, SUBMIT_WORK, Workspace, handlers


def make_agent(tmp_path, script, **kw):
    (tmp_path / "f.txt").write_text("hello\n")
    backend = ScriptedBackend(script)
    llm = LLM(backend)
    agent = Agent("solo", "sys", READ_TOOLS + [SUBMIT_WORK], handlers(Workspace(tmp_path)), llm, **kw)
    return agent, backend


def test_runs_tools_then_returns_submission(tmp_path):
    agent, backend = make_agent(tmp_path, [
        response(tool("read_file", path="f.txt")),
        response(text("done"), tool("submit_work", summary="ok", tests_passing=True)),
    ])
    result = agent.run("do it")
    assert result.output == {"summary": "ok", "tests_passing": True}
    assert result.turns == 2
    tool_result = backend.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "hello" in tool_result["content"]


def test_parallel_calls_answered_in_one_message(tmp_path):
    agent, backend = make_agent(tmp_path, [
        response(tool("read_file", path="f.txt"), tool("read_file", path="missing.txt")),
        response(tool("submit_work", summary="ok", tests_passing=False)),
    ])
    agent.run("go")
    results = backend.calls[1]["messages"][-1]["content"]
    assert [r["is_error"] for r in results] == [False, True]


def test_nudges_when_model_stops_without_submitting(tmp_path):
    agent, backend = make_agent(tmp_path, [
        response(text("I think I'm finished.")),
        response(tool("submit_work", summary="ok", tests_passing=True)),
    ])
    agent.run("go")
    assert "submit_work" in backend.calls[1]["messages"][-1]["content"]


def test_gives_up_after_repeated_nudges(tmp_path):
    agent, _ = make_agent(tmp_path, [response(text("no"))] * 3)
    with pytest.raises(AgentError, match="without calling submit_work"):
        agent.run("go")


def test_refusal_raises(tmp_path):
    agent, _ = make_agent(tmp_path, [response(stop="refusal")])
    with pytest.raises(AgentError, match="declined"):
        agent.run("go")


def test_max_turns(tmp_path):
    agent, _ = make_agent(tmp_path, [response(tool("list_files", path="."))] * 3, max_turns=3)
    with pytest.raises(AgentError, match="max_turns"):
        agent.run("go")
