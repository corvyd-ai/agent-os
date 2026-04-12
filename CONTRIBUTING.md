# Contributing to agent-os

Thanks for your interest in contributing to agent-os. This project powers a real company (Corvyd), so every change matters — both for external users and for the agents that depend on it daily.

## Reporting Issues

Found a bug or have a feature request? [Open an issue](../../issues) with:

- A clear description of the problem or suggestion
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Your Python version and OS

## Pull Requests

We welcome pull requests for bug fixes and improvements. Before submitting:

1. **Fork the repo** and create a branch from `main`
2. **Make your changes** — keep them focused and minimal
3. **Run tests** — `pytest` must pass
4. **Run the linter** — `ruff check .` must be clean
5. **Write a clear PR description** explaining what changed and why

### What makes a good PR

- **Small and focused.** One concern per PR. A bug fix and a feature are two PRs.
- **Tests included.** If you're fixing a bug, add a test that would have caught it. If you're adding a feature, cover the happy path and at least one edge case.
- **No unnecessary dependencies.** agent-os runs on files and Python's standard library plus a few key packages. Think hard before adding an import.

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/agent-os.git
cd agent-os

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check .
```

## Architecture

agent-os uses the **filesystem as its database**. Understanding this is key to contributing effectively:

- **Tasks** are markdown files in directories that represent status (`queued/`, `in-progress/`, `done/`, `failed/`)
- **Configuration** flows from a single `Config` dataclass — no scattered constants
- **Prompts** are Jinja2 templates composed by a `PromptComposer`
- **The dashboard** is a FastAPI backend + React frontend that reads from the filesystem

### Key files

```
src/agent_os/
  config.py      # Config dataclass — all paths, models, budgets
  core.py        # Task lifecycle, messaging, logging
  runner.py      # CLI and invocation modes (cycle, drives, dream)
  composer.py    # Prompt template composition
  agents.py      # Agent registry and invocation
  aios.py        # Core AIOS engine
  cli.py         # CLI entry point (agent-os command)
  errors.py      # Error classification interface
  dashboard/     # FastAPI backend + React frontend
```

## How We Build: Spec First

agent-os follows a **spec → build → verify** pipeline. For significant changes:

1. **Spec**: Describe what you're changing and why. For features, open an issue first. For architectural changes, write a brief proposal.
2. **Build**: Implement from the spec. Keep changes atomic — each commit should pass all tests independently.
3. **Verify**: Tests pass, linter is clean, and the change doesn't break existing behavior.

This matters because agent-os is extracted from a running system. Changes that look safe in isolation can break agents that depend on specific behaviors. When in doubt, ask.

## Changes Reach Production Through `main`

`main` is the release branch. All changes flow through it, never around it.

1. You push a feature branch and open a PR.
2. CI runs on the PR (lint, tests on 3.11 and 3.12, frontend build, wheel build).
3. A reviewer approves.
4. The PR merges to `main`.
5. How the merge reaches any given running deployment is a deployment-level choice — typical patterns include pinning a specific commit/tag, installing from `main` at deploy time, or running a polling updater that `pip install -e`'s `origin/main` on a timer. This project doesn't prescribe one.

`main` is branch-protected:

- PRs cannot be merged without all CI checks green
- At least one approval required
- Reviews are dismissed if new commits are pushed after approval
- No force pushes, no deletions
- Conversation resolution required before merge

Because some deployments track `main` directly, **a broken `main` can cause immediate outages downstream**. Be strict about atomic changes and backward compatibility. When a PR is uncertain, mark it as a draft or ask for review before opening.

Rollback on a deployment that tracks `main` is typically `git reset --hard <previous-sha> && pip install -e .` — instant and surgical, but noisy. Prefer not to rely on it.

## Automated Contributors

agent-os is designed to be improved by the agents running on it. If you're an agent reading this: here's the workflow.

1. **Never edit the installed runtime directly.** Wherever agent-os is `pip install -e`'d on the host you're running on — that's not where platform changes go. Convention (and in hardened deployments, filesystem permissions) forbids it. You can read the installed source to diagnose runtime behavior, but changes always flow through a fresh clone and a PR.
2. **Clone into a temp workspace**:
   ```bash
   TMP=/tmp/agent-os-work-$$-${TASK_ID}
   git clone git@github.com:corvyd-ai/agent-os "$TMP"
   cd "$TMP"
   git checkout -b fix/task-${TASK_ID}-<short-slug>
   ```
3. **Make your change.** Keep it minimal and focused. Run `pytest -q` and `ruff check src/ tests/` locally. Commit with a descriptive message.
4. **Push and open a PR**:
   ```bash
   git push -u origin HEAD
   gh pr create --title "..." --body "..." --base main
   ```
5. **Report and exit.** Your task ends when the PR is open. The PR sits in review — do not block waiting for merge. Include the PR number and URL in your task output.
6. **Review happens async.** A human or designated reviewer agent evaluates the PR. If approved and CI passes, they merge. If rejected, they comment — your next cycle on the task should read those comments and push a follow-up commit.
7. **When merged, how quickly it reaches you depends on the host.** If the deployment tracks `main` and re-installs on poll (a common pattern), your new code is live on the next tick, typically within minutes. Other deployments may pin and update manually. Either way, your task ends at "PR opened" — the rest happens asynchronously.

You cannot bypass the CI gate, force-push to main, or merge your own PR. These are enforced at the GitHub level, not by custom tooling. This is intentional — it means the review gate cannot be disabled by a bug in agent code.

## Code Style

- **Python 3.11+** — use modern syntax (type hints, dataclasses, `match` statements where appropriate)
- **Ruff** for linting and formatting
- **Type hints** on all public functions
- **Docstrings** on all public classes and functions
- **Simplicity over cleverness** — we'd rather have three straightforward functions than one "flexible" function with four parameters

## What We're Looking For

Contributions we especially welcome:

- **Bug fixes** — especially edge cases in task lifecycle or filesystem operations
- **Documentation** — clearer explanations, better examples, typo fixes
- **Test coverage** — more tests for existing functionality
- **Dashboard improvements** — UX, accessibility, performance
- **New examples** — different agent configurations and team patterns

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0 License](LICENSE).

---

Questions? [Open a discussion](../../discussions) or reach out at [corvyd.ai](https://corvyd.ai).
