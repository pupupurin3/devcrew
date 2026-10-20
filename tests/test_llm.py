from fakes import ScriptedBackend, response

from devcrew.llm import LLM, Usage


def test_request_shape_and_cost():
    backend = ScriptedBackend([response()])
    llm = LLM(backend, model="claude-opus-5-5", effort="high")
    llm.create(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    p = backend.calls[0]
    assert p["thinking"] == {"type": "adaptive"}
    assert p["output_config"] == {"effort": "high"}
    assert p["fallbacks"] == "default"
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    # 1000 in at $4/M + 100 out at $20/M
    assert abs(llm.usage.cost_usd - 0.006) < 1e-9


def test_no_fallbacks_on_haiku():
    backend = ScriptedBackend([response()])
    LLM(backend, model="claude-haiku-5-5").create(system="s", messages=[], tools=[])
    assert "fallbacks" not in backend.calls[0]


def test_usage_merge():
    a, b = Usage(input_tokens=1, cost_usd=0.5, calls=1), Usage(input_tokens=2, cost_usd=0.25, calls=2)
    a.merge(b)
    assert (a.input_tokens, a.calls, a.cost_usd) == (3, 3, 0.75)
