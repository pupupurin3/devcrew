"""Thin wrapper around the Anthropic Messages API.

Everything model-related lives here: which model each role uses, how hard it
thinks (effort), refusal fallbacks, and token/cost accounting. Agents only
see `LLM.create(...)`, which makes it trivial to swap in a scripted fake for
tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# USD per million tokens: (input, output, cache read).
PRICING: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}

DEFAULT_MODEL = "claude-opus-5-5"


@dataclass
class Usage:
    """Running token and cost totals across many API calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0

    def add(self, model: str, usage: Any) -> None:
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cread = getattr(usage, "cache_read_input_tokens", 0) or 0
        cwrite = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.input_tokens += inp
        self.output_tokens += out
        self.cache_read_tokens += cread
        self.cache_write_tokens += cwrite
        self.calls += 1
        p_in, p_out, p_read = PRICING.get(model, PRICING[DEFAULT_MODEL])
        # Cache writes bill at 1.25x the input rate for the 5-minute TTL.
        self.cost_usd += (
            inp * p_in + out * p_out + cread * p_read + cwrite * p_in * 1.25
        ) / 1_000_000

    def merge(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.calls += other.calls
        self.cost_usd += other.cost_usd

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "calls": self.calls,
            "cost_usd": round(self.cost_usd, 4),
        }


class MessagesBackend(Protocol):
    """The one SDK method we depend on (`client.beta.messages.create`)."""

    def create(self, **params: Any) -> Any: ...


@dataclass
class LLM:
    """Model settings for one agent role, plus its usage meter."""

    backend: MessagesBackend
    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 16000
    fallbacks: bool = True
    usage: Usage = field(default_factory=Usage)

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # The system prompt and tool list never change within a run, so a
            # single breakpoint on the system block caches tools + system.
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": messages,
            "tools": tools,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
        }
        if self.fallbacks and self.model != "claude-haiku-5-5":
            # On a safety-classifier refusal, the API re-runs the request on a
            # suitable fallback model instead of stopping the agent mid-task.
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        response = self.backend.create(**params)
        self.usage.add(self.model, response.usage)
        return response


def anthropic_backend() -> MessagesBackend:
    """Real backend. Credentials come from ANTHROPIC_API_KEY or `ant auth login`."""
    import anthropic

    return anthropic.Anthropic().beta.messages
