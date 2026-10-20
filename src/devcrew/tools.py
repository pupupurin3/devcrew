"""Tools the agents use to read and change a repository.

Every path is resolved inside a single workspace root, and commands run
without a shell from an allowlist, so an agent cannot wander outside the repo
or chain arbitrary shell commands. This is a guardrail, not a sandbox: run
untrusted tasks inside a container.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MAX_OUTPUT_CHARS = 12_000
MAX_READ_LINES = 2_000
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache"}

ALLOWED_COMMANDS = {
    "python", "python3", "pytest", "ls", "cat", "head", "tail", "wc",
    "git", "ruff", "mypy", "npm", "node", "npx", "make", "go", "cargo",
}
READ_ONLY_GIT = {"status", "diff", "log", "show", "ls-files"}


class ToolError(Exception):
    """Raised for bad tool input; reported to the model as an error result."""


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n... [{len(text) - limit} chars truncated] ...\n{text[-half:]}"


@dataclass
class Workspace:
    root: Path
    command_timeout: int = 120
    changed_files: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    def resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise ToolError(f"path escapes the workspace: {rel}")
        return path

    # -- read-only tools -------------------------------------------------

    def list_files(self, path: str = ".") -> str:
        base = self.resolve(path)
        if not base.is_dir():
            raise ToolError(f"not a directory: {path}")
        out = []
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(self.root)
            if any(part in SKIP_DIRS for part in rel.parts) or p.is_dir():
                continue
            out.append(str(rel))
            if len(out) >= 500:
                out.append("... (truncated at 500 files)")
                break
        return "\n".join(out) or "(empty)"

    def read_file(self, path: str) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        lines = p.read_text(errors="replace").splitlines()
        shown = lines[:MAX_READ_LINES]
        body = "\n".join(f"{i:>5}  {line}" for i, line in enumerate(shown, 1))
        if len(lines) > MAX_READ_LINES:
            body += f"\n... ({len(lines) - MAX_READ_LINES} more lines)"
        return body or "(empty file)"

    def search(self, pattern: str, path: str = ".") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"invalid regex: {e}") from e
        base = self.resolve(path)
        files = [base] if base.is_file() else sorted(base.rglob("*"))
        hits = []
        for f in files:
            rel = f.relative_to(self.root)
            if not f.is_file() or any(part in SKIP_DIRS for part in rel.parts):
                continue
            try:
                text = f.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {line.strip()}")
                    if len(hits) >= 100:
                        return "\n".join(hits) + "\n... (truncated at 100 matches)"
        return "\n".join(hits) or "no matches"

    def run_command(self, command: str) -> str:
        try:
            argv = shlex.split(command)
        except ValueError as e:
            raise ToolError(f"could not parse command: {e}") from e
        if not argv:
            raise ToolError("empty command")
        if argv[0] not in ALLOWED_COMMANDS:
            raise ToolError(
                f"'{argv[0]}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"
            )
        if argv[0] == "git" and (len(argv) < 2 or argv[1] not in READ_ONLY_GIT):
            raise ToolError(f"only read-only git subcommands: {', '.join(sorted(READ_ONLY_GIT))}")
        try:
            proc = subprocess.run(
                argv, cwd=self.root, capture_output=True, text=True,
                timeout=self.command_timeout,
            )
        except subprocess.TimeoutExpired:
            return f"command timed out after {self.command_timeout}s"
        except FileNotFoundError:
            raise ToolError(f"command not found: {argv[0]}")
        return _truncate(f"exit code: {proc.returncode}\n{proc.stdout}{proc.stderr}")

    # -- write tools ----------------------------------------------------

    def write_file(self, path: str, content: str) -> str:
        p = self.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        self.changed_files.add(str(p.relative_to(self.root)))
        return f"wrote {len(content)} chars to {path}"

    def edit_file(self, path: str, old_str: str, new_str: str) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        text = p.read_text()
        count = text.count(old_str)
        if count != 1:
            raise ToolError(
                f"old_str must appear exactly once in {path}, found {count} times; "
                "include more surrounding lines to make it unique"
            )
        p.write_text(text.replace(old_str, new_str, 1))
        self.changed_files.add(str(p.relative_to(self.root)))
        return f"edited {path}"


# -- tool schemas -------------------------------------------------------


def _schema(name: str, description: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
    }


_STR = {"type": "string"}

READ_TOOLS = [
    _schema("list_files", "List files under a directory of the repository (recursive).",
            {"path": {**_STR, "description": "Directory relative to repo root, e.g. '.'"}}),
    _schema("read_file", "Read a file with line numbers.",
            {"path": {**_STR, "description": "File path relative to repo root"}}),
    _schema("search", "Search file contents with a Python regex. Returns file:line: text.",
            {"pattern": _STR, "path": {**_STR, "description": "File or directory to search, e.g. '.'"}}),
    _schema("run_command",
            "Run a command in the repo root (no shell: no pipes, &&, or redirects). "
            "Use it to run the test suite, e.g. 'python -m pytest -q'.",
            {"command": _STR}),
]

WRITE_TOOLS = [
    _schema("write_file", "Create or overwrite a file with the full content given.",
            {"path": _STR, "content": _STR}),
    _schema("edit_file",
            "Replace one exact occurrence of old_str with new_str in a file. "
            "Prefer this over write_file for changes to existing files.",
            {"path": _STR, "old_str": _STR, "new_str": _STR}),
]

SUBMIT_PLAN = _schema(
    "submit_plan",
    "Submit the final implementation plan. Calling this ends your turn.",
    {
        "summary": {**_STR, "description": "One paragraph: what is wrong or missing and the approach"},
        "steps": {"type": "array", "items": _STR, "description": "Ordered, concrete steps naming files"},
        "acceptance_criteria": {"type": "array", "items": _STR,
                                "description": "Checkable conditions, including which tests must pass"},
    },
)

SUBMIT_WORK = _schema(
    "submit_work",
    "Report that the change is finished. Calling this ends your turn.",
    {
        "summary": {**_STR, "description": "What you changed and why"},
        "tests_passing": {"type": "boolean", "description": "Whether the test suite passed on your last run"},
    },
)

SUBMIT_REVIEW = _schema(
    "submit_review",
    "Submit your review verdict. Calling this ends your turn.",
    {
        "verdict": {"type": "string", "enum": ["approve", "request_changes"]},
        "issues": {"type": "array", "items": _STR,
                   "description": "Concrete problems the coder must fix; empty when approving"},
        "summary": _STR,
    },
)

TERMINAL_TOOLS = {"submit_plan", "submit_work", "submit_review"}


def handlers(ws: Workspace) -> dict[str, Callable[..., str]]:
    return {
        "list_files": ws.list_files,
        "read_file": ws.read_file,
        "search": ws.search,
        "run_command": ws.run_command,
        "write_file": ws.write_file,
        "edit_file": ws.edit_file,
    }
