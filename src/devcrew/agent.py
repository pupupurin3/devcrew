"""A minimal, explicit agent loop.

The loop is hand-written rather than delegated to an SDK helper so every
decision is visible: how stop reasons are handled, how parallel tool calls
are batched, and how an agent signals it is done (by calling a "submit_*"
tool whose input is the agent's structured result).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .llm import LLM
from .tools import TERMINAL_TOOLS, ToolError

MAX_NUDGES = 2


class AgentError(Exception):
    pass


@dataclass
class AgentResult:
    role: str
    output: dict[str, Any]
    turns: int
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Agent:
    role: str
    system: str
    tools: list[dict[str, Any]]
    handlers: dict[str, Callable[..., str]]
    llm: LLM
    max_turns: int = 40
    on_event: Callable[[dict[str, Any]], None] | None = None

    def _emit(self, trace: list[dict[str, Any]], event: dict[str, Any]) -> None:
        event = {"role": self.role, "t": round(time.time(), 3), **event}
        trace.append(event)
        if self.on_event:
            self.on_event(event)

    def _run_tool(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        handler = self.handlers.get(name)
        if handler is None:
            return f"unknown tool: {name}", True
        try:
            return handler(**args), False
        except ToolError as e:
            return str(e), True
        except Exception as e:  # surface unexpected failures to the model, keep going
            return f"{type(e).__name__}: {e}", True

    def run(self, task: str) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        trace: list[dict[str, Any]] = []
        terminal = next(t["name"] for t in self.tools if t["name"] in TERMINAL_TOOLS)
        nudges = 0

        for turn in range(1, self.max_turns + 1):
            response = self.llm.create(system=self.system, messages=messages, tools=self.tools)
            # Append the full content (thinking blocks included) unchanged, as
            # the API requires for multi-turn tool use with thinking.
            messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text" and block.text.strip():
                    self._emit(trace, {"type": "text", "text": block.text})

            if response.stop_reason == "refusal":
                raise AgentError(f"{self.role}: model declined the request")

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if response.stop_reason == "pause_turn":
                    continue
                if nudges >= MAX_NUDGES:
                    raise AgentError(f"{self.role}: finished without calling {terminal}")
                nudges += 1
                reason = "You ran out of output space." if response.stop_reason == "max_tokens" else ""
                messages.append({
                    "role": "user",
                    "content": f"{reason} Continue the task, and call `{terminal}` when you are done.".strip(),
                })
                continue

            # A terminal call ends the agent; its input is the structured result.
            for tu in tool_uses:
                if tu.name == terminal:
                    self._emit(trace, {"type": "submit", "tool": tu.name, "input": tu.input})
                    return AgentResult(self.role, dict(tu.input), turn, trace)

            # Run every tool call from this turn and return all results in one
            # user message, which keeps the model willing to batch calls.
            results = []
            for tu in tool_uses:
                output, is_error = self._run_tool(tu.name, dict(tu.input))
                self._emit(trace, {
                    "type": "tool", "tool": tu.name,
                    "input": json.dumps(tu.input)[:500], "error": is_error,
                    "output": output[:500],
                })
                results.append({
                    "type": "tool_result", "tool_use_id": tu.id,
                    "content": output, "is_error": is_error,
                })
            messages.append({"role": "user", "content": results})

        raise AgentError(f"{self.role}: hit max_turns ({self.max_turns}) without finishing")
