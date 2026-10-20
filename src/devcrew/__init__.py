"""devcrew: a planner/coder/reviewer agent team built on the Claude API."""

from .pipeline import CrewConfig, RoleConfig, RunResult, run_crew, run_solo

__all__ = ["CrewConfig", "RoleConfig", "RunResult", "run_crew", "run_solo"]
__version__ = "0.1.0"
