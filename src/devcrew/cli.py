"""Command-line entry point: `devcrew run`, `devcrew eval`."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .evals import default_setups, run_benchmark, to_markdown
from .llm import DEFAULT_MODEL, anthropic_backend
from .pipeline import CrewConfig, RoleConfig, RunResult, run_crew, run_solo


def _printer(trace_file: Path | None):
    fh = trace_file.open("w") if trace_file else None

    def on_event(e: dict[str, Any]) -> None:
        if fh:
            fh.write(json.dumps(e, default=str) + "\n")
            fh.flush()
        role = f"[{e['role']}]"
        if e["type"] == "tool":
            flag = " (error)" if e["error"] else ""
            print(f"{role:<11} {e['tool']} {e['input'][:100]}{flag}", file=sys.stderr)
        elif e["type"] == "submit":
            print(f"{role:<11} -> {e['tool']}", file=sys.stderr)

    return on_event


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _issue_task(repo: Path, number: int) -> tuple[str, str]:
    raw = subprocess.run(
        ["gh", "issue", "view", str(number), "--json", "title,body"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    issue = json.loads(raw)
    return issue["title"], f"GitHub issue #{number}: {issue['title']}\n\n{issue['body']}"


def _open_pr(repo: Path, branch: str, title: str, result: RunResult, issue: int | None) -> str:
    _git(repo, "checkout", "-b", branch)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", title)
    _git(repo, "push", "-u", "origin", branch)
    plan = next((o for o in result.outputs if o["role"] == "planner"), {})
    body = f"{plan.get('summary', '')}\n\nPlanned, implemented and reviewed by devcrew " \
           f"({result.rounds} review round(s), ${result.total_usage.cost_usd:.2f})."
    if issue:
        body += f"\n\nCloses #{issue}"
    return subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def cmd_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    title = "devcrew change"
    if args.issue:
        title, task = _issue_task(repo, args.issue)
    elif args.task_file:
        task = Path(args.task_file).read_text()
    elif args.task:
        task = args.task
    else:
        print("give a task, --task-file, or --issue", file=sys.stderr)
        return 2

    on_event = _printer(Path(args.trace) if args.trace else None)
    backend = anthropic_backend()
    if args.mode == "solo":
        result = run_solo(repo, task, backend, model=args.model, on_event=on_event)
    else:
        rc = lambda effort, turns: RoleConfig(model=args.model, effort=effort, max_turns=turns)
        config = CrewConfig(planner=rc("high", 25), coder=rc("high", 40),
                            reviewer=rc("medium", 25), max_review_rounds=args.rounds)
        result = run_crew(repo, task, backend, config, on_event=on_event)

    print(json.dumps(result.as_dict(), indent=2, default=str))
    if args.open_pr and result.approved and result.changed_files:
        default_branch = f"devcrew/issue-{args.issue}" if args.issue else "devcrew/change"
        branch = args.branch or default_branch
        print(_open_pr(repo, branch, title, result, args.issue))
    return 0 if result.approved else 1


def cmd_eval(args: argparse.Namespace) -> int:
    setups = default_setups()
    if args.setups:
        wanted = set(args.setups.split(","))
        setups = [s for s in setups if s.name in wanted]
    summary = run_benchmark(
        Path(args.tasks), anthropic_backend(), setups,
        repeats=args.repeats,
        only=args.only.split(",") if args.only else None,
        out_dir=Path(args.out),
    )
    print("\n" + to_markdown(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="devcrew", description="Planner/coder/reviewer agents for your repo.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the crew on a repository")
    r.add_argument("task", nargs="?", help="what to do, in plain language")
    r.add_argument("--repo", default=".", help="repository path (default: current directory)")
    r.add_argument("--task-file", help="read the task from a file")
    r.add_argument("--issue", type=int, help="use a GitHub issue of this repo as the task (needs gh)")
    r.add_argument("--mode", choices=["crew", "solo"], default="crew")
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--rounds", type=int, default=2, help="max coder/reviewer rounds")
    r.add_argument("--trace", help="write every agent event to this JSONL file")
    r.add_argument("--open-pr", action="store_true", help="on approval, commit to a branch and open a PR")
    r.add_argument("--branch", help="branch name for --open-pr")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("eval", help="benchmark agent setups on the eval tasks")
    e.add_argument("--tasks", default="evals/tasks")
    e.add_argument("--setups", help="comma-separated subset, e.g. solo-opus,crew-opus")
    e.add_argument("--only", help="comma-separated task names")
    e.add_argument("--repeats", type=int, default=1)
    e.add_argument("--out", default="evals/results")
    e.set_defaults(func=cmd_eval)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
