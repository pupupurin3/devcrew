"""Benchmark harness: does the crew structure actually help, and at what cost?

Each task in `evals/tasks/<name>/` has:
  task.md   the request, written like a real issue
  repo/     the starting code, with a few visible tests
  hidden/   held-out tests the agents never see

A run copies `repo/` to a temp dir, lets an agent setup work on it, then
copies the hidden tests in and runs pytest. A task passes only if every
hidden and visible test passes and the visible tests were not edited.
That last check catches the classic failure where an agent "fixes" a
failing test by weakening it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .llm import MessagesBackend
from .pipeline import CrewConfig, RunResult, run_crew, run_solo


@dataclass
class Setup:
    """One agent configuration to benchmark."""

    name: str
    run: Callable[[Path, str, MessagesBackend], RunResult]


def default_setups() -> list[Setup]:
    return [
        Setup("solo-opus", lambda r, t, b: run_solo(r, t, b, model="claude-opus-5-5")),
        Setup("crew-opus", lambda r, t, b: run_crew(r, t, b, CrewConfig.uniform("claude-opus-5-5"))),
        Setup("solo-haiku", lambda r, t, b: run_solo(r, t, b, model="claude-haiku-5-5")),
        Setup("crew-haiku", lambda r, t, b: run_crew(r, t, b, CrewConfig.uniform("claude-haiku-5-5"))),
    ]


def _digest(root: Path) -> dict[str, str]:
    tests = root / "tests"
    if not tests.is_dir():
        return {}
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(tests.rglob("*.py"))
    }


def grade(work: Path, task_dir: Path, visible_before: dict[str, str]) -> dict[str, Any]:
    after = _digest(work)
    tampered = sorted(k for k, v in visible_before.items() if after.get(k) != v)
    for f in (task_dir / "hidden").glob("*.py"):
        shutil.copy(f, work / f.name)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "."],
        cwd=work, capture_output=True, text=True, timeout=300,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
    return {
        "passed": proc.returncode == 0 and not tampered,
        "tests_ok": proc.returncode == 0,
        "tampered_tests": tampered,
        "pytest": tail[0],
    }


def list_tasks(tasks_dir: Path, only: list[str] | None = None) -> list[Path]:
    tasks = sorted(p for p in tasks_dir.iterdir() if (p / "task.md").is_file())
    if only:
        tasks = [t for t in tasks if t.name in only]
    return tasks


def run_one(task_dir: Path, setup: Setup, backend: MessagesBackend) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"devcrew-{task_dir.name}-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(task_dir / "repo", work)
        before = _digest(work)
        task = (task_dir / "task.md").read_text()
        started = time.time()
        try:
            result = setup.run(work, task, backend).as_dict()
        except Exception as e:  # one broken run must not sink the whole benchmark
            result = {"error": f"{type(e).__name__}: {e}", "total": {"cost_usd": 0.0}}
        result["wall_s"] = round(time.time() - started, 1)
        result["grade"] = grade(work, task_dir, before)
        return {"task": task_dir.name, "setup": setup.name, **result}


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_setup: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_setup.setdefault(r["setup"], []).append(r)
    out = []
    for name, rs in by_setup.items():
        n = len(rs)
        out.append({
            "setup": name,
            "runs": n,
            "pass_rate": sum(r["grade"]["passed"] for r in rs) / n,
            "tampered": sum(bool(r["grade"]["tampered_tests"]) for r in rs),
            "self_reported_ok": sum(bool(r.get("approved")) for r in rs) / n,
            "mean_cost_usd": sum(r.get("total", {}).get("cost_usd", 0.0) for r in rs) / n,
            "mean_wall_s": sum(r["wall_s"] for r in rs) / n,
        })
    return out


def to_markdown(summary: list[dict[str, Any]]) -> str:
    lines = [
        "| Setup | Runs | Pass rate | Said done | Test tampering | Mean cost | Mean time |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['setup']} | {s['runs']} | {s['pass_rate']:.0%} | {s['self_reported_ok']:.0%} "
            f"| {s['tampered']} | ${s['mean_cost_usd']:.3f} | {s['mean_wall_s']:.0f}s |"
        )
    return "\n".join(lines)


def run_benchmark(
    tasks_dir: Path,
    backend: MessagesBackend,
    setups: list[Setup],
    repeats: int = 1,
    only: list[str] | None = None,
    out_dir: Path | None = None,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    rows = []
    for task_dir in list_tasks(tasks_dir, only):
        for setup in setups:
            for i in range(repeats):
                row = run_one(task_dir, setup, backend)
                row["repeat"] = i
                rows.append(row)
                g = row["grade"]
                log(f"{task_dir.name:<20} {setup.name:<12} #{i} "
                    f"{'PASS' if g['passed'] else 'FAIL'}  ${row.get('total', {}).get('cost_usd', 0):.3f}  "
                    f"{row['wall_s']}s  {g['pytest']}")
    summary = summarize(rows)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (out_dir / f"{stamp}.json").write_text(json.dumps({"rows": rows, "summary": summary}, indent=2))
        (out_dir / f"{stamp}.md").write_text(to_markdown(summary) + "\n")
    return summary
