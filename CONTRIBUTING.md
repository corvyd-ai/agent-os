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

## The Blue/Green Safety Model

Corvyd (the reference implementation) runs agent-os through a blue/green deployment pipeline. This means:

- Every change is applied to an inactive copy first
- Smoke tests verify the change before promotion
- Rollback is instant if something breaks

You don't need to worry about this for your PRs — the maintainers handle promotion. But it explains why we're strict about backward compatibility and atomic changes.

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
