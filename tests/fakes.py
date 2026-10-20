"""A scripted stand-in for the Messages API so tests run offline and free."""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any, Callable

_ids = itertools.count()


def text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def tool(name: str, **inp: Any) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"toolu_{next(_ids)}", name=name, input=inp)


def response(*blocks: SimpleNamespace, stop: str | None = None) -> SimpleNamespace:
    if stop is None:
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )


class ScriptedBackend:
    """Replays responses in order, or calls `fn(params)` to build each one."""

    def __init__(self, script: list[SimpleNamespace] | None = None,
                 fn: Callable[[dict[str, Any]], SimpleNamespace] | None = None):
        self.script = list(script or [])
        self.fn = fn
        self.calls: list[dict[str, Any]] = []

    def create(self, **params: Any) -> SimpleNamespace:
        # Snapshot messages: the agent mutates the list after the call.
        self.calls.append({**params, "messages": list(params["messages"])})
        if self.fn:
            return self.fn(params)
        if not self.script:
            raise AssertionError("backend called more times than scripted")
        return self.script.pop(0)
