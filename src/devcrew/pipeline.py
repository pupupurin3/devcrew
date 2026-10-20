"""Orchestration: planner -> coder -> reviewer, with a bounded revision loop.

Each agent starts from a fresh context and receives only what it needs (the
task, the plan, the latest review). That keeps prompts short, makes every
hand-off inspectable, and stops one agent's mistakes from leaking into the
next agent's reasoning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import roles
from .agent import Agent, AgentError
from .llm import DEFAULT_MODEL, LLM, MessagesBackend, Usage
from .tools import READ_TOOLS, SUBMIT_PLAN, SUBMIT_REVIEW, SUBMIT_WORK, WRITE_TOOLS, Workspace, handlers


@dataclass
class RoleConfig:
    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_turns: int = 40


@dataclass
class CrewConfig:
    planner: RoleConfig = field(default_factory=lambda: RoleConfig(effort="high", max_turns=25))
    coder: RoleConfig = field(default_factory=lambda: RoleConfig(effort="high", max_turns=40))
    reviewer: RoleConfig = field(default_factory=lambda: RoleConfig(effort="medium", max_turns=25))
    max_review_rounds: int = 2
    fallbacks: bool = True

    @classmethod
    def uniform(cls, model: str, **kw: Any) -> "CrewConfig":
        return cls(
            planner=RoleConfig(model=model, effort="high", max_turns=25),
            coder=RoleConfig(model=model, effort="high", max_turns=40),
            reviewer=RoleConfig(model=model, effort="medium", max_turns=25),
            **kw,
        )


@dataclass
class RunResult:
    mode: str
    approved: bool
    rounds: int
    elapsed_s: float
    changed_files: list[str]
    usage: dict[str, Usage]
    outputs: list[dict[str, Any]]
    error: str | None = None

    @property
    def total_usage(self) -> Usage:
        total = Usage()
        for u in self.usage.values():
            total.merge(u)
        return total

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "approved": self.approved,
            "rounds": self.rounds,
            "elapsed_s": round(self.elapsed_s, 1),
            "changed_files": self.changed_files,
            "usage": {k: v.as_dict() for k, v in self.usage.items()},
            "total": self.total_usage.as_dict(),
            "outputs": self.outputs,
            "error": self.error,
        }


Listener = Callable[[dict[str, Any]], None]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


def format_plan(plan: dict[str, Any]) -> str:
    steps = "\n".join(f"{n}. {s}" for n, s in enumerate(plan.get("steps", []), 1))
    return (
        f"Summary: {plan.get('summary', '')}\n\nSteps:\n{steps}\n\n"
        f"Acceptance criteria:\n{_bullets(plan.get('acceptance_criteria', []))}"
    )


def run_crew(
    repo: Path,
    task: str,
    backend: MessagesBackend,
    config: CrewConfig | None = None,
    on_event: Listener | None = None,
) -> RunResult:
    config = config or CrewConfig()
    ws = Workspace(repo)
    h = handlers(ws)
    usage: dict[str, Usage] = {}
    outputs: list[dict[str, Any]] = []
    start = time.time()

    def make(role: str, rc: RoleConfig, system: str, tools: list[dict[str, Any]]) -> Agent:
        llm = LLM(backend, model=rc.model, effort=rc.effort, fallbacks=config.fallbacks,
                  usage=usage.setdefault(role, Usage()))
        return Agent(role, system, tools, h, llm, max_turns=rc.max_turns, on_event=on_event)

    def result(approved: bool, rounds: int, error: str | None = None) -> RunResult:
        return RunResult("crew", approved, rounds, time.time() - start,
                         sorted(ws.changed_files), usage, outputs, error)

    rounds = 0
    try:
        plan = make("planner", config.planner, roles.PLANNER, READ_TOOLS + [SUBMIT_PLAN]).run(
            f"Task:\n{task}"
        ).output
        outputs.append({"role": "planner", **plan})
        plan_text = format_plan(plan)

        feedback = ""
        for rounds in range(1, config.max_review_rounds + 1):
            coder_prompt = f"Task:\n{task}\n\nPlan:\n{plan_text}"
            if feedback:
                coder_prompt += f"\n\nThe reviewer requested changes to your previous attempt:\n{feedback}"
            work = make("coder", config.coder, roles.CODER, READ_TOOLS + WRITE_TOOLS + [SUBMIT_WORK]).run(
                coder_prompt
            ).output
            outputs.append({"role": "coder", "round": rounds, **work})

            review = make("reviewer", config.reviewer, roles.REVIEWER, READ_TOOLS + [SUBMIT_REVIEW]).run(
                f"Task:\n{task}\n\nPlan:\n{plan_text}\n\n"
                f"Files changed so far:\n{_bullets(sorted(ws.changed_files))}\n\n"
                f"Coder's report:\n{work.get('summary', '')}"
            ).output
            outputs.append({"role": "reviewer", "round": rounds, **review})
            if review.get("verdict") == "approve":
                return result(True, rounds)
            feedback = _bullets(review.get("issues", [])) + f"\n\n{review.get('summary', '')}"
        return result(False, rounds)
    except AgentError as e:
        return result(False, rounds, str(e))


def run_solo(
    repo: Path,
    task: str,
    backend: MessagesBackend,
    model: str = DEFAULT_MODEL,
    effort: str = "high",
    max_turns: int = 60,
    fallbacks: bool = True,
    on_event: Listener | None = None,
) -> RunResult:
    """Single-agent baseline used to measure what the crew structure adds."""
    ws = Workspace(repo)
    usage = Usage()
    start = time.time()
    llm = LLM(backend, model=model, effort=effort, fallbacks=fallbacks, usage=usage)
    agent = Agent("solo", roles.SOLO, READ_TOOLS + WRITE_TOOLS + [SUBMIT_WORK], handlers(ws), llm,
                  max_turns=max_turns, on_event=on_event)
    try:
        out = agent.run(f"Task:\n{task}").output
        return RunResult("solo", bool(out.get("tests_passing")), 1, time.time() - start,
                         sorted(ws.changed_files), {"solo": usage}, [{"role": "solo", **out}])
    except AgentError as e:
        return RunResult("solo", False, 1, time.time() - start, sorted(ws.changed_files),
                         {"solo": usage}, [], str(e))
