"""agent-os runner — invokes agents via the Claude Agent SDK.

Usage:
    agent-os cycle agent-001          # One cycle: tasks, messages, threads
    agent-os task agent-001 task-001  # Run a specific task
    agent-os standing-orders agent-001  # Standing orders if due
    agent-os drives agent-001         # Drive consultation
    agent-os dream agent-001          # Dream cycle
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)


# SDK error types for typed exception handling.
# These are internal SDK paths that may move — fallbacks ensure we degrade
# gracefully to the generic Exception handler if imports fail.
class _Unavailable(Exception):
    """Placeholder for SDK error types that couldn't be imported."""

    pass


try:
    from claude_agent_sdk._errors import (
        CLIConnectionError,
        CLIJSONDecodeError,
        CLINotFoundError,
        ProcessError,
    )
except ImportError:
    CLIConnectionError = _Unavailable
    CLINotFoundError = _Unavailable
    ProcessError = _Unavailable
    CLIJSONDecodeError = _Unavailable

from . import core as aios  # aliased as aios for minimal internal churn
from .budget import check_agent_budget, check_budget
from .composer import PromptComposer
from .config import Config, get_config
from .errors import ClaudeErrorClassifier
from .logger import get_logger
from .registry import load_agent
from .tools import AIOS_TOOL_NAMES, create_aios_tools_server

# --- Shared infrastructure ---

_error_classifier = ClaudeErrorClassifier()


def _now_iso() -> str:
    """Current time in configured timezone, ISO format."""
    cfg = get_config()
    return datetime.now(cfg.tz).isoformat()


def _classify_idle_cycle(agent_id: str, *, config: Config | None = None) -> str:
    """Classify why a cycle is idle for health metrics.

    Returns one of:
    - "starved": no queued tasks assigned to this agent at all
    - "blocked": tasks exist for this agent but dependencies unsatisfied
    - "idle": no tasks, messages, or threads (clean idle)
    """
    cfg = config or get_config()
    if not cfg.tasks_queued.exists():
        return "idle"

    has_any_tasks = False
    has_assigned = False
    for f in cfg.tasks_queued.iterdir():
        if not f.name.endswith(".md"):
            continue
        has_any_tasks = True
        meta, _ = aios._parse_frontmatter(f)
        assigned = meta.get("assigned_to")
        if not assigned or assigned == agent_id or agent_id.startswith(assigned + "-"):
            has_assigned = True
            # Check if this task is blocked on dependencies
            depends_on = meta.get("depends_on") or []
            if not depends_on or aios._deps_satisfied(depends_on, config=cfg):
                # There's a task we could run — shouldn't get here, but
                # race condition between _find_next_task and classification
                return "idle"

    if not has_any_tasks:
        return "idle"
    return "blocked" if has_assigned else "starved"


def _compute_expected_at(agent_id: str, order_name: str, cadence_hours: float, *, config: Config | None = None) -> str:
    """Compute when a standing order was expected to fire.

    Returns ISO timestamp of (last_cadence + cadence_hours), or "first_run"
    if no previous cadence record exists.
    """
    cfg = config or get_config()
    cadence_file = cfg.logs_dir / agent_id / f".cadence-{order_name}"
    if not cadence_file.exists():
        return "first_run"
    try:
        from datetime import timedelta

        last_run = datetime.fromisoformat(cadence_file.read_text().strip())
        expected = last_run + timedelta(hours=cadence_hours)
        return expected.isoformat()
    except (ValueError, OSError):
        return "unknown"


class StderrCapture:
    """Collects stderr lines from the SDK via the stderr callback."""

    def __init__(self, agent_id: str = "system"):
        self.lines: list[str] = []
        self._agent_id = agent_id

    def callback(self, line: str) -> None:
        self.lines.append(line)
        get_logger(self._agent_id).debug("sdk_stderr", line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def clear(self) -> None:
        self.lines.clear()


# --- Prompt helpers ---


def build_task_prompt(agent_config, task_meta: dict, task_body: str) -> str:
    """Build the user prompt for a task-based invocation."""
    title = task_meta.get("title", "Untitled task")
    task_id = task_meta.get("id", "unknown")
    return (
        f'Work on task {task_id}: "{title}"\n\n'
        f"The full task description is included in your system prompt. "
        f"Complete the work described, write outputs to the locations specified, "
        f"and report your findings/results clearly."
    )


def build_cycle_prompt(agent_config) -> str:
    """Build the user prompt for a cycle-based invocation."""
    return (
        f"Run your agent loop cycle as {agent_config.agent_id}. "
        "Check for any queued tasks assigned to you. "
        "If you find work, do it. If not, report that your cycle is idle."
    )


# --- SDK invocation ---


async def _streaming_prompt(text: str):
    """Wrap a string prompt as an async generator for MCP server compatibility.

    SDK MCP servers require streaming input mode — the bidirectional control
    protocol needs stdin to stay open. String prompts close stdin immediately.
    See: https://github.com/anthropics/claude-agent-sdk-python/issues/386
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
    }


def _make_options(
    agent_config,
    system_prompt: str,
    *,
    config: Config | None = None,
    cwd: Path | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    model: str | None = None,
    stderr_capture: StderrCapture | None = None,
    defer_complete: bool = False,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions with agent-os MCP tools injected.

    When ``defer_complete`` is True, the MCP ``complete_task`` tool becomes
    a no-op ack — the runner is then the single authority that moves the
    task to done/ after commit/push succeed. Used in workspace mode so a
    commit-phase failure does not leave an early "success" in done/.
    """
    cfg = config or get_config()

    prompt_bytes = len(system_prompt.encode("utf-8"))
    if prompt_bytes > 120_000:
        log = get_logger(agent_config.agent_id)
        log.warn(
            "prompt_size_warning",
            f"System prompt {prompt_bytes:,} bytes — approaching 128KB CLI limit",
            {"bytes": prompt_bytes, "agent": agent_config.agent_id},
        )

    aios_server = create_aios_tools_server(
        agent_id=agent_config.agent_id,
        config=cfg,
        defer_complete=defer_complete,
    )
    opts_kwargs = dict(
        system_prompt=system_prompt,
        allowed_tools=agent_config.allowed_tools + AIOS_TOOL_NAMES,
        permission_mode="bypassPermissions",
        model=model or agent_config.model,
        max_turns=max_turns or cfg.max_turns_per_invocation,
        max_budget_usd=max_budget_usd or cfg.max_budget_per_invocation_usd,
        cwd=str(cwd or cfg.company_root),
        mcp_servers={"aios": aios_server},
    )
    if stderr_capture is not None:
        opts_kwargs["stderr"] = stderr_capture.callback
    return ClaudeAgentOptions(**opts_kwargs)


def _find_product_code_dir(task_meta: dict, *, config: Config | None = None) -> Path | None:
    """Attempt to find the product code directory for a task."""
    cfg = config or get_config()
    product = task_meta.get("product")
    if not product:
        return None
    code_dir = cfg.company_root / "products" / product / "code"
    if code_dir.exists():
        return code_dir
    return None


def _run_quality_gates(code_dir: Path, *, config: Config | None = None) -> tuple[bool, str]:
    """Run the pre-done-checks script against a code directory."""
    cfg = config or get_config()
    script = cfg.pre_done_checks_script
    if not script.exists():
        return True, "[agent-os] Quality gate script not found — skipping"

    try:
        result = subprocess.run(
            ["bash", str(script), str(code_dir)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(code_dir),
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Quality gate checks timed out after 5 minutes"
    except Exception as e:
        return False, f"Quality gate check error: {e}"


def _ensure_api_key() -> None:
    """Ensure ANTHROPIC_API_KEY is set.

    By the time this is called, load_dotenv() has already loaded .env from
    the project root. This function checks the result and provides a clear
    error if the key is still missing.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return

    msg = (
        "No ANTHROPIC_API_KEY set. "
        "Add it to your .env file (ANTHROPIC_API_KEY=sk-ant-...) "
        "or set the environment variable."
    )
    get_logger("system").error("api_key_missing", msg)
    raise RuntimeError(msg)


async def _run_query(
    prompt_text: str,
    options: ClaudeAgentOptions,
    *,
    label: str,
    stderr_capture: StderrCapture | None = None,
    max_retries: int = 0,
) -> ResultMessage | None:
    """Run a Claude Agent SDK query with error classification and retry.

    Handles streaming output, error detection, retry for transient errors,
    and benign transport cleanup detection.
    """
    log = get_logger("system")
    last_exc = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            backoff = (2**attempt) + random.uniform(0, 1)
            log.info("sdk_retry", f"Retry {attempt}/{max_retries} after {backoff:.1f}s for {label}")
            await asyncio.sleep(backoff)
            if stderr_capture:
                stderr_capture.clear()

        result_msg = None
        tool_errors = 0
        api_errors = []

        try:
            async for message in query(prompt=_streaming_prompt(prompt_text), options=options):
                if isinstance(message, AssistantMessage):
                    if hasattr(message, "error") and message.error:
                        api_errors.append(message.error)
                        log.warn("sdk_api_error", f"API error in stream: {message.error}", {"label": label})

                    for block in message.content:
                        if hasattr(block, "text"):
                            print(block.text, flush=True)
                        elif hasattr(block, "name"):
                            print(f"  [tool: {block.name}]", flush=True)
                        if hasattr(block, "is_error") and block.is_error:
                            tool_errors += 1
                            error_text = getattr(block, "text", str(block))
                            log.warn("sdk_tool_error", f"Tool error: {error_text}", {"label": label})

                elif isinstance(message, ResultMessage):
                    result_msg = message
                    log.info(
                        "sdk_complete",
                        f"{label} complete: {message.subtype} ({message.num_turns} turns)",
                        {"tool_errors": tool_errors, "api_errors": len(api_errors), "turns": message.num_turns},
                    )

            return result_msg

        except (CLINotFoundError, CLIJSONDecodeError) as e:
            detail = _error_classifier.format_detail(e)
            raise RuntimeError(f"SDK error during {label}: {detail}") from e

        except ProcessError as e:
            last_exc = e
            detail = _error_classifier.format_detail(e)
            combined = f"{detail} {stderr_capture.text if stderr_capture else ''}"
            category, retryable = _error_classifier.classify(combined)

            if retryable and attempt < max_retries:
                log.warn("sdk_transient_error", f"Transient error during {label}: {detail}")
                continue

            if category == "permanent":
                log.error("sdk_permanent_error", f"Permanent error during {label} — not retrying")
            raise RuntimeError(f"SDK error during {label}: {detail}") from e

        except Exception as e:
            if result_msg is not None and _error_classifier.is_benign_cleanup(e):
                log.debug("sdk_cleanup", f"Benign transport cleanup after {label} (result already received)")
                return result_msg

            last_exc = e

            if CLIConnectionError is not _Unavailable and isinstance(e, CLIConnectionError):
                detail = _error_classifier.format_detail(e)
                combined = f"{detail} {stderr_capture.text if stderr_capture else ''}"
                _category, retryable = _error_classifier.classify(combined)
                if retryable and attempt < max_retries:
                    log.warn("sdk_transient_error", f"Transient error during {label}: {detail}")
                    continue

            if isinstance(e, ExceptionGroup):
                detail = _error_classifier.format_detail(e)
                combined = f"{detail} {stderr_capture.text if stderr_capture else ''}"
                _category, retryable = _error_classifier.classify(combined)
                if retryable and attempt < max_retries:
                    log.warn("sdk_transient_error", f"Transient error during {label}: {detail}")
                    continue

            detail = _error_classifier.format_detail(e)
            raise RuntimeError(f"SDK error during {label}: {detail}") from e

    detail = _error_classifier.format_detail(last_exc) if last_exc else "unknown error"
    raise RuntimeError(f"SDK error during {label} (after {max_retries} retries): {detail}") from last_exc


# --- Budget gate ---


def _check_budget_gate(agent_id: str, mode: str, *, config: Config | None = None) -> bool:
    """Check aggregate budget and per-agent cap. Returns True if OK to proceed."""
    cfg = config or get_config()

    log = get_logger(agent_id)

    budget = check_budget(config=cfg)
    if budget.circuit_breaker_tripped:
        log.warn(
            "budget_blocked",
            f"Circuit breaker tripped (${budget.daily_spent:.2f}/${budget.daily_cap:.2f}) — skipping {mode}",
            {"daily_spent": budget.daily_spent, "daily_cap": budget.daily_cap, "mode": mode},
        )
        return False

    within, agent_spent = check_agent_budget(agent_id, config=cfg)
    if not within:
        cap = cfg.agent_daily_caps.get(agent_id, 0)
        log.warn(
            "agent_budget_blocked",
            f"Agent daily cap reached (${agent_spent:.2f}/${cap:.2f}) — skipping {mode}",
            {"agent_spent": agent_spent, "agent_cap": cap, "mode": mode},
        )
        return False

    return True


# --- Invocation modes ---


async def run_agent(
    agent_id: str,
    task_id: str | None = None,
    *,
    config: Config | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> None:
    """Run an agent on a specific task."""
    cfg = config or get_config()

    if not _check_budget_gate(agent_id, "task", config=cfg):
        return

    # Pre-flight health gate: verify agent can write to its directories
    from .preflight import run_preflight

    preflight = run_preflight(agent_id, config=cfg)
    if not preflight.passed:
        log = get_logger(agent_id, config=cfg)
        log.error(
            "preflight_failed",
            f"Pre-flight checks failed: {preflight.summary}",
            {
                "checks": [
                    {"name": c.name, "detail": c.detail, "fix": c.fix_suggestion} for c in preflight.failed_checks
                ],
            },
        )
        from .notifications import NotificationEvent, send_notification

        send_notification(
            NotificationEvent(
                event_type="preflight_failed",
                severity="critical",
                title=f"Agent {agent_id} blocked by pre-flight check",
                detail=preflight.summary,
                agent_id=agent_id,
                refs={"failed_checks": len(preflight.failed_checks)},
            ),
            config=cfg,
        )
        return

    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    log = get_logger(agent_id)
    log.info(
        "agent_loaded",
        f"Loaded agent: {agent_config.agent_id} ({agent_config.role})",
        {"model": agent_config.model, "tools": agent_config.allowed_tools},
    )

    # Pre-flight: validate API key before claiming any task
    os.environ.pop("CLAUDECODE", None)
    _ensure_api_key()

    task_context = None
    task_meta = None

    if task_id:
        task_path = aios.claim_task(agent_config.agent_id, task_id, config=cfg)
        if not task_path:
            log.error("claim_failed", f"Could not claim task {task_id}")
            sys.exit(1)
        log.info("claimed_task", f"Claimed task: {task_path.name}", {"task_id": task_id})

        task_meta, task_body = aios._parse_frontmatter(task_path)
        task_context = task_path.read_text()

        aios.log_action(
            agent_config.agent_id,
            "claimed_task",
            f"Claimed {task_id}",
            {"task_id": task_id, "path": str(task_path)},
            config=cfg,
        )

        # Determine if this task uses workspace mode
        use_workspace = cfg.project_enabled and agent_config.role in cfg.builder_roles

        if use_workspace:
            await _run_agent_with_workspace(
                agent_config,
                task_id,
                task_meta,
                task_body,
                task_context,
                composer=composer,
                config=cfg,
                max_turns=max_turns,
                max_budget_usd=max_budget_usd,
            )
        else:
            await _run_agent_standard(
                agent_config,
                task_id,
                task_meta,
                task_body,
                task_context,
                composer=composer,
                config=cfg,
                max_turns=max_turns,
                max_budget_usd=max_budget_usd,
            )
    else:
        log.error("no_mode", "Must specify --task or --cycle")
        sys.exit(1)


async def _run_agent_standard(
    agent_config,
    task_id: str,
    task_meta: dict,
    task_body: str,
    task_context: str,
    *,
    composer: PromptComposer,
    config: Config,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> None:
    """Original task execution path — no workspace isolation."""
    cfg = config
    log = get_logger(agent_config.agent_id)

    try:
        prompt = build_task_prompt(agent_config, task_meta, task_body)
        system_prompt = composer.build_system_prompt(agent_config, task_context)

        log.info("sdk_invoke", "Invoking Claude Agent SDK", {"model": agent_config.model, "task": task_id})

        stderr_capture = StderrCapture(agent_config.agent_id)
        options = _make_options(
            agent_config,
            system_prompt,
            config=cfg,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            stderr_capture=stderr_capture,
        )

        result_msg = await _run_query(
            prompt,
            options,
            label=f"task {task_id}",
            stderr_capture=stderr_capture,
            max_retries=2,
        )
    except RuntimeError as e:
        error_detail = str(e)
        stderr_text = stderr_capture.text if "stderr_capture" in dir() else ""
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e, stderr_text, task=task_id)
        log.error("sdk_error", error_detail, {**error_refs, "task": task_id})
        aios.fail_task(task_id, error_detail, error_refs=error_refs, config=cfg)
        from .circuit_breaker import evaluate_breaker

        evaluate_breaker(agent_config.agent_id, config=cfg)
        sys.exit(1)
    except Exception as e:
        error_detail = f"Pre-flight error: {e}"
        log.error("preflight_error", error_detail, {"task": task_id})
        aios.fail_task(task_id, error_detail, config=cfg)
        from .circuit_breaker import evaluate_breaker

        evaluate_breaker(agent_config.agent_id, config=cfg)
        sys.exit(1)

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        duration = result_msg.duration_ms
        turns = result_msg.num_turns

        aios.log_cost(agent_config.agent_id, task_id, cost, duration, agent_config.model, turns, config=cfg)
        log.info(
            "sdk_complete",
            f"Done: ${cost:.4f}, {turns} turns, {duration}ms",
            {"task": task_id, "cost_usd": cost, "turns": turns, "duration_ms": duration},
        )

        if not result_msg.is_error:
            if agent_config.role in cfg.builder_roles and task_meta:
                code_dir = _find_product_code_dir(task_meta, config=cfg)
                if code_dir:
                    log.info("quality_gates_start", f"Running pre-done checks on {code_dir}", {"task_id": task_id})

                    gates_passed, gate_output = _run_quality_gates(code_dir, config=cfg)
                    print(gate_output, flush=True)

                    if gates_passed:
                        log.info("quality_gates_passed", "All quality gates passed", {"task_id": task_id})
                        aios.complete_task(task_id, config=cfg)
                        log.info("completed_task", f"Completed {task_id}", {"task_id": task_id})
                    else:
                        log.error(
                            "quality_gates_failed",
                            "Quality gates failed — task moved to failed/",
                            {"task_id": task_id, "output": gate_output[:500]},
                        )
                        aios.fail_task(task_id, f"Quality gates failed:\n{gate_output[-1000:]}", config=cfg)
                else:
                    aios.complete_task(task_id, config=cfg)
                    log.info(
                        "completed_task",
                        f"Completed {task_id} (quality gates: N/A)",
                        {"task_id": task_id},
                    )
            else:
                aios.complete_task(task_id, config=cfg)
                log.info("completed_task", f"Completed {task_id}", {"task_id": task_id})
        else:
            aios.fail_task(task_id, result_msg.result or "Agent returned error", config=cfg)
            log.error("task_failed", f"Task {task_id} moved to failed/", {"task_id": task_id})


async def _run_agent_with_workspace(
    agent_config,
    task_id: str,
    task_meta: dict,
    task_body: str,
    task_context: str,
    *,
    composer: PromptComposer,
    config: Config,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> None:
    """Workspace-aware task execution: worktree isolation, validation, commit, push.

    Failure policy: when the agent has produced uncommitted work and anything
    downstream fails (SDK error, commit-phase error, uncaught exception), the
    runner tries to salvage-commit the work so the branch preserves it. If the
    salvage commit itself fails (e.g. broken git identity), the worktree is
    left on disk for manual recovery rather than being deleted. The branch is
    only deleted when we're certain no agent work was produced (setup-phase
    failure, workspace-create failure).
    """
    from .notifications import NotificationEvent, send_notification
    from .workspace import (
        WorkspaceError,
        WorkspaceEvent,
        archive_workspace,
        cleanup_workspace,
        commit_workspace,
        create_workspace,
        has_uncommitted_changes,
        open_pull_request,
        push_workspace,
        salvage_commit,
        setup_workspace,
        validate_workspace,
    )

    # Event kinds that are worth waking a human up about (vs. info-only logs).
    # Agents discover these via `agent-os notifications events` — keep the
    # `event_type` strings in sync with notifications.KNOWN_EVENT_TYPES.
    _WORKSPACE_EVENT_NOTIFY: dict[str, tuple[str, str]] = {
        # event.kind                          -> (event_type, severity)
        "fetch_failed": ("workspace_fetch_failed", "warning"),
        "per_attempt_path_used": ("workspace_per_attempt_path_used", "warning"),
        "existing_worktree_cleanup_failed": ("workspace_cleanup_failed", "warning"),
        "cleanup_failed": ("workspace_cleanup_failed", "warning"),
        "existing_worktree_archive_failed": ("workspace_cleanup_failed", "warning"),
        "archive_move_failed": ("workspace_cleanup_failed", "warning"),
        "existing_worktree_archived": ("workspace_leftover_archived", "info"),
        "local_default_diverged": ("workspace_local_default_diverged", "warning"),
    }

    def _handle_workspace_events(events: list[WorkspaceEvent], phase: str) -> None:
        """Log every WorkspaceEvent and fire notifications for notable kinds.

        `phase` is a short label ("create", "cleanup", "archive") included in
        the log payload so agents tracing the event stream can tell *when*
        a thing happened, not just *what*.
        """
        for ev in events:
            log.info(
                f"workspace_event_{ev.kind}",
                ev.message,
                {"task_id": task_id, "phase": phase, **ev.detail},
            )
            mapping = _WORKSPACE_EVENT_NOTIFY.get(ev.kind)
            if not mapping:
                continue
            event_type, severity = mapping
            if severity == "info":
                # Log-only events (like normal leftover archival) don't need
                # to page a human — they're expected under retry scenarios.
                continue
            send_notification(
                NotificationEvent(
                    event_type=event_type,
                    severity=severity,
                    title=f"Workspace event for task {task_id}: {ev.kind}",
                    detail=ev.message + (f"\n\nDetail: {ev.detail}" if ev.detail else ""),
                    agent_id=agent_config.agent_id,
                    refs={"task_id": task_id, "phase": phase, "kind": ev.kind},
                ),
                config=cfg,
            )

    cfg = config
    log = get_logger(agent_config.agent_id)
    workspace = None

    def _preserve_on_failure(reason: str) -> None:
        """Best-effort work preservation after a failure.

        Runs on every failure path that could have uncommitted agent work in
        the worktree. Either salvage-commits the work (so the branch holds
        it for review) or — if the commit itself fails — leaves the worktree
        on disk and notifies the human.
        """
        if not workspace:
            return

        try:
            had_changes = has_uncommitted_changes(workspace)
        except Exception:
            had_changes = False

        if not had_changes:
            # No agent work to preserve. Clean up entirely — both worktree
            # and branch — since the branch would just be an empty pointer
            # to the default branch head.
            try:
                ok, steps, err = cleanup_workspace(workspace, delete_branch=True, config=cfg)
                if not ok:
                    _handle_workspace_events(
                        [
                            WorkspaceEvent(
                                kind="cleanup_failed",
                                message=f"Failed to clean empty workspace: {err}",
                                detail={
                                    "path": str(workspace.worktree_path),
                                    "steps": steps,
                                    "error": err or "",
                                },
                            )
                        ],
                        phase="cleanup",
                    )
            except Exception as e:
                log.error(
                    "workspace_cleanup_exception",
                    f"Cleanup raised: {e}",
                    {"task_id": task_id, "error": str(e)},
                )
            return

        salvaged_sha = None
        with contextlib.suppress(Exception):
            salvaged_sha = salvage_commit(
                workspace,
                task_meta,
                agent_config.agent_id,
                reason,
                config=cfg,
            )

        if not salvaged_sha:
            # Couldn't commit (e.g. missing git identity). Leave the worktree
            # in place so the human can recover manually — deleting it now
            # would throw away real agent work.
            log.error(
                "workspace_preserved",
                f"Could not salvage-commit; worktree preserved at {workspace.worktree_path}",
                {"task_id": task_id, "branch": workspace.branch, "reason": reason},
            )
            send_notification(
                NotificationEvent(
                    event_type="workspace_preserved",
                    severity="critical",
                    title=f"Worktree preserved for task {task_id} (could not salvage)",
                    detail=(
                        f"Task {task_id} failed ({reason}) with uncommitted agent work, "
                        f"and the runner could not commit the work on its behalf. "
                        f"The worktree has been left on disk for manual recovery.\n\n"
                        f"Worktree: `{workspace.worktree_path}`\n"
                        f"Branch:   `{workspace.branch}`\n\n"
                        f"Recover with: `cd {workspace.worktree_path}` then stage / commit manually. "
                        f"Most common cause: no git user.email / user.name configured."
                    ),
                    agent_id=agent_config.agent_id,
                    refs={"task_id": task_id, "branch": workspace.branch, "worktree": str(workspace.worktree_path)},
                ),
                config=cfg,
            )
            return

        log.warn(
            "workspace_salvaged",
            f"Salvaged partial work as {salvaged_sha[:8]} on {workspace.branch}",
            {"task_id": task_id, "branch": workspace.branch, "sha": salvaged_sha, "reason": reason},
        )

        push_ok, push_output = True, ""
        with contextlib.suppress(Exception):
            push_ok, push_output = push_workspace(workspace, config=cfg)

        send_notification(
            NotificationEvent(
                event_type="workspace_salvaged",
                severity="warning",
                title=f"Partial work preserved for task {task_id}",
                detail=(
                    f"Task {task_id} failed ({reason}) after the agent had made "
                    f"changes. The runner created a salvage commit on branch "
                    f"`{workspace.branch}` so the work isn't lost.\n\n"
                    f"Commit: {salvaged_sha[:8]}\n"
                    f"Push:   {'pushed to remote' if push_ok else 'local only — ' + push_output[:200]}\n\n"
                    f"The commit is flagged SALVAGE in its message and has NOT been validated."
                ),
                agent_id=agent_config.agent_id,
                refs={"task_id": task_id, "branch": workspace.branch, "sha": salvaged_sha},
            ),
            config=cfg,
        )

        # Branch preserves the salvage commit. Archive the worktree so the
        # files survive for forensics (same principle that makes successful
        # tasks land in _archive/) — agents and humans can inspect the full
        # state that led to the failure, not just the final commit.
        try:
            archive_path, archive_events = archive_workspace(workspace, "salvaged", config=cfg)
            if archive_path:
                log.info(
                    "workspace_archived",
                    f"Archived salvaged worktree to {archive_path}",
                    {"task_id": task_id, "archive": str(archive_path)},
                )
            _handle_workspace_events(archive_events, phase="archive")
        except Exception as e:
            log.error(
                "workspace_archive_failed",
                f"Salvage-archive failed: {e}",
                {"task_id": task_id, "error": str(e)},
            )

    try:
        # --- Create workspace ---
        log.info("workspace_create", f"Creating workspace for {task_id}", {"task_id": task_id})
        workspace = create_workspace(task_id, config=cfg)
        log.info(
            "workspace_created",
            f"Workspace ready: {workspace.branch} at {workspace.worktree_path} (attempt {workspace.attempt})",
            {
                "task_id": task_id,
                "branch": workspace.branch,
                "worktree": str(workspace.worktree_path),
                "attempt": workspace.attempt,
            },
        )
        # Surface any anomalies from create (leftover archived, fetch failed,
        # per-attempt path used). Logged for every event; notified for the
        # ones worth waking a human up over.
        _handle_workspace_events(workspace.events, phase="create")

        # --- Setup workspace ---
        if cfg.project_setup_commands:
            log.info("workspace_setup", "Running setup commands", {"task_id": task_id})
            ok, setup_output = setup_workspace(workspace, config=cfg)
            if not ok:
                log.error("workspace_setup_failed", "Setup commands failed", {"task_id": task_id})
                aios.fail_task(task_id, f"Workspace setup failed:\n{setup_output[-2000:]}", config=cfg)
                # Setup failed before the agent ran — no work to preserve.
                ok, steps, err = cleanup_workspace(workspace, delete_branch=True, config=cfg)
                if not ok:
                    _handle_workspace_events(
                        [
                            WorkspaceEvent(
                                kind="cleanup_failed",
                                message=f"Cleanup after setup-failure left state behind: {err}",
                                detail={
                                    "path": str(workspace.worktree_path),
                                    "steps": steps,
                                    "error": err or "",
                                },
                            )
                        ],
                        phase="cleanup",
                    )
                return

        # --- Build prompts with workspace context ---
        prompt = build_task_prompt(agent_config, task_meta, task_body)
        system_prompt = composer.build_system_prompt(
            agent_config,
            task_context,
            workspace_branch=workspace.branch,
            workspace_code_dir=str(workspace.code_dir),
        )

        stderr_capture = StderrCapture(agent_config.agent_id)
        options = _make_options(
            agent_config,
            system_prompt,
            config=cfg,
            cwd=workspace.code_dir,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            stderr_capture=stderr_capture,
            defer_complete=True,
        )

        # --- Execute with validation retry loop ---
        max_retries = cfg.project_validate_max_retries if cfg.project_validate_on_failure == "retry" else 0
        validate_output = ""
        max_turns_exhausted = False  # Did the last SDK call end in error_max_turns?

        for attempt in range(max_retries + 1):
            if attempt > 0:
                retry_prompt = (
                    f"Your previous work failed validation (attempt {attempt}/{max_retries + 1}).\n\n"
                    f"Validation output:\n```\n{validate_output[-3000:]}\n```\n\n"
                    f"Fix the issues and try again."
                )
                log.info(
                    "workspace_retry",
                    f"Validation retry {attempt}/{max_retries}",
                    {"task_id": task_id, "attempt": attempt},
                )
                result_msg = await _run_query(
                    retry_prompt,
                    options,
                    label=f"task {task_id} (retry {attempt})",
                    stderr_capture=stderr_capture,
                    max_retries=2,
                )
            else:
                log.info(
                    "sdk_invoke",
                    "Invoking Claude Agent SDK (workspace mode)",
                    {
                        "model": agent_config.model,
                        "task": task_id,
                        "branch": workspace.branch,
                    },
                )
                result_msg = await _run_query(
                    prompt,
                    options,
                    label=f"task {task_id}",
                    stderr_capture=stderr_capture,
                    max_retries=2,
                )

            max_turns_exhausted = False  # reset each attempt

            if result_msg:
                cost = result_msg.total_cost_usd or 0.0
                aios.log_cost(
                    agent_config.agent_id,
                    task_id,
                    cost,
                    result_msg.duration_ms,
                    agent_config.model,
                    result_msg.num_turns,
                    config=cfg,
                )
                log.info(
                    "sdk_complete",
                    f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
                    {
                        "task": task_id,
                        "cost_usd": cost,
                        "attempt": attempt,
                        "subtype": result_msg.subtype,
                    },
                )

                if result_msg.is_error:
                    subtype = result_msg.subtype or ""
                    if subtype == "error_max_turns":
                        # Agent didn't finish under its own steam, but the
                        # work in the worktree may still be valid. Fall
                        # through to validation — if it passes, we'll submit
                        # for review instead of marking done or failed.
                        max_turns_exhausted = True
                        log.warn(
                            "sdk_max_turns",
                            f"Agent hit turn limit ({result_msg.num_turns} turns) — validating partial work",
                            {"task_id": task_id, "turns": result_msg.num_turns},
                        )
                    else:
                        # Generic agent error — preserve any in-flight work.
                        aios.fail_task(
                            task_id,
                            result_msg.result or f"Agent returned error (subtype={subtype})",
                            error_refs={"subtype": subtype, "num_turns": result_msg.num_turns},
                            config=cfg,
                        )
                        log.error(
                            "task_failed",
                            f"Task {task_id} agent error (subtype={subtype})",
                            {"task_id": task_id, "subtype": subtype},
                        )
                        _preserve_on_failure(f"agent error: {subtype or 'unknown'}")
                        return

            # --- Validate ---
            if cfg.project_validate_commands:
                log.info("workspace_validate", f"Running validation (attempt {attempt + 1})", {"task_id": task_id})
                valid, validate_output = validate_workspace(workspace, config=cfg)
                if valid:
                    log.info("workspace_validate_passed", "Validation passed", {"task_id": task_id})
                    break
                else:
                    log.warn(
                        "workspace_validate_failed",
                        f"Validation failed (attempt {attempt + 1})",
                        {
                            "task_id": task_id,
                            "output": validate_output[:500],
                        },
                    )
            else:
                break  # No validation commands — accept immediately
        else:
            # All retries exhausted — preserve the failing work so a human
            # can see what broke instead of hunting through a deleted branch.
            aios.fail_task(
                task_id,
                f"Validation failed after {max_retries + 1} attempts:\n{validate_output[-2000:]}",
                config=cfg,
            )
            log.error("workspace_validate_exhausted", "Validation retries exhausted", {"task_id": task_id})
            _preserve_on_failure(f"validation failed after {max_retries + 1} attempts")
            return

        # --- Commit + Push ---
        try:
            sha = commit_workspace(workspace, task_meta, agent_config.agent_id, config=cfg)
        except WorkspaceError as e:
            # Commit-phase failure: the agent's work is in the worktree but
            # can't be committed (usually missing git identity). Preserve it.
            log.error("workspace_commit_failed", f"Commit failed: {e}", {"task_id": task_id})
            aios.fail_task(task_id, f"Commit failed: {e}", config=cfg)
            _preserve_on_failure(f"commit failed: {e}")
            from .circuit_breaker import evaluate_breaker

            evaluate_breaker(agent_config.agent_id, config=cfg)
            return

        if sha:
            log.info("workspace_committed", f"Committed {sha[:8]}", {"task_id": task_id, "sha": sha})
            push_ok, push_output = push_workspace(workspace, config=cfg)
            if push_ok:
                log.info("workspace_pushed", f"Pushed {workspace.branch}", {"task_id": task_id})
                # --- Open a pull request (GitHub only; non-fatal) ---
                pr_ok, pr_url, pr_message = open_pull_request(workspace, task_meta, agent_config.agent_id, config=cfg)
                if pr_ok and pr_url:
                    log.info(
                        "workspace_pr_opened",
                        f"Opened PR: {pr_url}",
                        {"task_id": task_id, "branch": workspace.branch, "url": pr_url},
                    )
                    send_notification(
                        NotificationEvent(
                            event_type="workspace_pr_opened",
                            severity="info",
                            title=f"PR opened for task {task_id}",
                            detail=(
                                f"Task {task_id} completed and a pull request was opened.\n\n"
                                f"URL: {pr_url}\n"
                                f"Branch: `{workspace.branch}`\n"
                                f"Commit: {sha[:8]}"
                            ),
                            agent_id=agent_config.agent_id,
                            refs={
                                "task_id": task_id,
                                "branch": workspace.branch,
                                "url": pr_url,
                                "sha": sha,
                            },
                        ),
                        config=cfg,
                    )
                elif pr_ok:
                    # Intentional skip — not an error, but log so the reason
                    # is discoverable ("PR disabled", "non-GitHub remote", etc).
                    log.info(
                        "workspace_pr_skipped",
                        f"PR creation skipped: {pr_message}",
                        {"task_id": task_id, "branch": workspace.branch, "reason": pr_message},
                    )
                else:
                    log.error(
                        "workspace_pr_failed",
                        f"PR creation failed (non-fatal): {pr_message}",
                        {"task_id": task_id, "branch": workspace.branch, "error": pr_message},
                    )
                    send_notification(
                        NotificationEvent(
                            event_type="workspace_pr_failed",
                            severity="warning",
                            title=f"PR creation failed for task {task_id}",
                            detail=(
                                f"Branch `{workspace.branch}` was pushed successfully but the "
                                f"follow-up `gh pr create` call failed. Task is still marked "
                                f"done — the branch is on the remote and a PR can be opened "
                                f"manually.\n\n"
                                f"Error:\n{pr_message[:500]}"
                            ),
                            agent_id=agent_config.agent_id,
                            refs={"task_id": task_id, "branch": workspace.branch, "sha": sha},
                        ),
                        config=cfg,
                    )
            else:
                # Push failure is non-fatal for THIS task (the commit is in
                # the agent branch locally), but if nothing ever pushes, work
                # piles up invisibly. Fire a critical notification so the
                # human notices now, not when they finally check `git log`.
                log.error(
                    "workspace_push_failed",
                    f"Push failed (non-fatal): {push_output[:200]}",
                    {"task_id": task_id, "branch": workspace.branch},
                )
                send_notification(
                    NotificationEvent(
                        event_type="workspace_push_failed",
                        severity="critical",
                        title=f"Push failed for task {task_id}",
                        detail=(
                            f"Branch `{workspace.branch}` was committed locally but the push to remote failed. "
                            f"Work will pile up in the repo until push auth is fixed.\n\n"
                            f"Error:\n{push_output[:400]}\n\n"
                            f"Diagnose with: agent-os project check"
                        ),
                        agent_id=agent_config.agent_id,
                        refs={"task_id": task_id, "branch": workspace.branch},
                    ),
                    config=cfg,
                )
        else:
            log.info("workspace_no_changes", "No code changes to commit", {"task_id": task_id})

        # --- Resolve task ---
        if max_turns_exhausted:
            # Work passed validation but the agent never signalled completion
            # under its own control. Route to in-review so a human signs off
            # rather than trusting the runner's inference.
            aios.submit_for_review(task_id, config=cfg)
            log.warn(
                "task_submitted_for_review",
                f"Task {task_id} hit turn limit but validation passed — submitted for review",
                {"task_id": task_id, "branch": workspace.branch, "sha": sha},
            )
            send_notification(
                NotificationEvent(
                    event_type="task_submitted_for_review",
                    severity="warning",
                    title=f"Task {task_id} submitted for review (turn limit hit)",
                    detail=(
                        f"Task {task_id} ran out of turns but the resulting work passed "
                        f"validation. The runner committed and submitted it for review "
                        f"rather than marking it done — the agent did not explicitly "
                        f"confirm completion.\n\n"
                        f"Branch: `{workspace.branch}`\n"
                        f"{f'Commit: {sha[:8]}' if sha else 'No code changes to commit'}\n\n"
                        f"Review on the branch, then mark done or iterate."
                    ),
                    agent_id=agent_config.agent_id,
                    refs={"task_id": task_id, "branch": workspace.branch, "sha": sha or ""},
                ),
                config=cfg,
            )
            archive_path, archive_events = archive_workspace(workspace, "in_review", config=cfg)
            if archive_path:
                log.info(
                    "workspace_archived",
                    f"Archived worktree to {archive_path}",
                    {"task_id": task_id, "archive": str(archive_path)},
                )
            _handle_workspace_events(archive_events, phase="archive")
        else:
            aios.complete_task(task_id, config=cfg)
            log.info("completed_task", f"Completed {task_id}", {"task_id": task_id, "branch": workspace.branch})
            archive_path, archive_events = archive_workspace(workspace, "completed", config=cfg)
            if archive_path:
                log.info(
                    "workspace_archived",
                    f"Archived worktree to {archive_path}",
                    {"task_id": task_id, "archive": str(archive_path)},
                )
            _handle_workspace_events(archive_events, phase="archive")

    except WorkspaceError as e:
        log.error("workspace_error", str(e), {"task_id": task_id})
        aios.fail_task(task_id, f"Workspace error: {e}", config=cfg)
        _preserve_on_failure(f"workspace error: {e}")
        from .circuit_breaker import evaluate_breaker

        evaluate_breaker(agent_config.agent_id, config=cfg)
    except RuntimeError as e:
        error_detail = str(e)
        log.error("sdk_error", error_detail, {"task_id": task_id})
        aios.fail_task(task_id, error_detail, config=cfg)
        _preserve_on_failure(f"SDK error: {error_detail[:200]}")
        from .circuit_breaker import evaluate_breaker

        evaluate_breaker(agent_config.agent_id, config=cfg)
        sys.exit(1)
    except Exception as e:
        error_detail = f"Workspace task error: {e}"
        log.error("workspace_task_error", error_detail, {"task_id": task_id})
        aios.fail_task(task_id, error_detail, config=cfg)
        _preserve_on_failure(f"workspace task error: {str(e)[:200]}")
        from .circuit_breaker import evaluate_breaker

        evaluate_breaker(agent_config.agent_id, config=cfg)
        sys.exit(1)


async def run_drive_consultation(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """Consult drives — agents think about what the company needs."""
    cfg = config or get_config()

    if not _check_budget_gate(agent_id, "drive_consultation", config=cfg):
        return

    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    log = get_logger(agent_key)

    # Idle-exit gate: skip if nothing has changed since last consultation
    proposals = aios.list_active_proposals(config=cfg)
    drives_mtime = cfg.drives_file.stat().st_mtime if cfg.drives_file.exists() else 0
    last_consultation = aios.get_last_cadence(agent_key, "drive-consultation", config=cfg)
    if not proposals and drives_mtime < last_consultation:
        log.info("drive_consultation_idle", "No proposals or drive changes since last consultation, skipping ($0)")
        return

    expected_at = _now_iso()  # Drive consultations run on cron schedule; expected = now
    log.info("drive_consultation_start", "Consulting drives (scheduled)", {"expected_at": expected_at})

    try:
        journal = aios.read_journal(agent_key, max_entries=5, config=cfg)
        journal_context = ""
        if journal:
            journal_context = f"\n\n# Your Recent Journal Entries\n\n{journal}"

        system_prompt = composer.build_system_prompt(agent_config) + journal_context

        company_drives = aios.read_drives(config=cfg)
        proposals = aios.list_active_proposals(config=cfg)
        if proposals:
            proposals_text = "\n\n".join(
                f"### {meta.get('title', 'Untitled')} "
                f"(by {meta.get('proposed_by', 'unknown')}, {meta.get('date', '?')})\n\n"
                f"**File**: {path.name}\n\n{body}"
                for meta, body, path in proposals
            )
        else:
            proposals_text = "(No active proposals)"

        prompt = composer.render_template(
            "drive_consultation.jinja2",
            company_drives=company_drives or "(No company drives document yet)",
            active_proposals=proposals_text,
            agent_id=agent_key,
        )

        os.environ.pop("CLAUDECODE", None)
        _ensure_api_key()

        stderr_capture = StderrCapture(agent_key)
        options = _make_options(
            agent_config,
            system_prompt,
            config=cfg,
            max_turns=max_turns or cfg.drive_consultation_max_turns,
            max_budget_usd=max_budget_usd or cfg.drive_consultation_max_budget_usd,
            stderr_capture=stderr_capture,
        )

        result_msg = await _run_query(
            prompt,
            options,
            label=f"drive consultation ({agent_key})",
            stderr_capture=stderr_capture,
            max_retries=1,
        )
    except Exception as e:
        stderr_text = stderr_capture.text if "stderr_capture" in dir() else ""
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e if e.__cause__ else e, stderr_text)
        log.error("drive_consultation_error", str(e), error_refs)
        return

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        aios.log_cost(
            agent_key,
            "drive-consultation",
            cost,
            result_msg.duration_ms,
            agent_config.model,
            result_msg.num_turns,
            config=cfg,
        )
        log.info(
            "drive_consultation_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns},
        )

    log.info("drive_consultation_done", "Drive consultation finished")


async def run_dream_cycle(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """Nightly dream cycle — agents reorganize their memory state."""
    cfg = config or get_config()

    if not _check_budget_gate(agent_id, "dream_cycle", config=cfg):
        return

    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    log = get_logger(agent_key)
    log.info("dream_start", "Entering dream cycle (nightly memory reorganization)")

    try:
        system_prompt = composer.build_system_prompt(agent_config)

        prompt = composer.render_template("dream.jinja2", agent_id=agent_key)

        os.environ.pop("CLAUDECODE", None)
        _ensure_api_key()

        dream_model = cfg.dream_model
        log.debug("dream_model", f"Dream model: {dream_model}", {"model": dream_model})

        stderr_capture = StderrCapture(agent_key)
        options = _make_options(
            agent_config,
            system_prompt,
            config=cfg,
            max_turns=max_turns or cfg.dream_max_turns,
            max_budget_usd=max_budget_usd or cfg.dream_max_budget_usd,
            model=dream_model,
            stderr_capture=stderr_capture,
        )

        result_msg = await _run_query(
            prompt,
            options,
            label=f"dream cycle ({agent_key})",
            stderr_capture=stderr_capture,
            max_retries=1,
        )
    except Exception as e:
        stderr_text = stderr_capture.text if "stderr_capture" in dir() else ""
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e if e.__cause__ else e, stderr_text)
        log.error("dream_error", str(e), error_refs)
        return

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        aios.log_cost(
            agent_key, "dream-cycle", cost, result_msg.duration_ms, dream_model, result_msg.num_turns, config=cfg
        )
        log.info(
            "dream_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns},
        )

    log.info("dream_done", "Dream cycle finished")


def _emit_jsonl(data: dict) -> None:
    """Print a single JSON line to stdout, flushed. Used by interactive mode."""
    print(json.dumps(data), flush=True)


async def run_interactive(
    agent_id: str,
    *,
    conversation_json: str,
    config: Config | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> None:
    """Run an interactive conversation turn with the operator."""
    cfg = config or get_config()
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    try:
        conversation = json.loads(conversation_json)
    except json.JSONDecodeError as e:
        _emit_jsonl({"type": "error", "message": f"Invalid conversation JSON: {e}"})
        return

    turns = conversation.get("turns", [])
    new_message = conversation.get("message", "")
    conversation_id = conversation.get("conversation_id", "unknown")

    if not new_message.strip():
        _emit_jsonl({"type": "error", "message": "Empty message"})
        return

    turn_number = len(turns) // 2 + 1

    system_prompt = composer.build_system_prompt(agent_config)

    preamble = composer.render_template(
        "interactive.jinja2",
        agent_name=agent_config.name,
        agent_role=agent_config.role,
        turn_number=turn_number,
    )

    prompt_parts = [preamble]

    if turns:
        prompt_parts.append("## Conversation So Far\n")
        for turn in turns:
            role_label = "Operator" if turn["role"] == "human" else "You"
            prompt_parts.append(f"**{role_label}**: {turn['content']}\n")

    prompt_parts.append(f"## Current Message\n\n**Operator**: {new_message}")

    prompt = "\n\n".join(prompt_parts)

    os.environ.pop("CLAUDECODE", None)
    _ensure_api_key()

    options = _make_options(
        agent_config,
        system_prompt,
        config=cfg,
        max_turns=max_turns or cfg.interactive_max_turns,
        max_budget_usd=max_budget_usd or cfg.interactive_max_budget_usd,
    )

    start_time = time.monotonic()

    try:
        result_msg = None
        async for message in query(prompt=_streaming_prompt(prompt), options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, "text"):
                        _emit_jsonl({"type": "text", "text": block.text})
                    elif hasattr(block, "name"):
                        input_preview = ""
                        if hasattr(block, "input") and isinstance(block.input, dict):
                            preview_keys = ["file_path", "command", "pattern", "query", "url"]
                            for k in preview_keys:
                                if k in block.input:
                                    input_preview = str(block.input[k])[:200]
                                    break
                        _emit_jsonl(
                            {
                                "type": "tool_use",
                                "name": block.name,
                                "input_preview": input_preview,
                            }
                        )
            elif isinstance(message, ResultMessage):
                result_msg = message
    except Exception as e:
        if result_msg is not None and _error_classifier.is_benign_cleanup(e):
            pass
        else:
            _emit_jsonl({"type": "error", "message": f"Agent error: {_error_classifier.format_detail(e)}"})
            aios.log_action(agent_key, "interactive_error", str(e), {"conversation_id": conversation_id}, config=cfg)
            return

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        turns_used = result_msg.num_turns
        duration = result_msg.duration_ms or elapsed_ms

        aios.log_cost(agent_key, "interactive", cost, duration, agent_config.model, turns_used, config=cfg)
        aios.log_action(
            agent_key,
            "interactive_conversation",
            f"Interactive turn {turn_number}: ${cost:.4f}, {turns_used} turns",
            {"conversation_id": conversation_id, "turn_number": turn_number, "cost_usd": cost, "turns": turns_used},
            config=cfg,
        )

        _emit_jsonl(
            {
                "type": "complete",
                "cost_usd": round(cost, 4),
                "duration_ms": duration,
                "num_turns": turns_used,
            }
        )
    else:
        _emit_jsonl(
            {
                "type": "complete",
                "cost_usd": 0.0,
                "duration_ms": elapsed_ms,
                "num_turns": 0,
            }
        )


async def run_thread_response(agent_id: str, pending_threads: list, *, config: Config | None = None) -> None:
    """Respond to conversation threads where this agent's input is awaited."""
    cfg = config or get_config()
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    log = get_logger(agent_key)
    log.info(
        "thread_response_start",
        f"Responding to {len(pending_threads)} thread(s)",
        {"thread_count": len(pending_threads)},
    )

    thread_lines = []
    for meta, _body, path in pending_threads:
        topic = meta.get("topic", "Untitled")
        participants = meta.get("participants", [])
        thread_lines.append(f"- **{topic}** (participants: {', '.join(participants)})\n  Path: {path}")

    prompt = composer.render_template(
        "thread_response.jinja2",
        thread_list="\n".join(thread_lines),
    )

    system_prompt = composer.build_system_prompt(agent_config)

    os.environ.pop("CLAUDECODE", None)
    _ensure_api_key()

    stderr_capture = StderrCapture(agent_key)
    options = _make_options(
        agent_config,
        system_prompt,
        config=cfg,
        max_turns=cfg.thread_response_max_turns,
        max_budget_usd=cfg.thread_response_max_budget_usd,
        stderr_capture=stderr_capture,
    )

    try:
        result_msg = await _run_query(
            prompt,
            options,
            label=f"thread response ({agent_key})",
            stderr_capture=stderr_capture,
            max_retries=1,
        )
    except RuntimeError as e:
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e, stderr_capture.text)
        log.error("thread_response_error", str(e), error_refs)
        return

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        aios.log_cost(
            agent_key,
            "thread-response",
            cost,
            result_msg.duration_ms,
            agent_config.model,
            result_msg.num_turns,
            config=cfg,
        )
        log.info(
            "thread_response_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns},
        )


async def run_message_triage(agent_id: str, *, config: Config | None = None) -> None:
    """Process unread inbox messages — lightweight triage using Sonnet."""
    cfg = config or get_config()
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    log = get_logger(agent_key)

    inbox_msgs = aios.read_inbox(agent_key, config=cfg)
    if not inbox_msgs:
        return

    log.info("message_triage_start", f"Triaging {len(inbox_msgs)} message(s)", {"count": len(inbox_msgs)})

    msg_parts = []
    for meta, body, path in inbox_msgs:
        sender = meta.get("from", "unknown")
        subject = meta.get("subject", "No subject")
        date = meta.get("date", "?")
        msg_parts.append(f"### {subject}\n**From**: {sender} | **Date**: {date} | **Path**: {path}\n\n{body}")

    prompt = composer.render_template(
        "message_triage.jinja2",
        msg_count=len(inbox_msgs),
        messages_text="\n\n---\n\n".join(msg_parts),
        agent_id=agent_key,
    )

    system_prompt = composer.build_system_prompt(agent_config)

    os.environ.pop("CLAUDECODE", None)
    _ensure_api_key()

    stderr_capture = StderrCapture(agent_key)
    options = _make_options(
        agent_config,
        system_prompt,
        config=cfg,
        max_turns=cfg.message_triage_max_turns,
        max_budget_usd=cfg.message_triage_max_budget_usd,
        model=cfg.message_triage_model,
        stderr_capture=stderr_capture,
    )

    try:
        result_msg = await _run_query(
            prompt,
            options,
            label=f"message triage ({agent_key})",
            stderr_capture=stderr_capture,
            max_retries=1,
        )
    except RuntimeError as e:
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e, stderr_capture.text)
        log.error("message_triage_error", str(e), error_refs)
        return

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        aios.log_cost(
            agent_key,
            "message-triage",
            cost,
            result_msg.duration_ms,
            cfg.message_triage_model,
            result_msg.num_turns,
            config=cfg,
        )
        log.info(
            "message_triage_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns, "model": cfg.message_triage_model},
        )


async def run_cycle(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """One-shot cycle for cron: check tasks, triage messages, respond to threads."""
    cfg = config or get_config()

    if not _check_budget_gate(agent_id, "cycle", config=cfg):
        return

    # Pre-flight health gate: verify agent can write to its directories
    from .preflight import run_preflight

    preflight = run_preflight(agent_id, config=cfg)
    if not preflight.passed:
        log = get_logger(agent_id, config=cfg)
        log.error(
            "preflight_failed",
            f"Pre-flight checks failed: {preflight.summary}",
            {
                "checks": [
                    {"name": c.name, "detail": c.detail, "fix": c.fix_suggestion} for c in preflight.failed_checks
                ],
            },
        )
        from .notifications import NotificationEvent, send_notification

        send_notification(
            NotificationEvent(
                event_type="preflight_failed",
                severity="critical",
                title=f"Agent {agent_id} blocked by pre-flight check",
                detail=preflight.summary,
                agent_id=agent_id,
                refs={"failed_checks": len(preflight.failed_checks)},
            ),
            config=cfg,
        )
        return

    # Failure circuit breaker: stop dispatching if too many consecutive failures
    from .circuit_breaker import auto_check_reset, check_breaker

    breaker = check_breaker(agent_id, config=cfg)
    if breaker.tripped and not auto_check_reset(agent_id, config=cfg):
        log = get_logger(agent_id, config=cfg)
        log.warn(
            "circuit_breaker_active",
            f"Failure circuit breaker active: {breaker.reason}",
            {
                "tripped_at": breaker.tripped_at,
                "consecutive_failures": breaker.consecutive_failures,
            },
        )
        return

    agent_config = load_agent(agent_id, config=cfg)
    log = get_logger(agent_config.agent_id)

    next_task = aios._find_next_task(agent_config.agent_id, config=cfg)
    if next_task:
        task_id = next_task.stem
        log.info("cycle_task_found", f"Found task {task_id}, running...", {"task_id": task_id})
        await run_agent(agent_id, task_id=task_id, config=cfg, max_turns=max_turns, max_budget_usd=max_budget_usd)
        return

    inbox_msgs = aios.read_inbox(agent_config.agent_id, config=cfg)
    if inbox_msgs:
        await run_message_triage(agent_id, config=cfg)
        return

    pending = aios.get_pending_threads(agent_config.agent_id, config=cfg)
    if pending:
        log.info("cycle_threads", f"{len(pending)} thread(s) need response, running...", {"thread_count": len(pending)})
        await run_thread_response(agent_id, pending, config=cfg)
        return

    # Classify the idle cycle for health metrics
    cycle_type = _classify_idle_cycle(agent_config.agent_id, config=cfg)
    log.info("cycle_idle", f"Nothing to do ({cycle_type}), exiting", {"cycle_type": cycle_type})


async def run_standing_orders(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """Run standing orders for an agent — read from registry metadata.

    Checks cadence first: if the order isn't due yet, exits immediately ($0).
    When due, loads the prompt from the standing order file and invokes Claude.
    """
    cfg = config or get_config()

    if not _check_budget_gate(agent_id, "standing_orders", config=cfg):
        return

    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id
    log = get_logger(agent_key)

    # Read standing orders from agent registry metadata
    orders = agent_config.meta.get("standing_orders", {})
    if not orders:
        return

    for order_name, order_config in orders.items():
        cadence_hours = order_config["cadence_hours"]

        if not aios.check_cadence(agent_key, order_name, cadence_hours, config=cfg):
            continue

        # Compute expected_at: last cadence time + cadence interval
        expected_at = _compute_expected_at(agent_key, order_name, cadence_hours, config=cfg)
        log.info(
            "standing_order_start",
            f"Running standing order: {order_name}",
            {"order": order_name, "cadence_hours": cadence_hours, "expected_at": expected_at},
        )

        # Load prompt from file
        prompt_file = order_config.get("prompt_file", "")
        prompt_path = cfg.agents_dir / prompt_file
        if not prompt_path.exists():
            log.error(
                "standing_order_error",
                f"Prompt file not found: {prompt_path}",
                {"order": order_name},
            )
            continue

        order_prompt = prompt_path.read_text()

        # Interpolate {agent_id} in the prompt text (standing order files use this)
        order_prompt = order_prompt.replace("{agent_id}", agent_key)

        # Read journal for temporal context
        journal = aios.read_journal(agent_key, max_entries=10, config=cfg)
        journal_context = ""
        if journal:
            journal_context = f"\n\n# Your Recent Journal Entries\n\n{journal}"

        system_prompt = composer.build_system_prompt(agent_config) + journal_context

        os.environ.pop("CLAUDECODE", None)

        stderr_capture = StderrCapture(agent_key)
        try:
            _ensure_api_key()
            options = _make_options(
                agent_config,
                system_prompt,
                config=cfg,
                max_turns=max_turns or cfg.standing_orders_max_turns,
                max_budget_usd=max_budget_usd or cfg.standing_orders_max_budget_usd,
                stderr_capture=stderr_capture,
            )

            result_msg = await _run_query(
                order_prompt,
                options,
                label=f"standing order '{order_name}' ({agent_key})",
                stderr_capture=stderr_capture,
                max_retries=2,
            )
        except Exception as e:
            error_refs = _error_classifier.build_error_refs(
                e.__cause__ or e if e.__cause__ else e, stderr_capture.text, order=order_name
            )
            log.error(
                "standing_order_error",
                f"Error in standing order '{order_name}': {e}",
                {**error_refs, "order": order_name},
            )
            # Mark cadence even on error to prevent infinite retry loops.
            # The order will be retried after the normal cadence interval.
            aios.mark_cadence(agent_key, order_name, config=cfg)
            continue

        if result_msg:
            cost = result_msg.total_cost_usd or 0.0
            aios.log_cost(
                agent_key,
                f"standing-order:{order_name}",
                cost,
                result_msg.duration_ms,
                agent_config.model,
                result_msg.num_turns,
                config=cfg,
            )
            log.info(
                "standing_order_complete",
                f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
                {"order": order_name, "cost_usd": cost, "turns": result_msg.num_turns},
            )

        aios.mark_cadence(agent_key, order_name, config=cfg)


def main():
    parser = argparse.ArgumentParser(description="agent-os runner")
    parser.add_argument("--agent", required=True, help="Agent ID (e.g. agent-006)")
    parser.add_argument("--task", help="Specific task ID to run")
    parser.add_argument("--cycle", action="store_true", help="Run one cycle: check tasks, messages, threads (for cron)")
    parser.add_argument(
        "--standing-orders", action="store_true", help="Run standing orders if due (for cron, less frequent)"
    )
    parser.add_argument("--drives", action="store_true", help="Run drive consultation (cron-scheduled or manual)")
    parser.add_argument("--dream", action="store_true", help="Run dream cycle (nightly memory reorganization)")
    parser.add_argument(
        "--interactive", action="store_true", help="Interactive conversation mode (reads JSON from stdin)"
    )
    parser.add_argument("--max-turns", type=int, default=None, help="Override max turns for this invocation")
    parser.add_argument("--max-budget", type=float, default=None, help="Override max budget (USD) for this invocation")
    args = parser.parse_args()

    if not any([args.task, args.cycle, args.standing_orders, args.drives, args.dream, args.interactive]):
        parser.error("Must specify --task, --cycle, --standing-orders, --drives, --dream, or --interactive")

    overrides = {}
    if args.max_turns is not None:
        overrides["max_turns"] = args.max_turns
    if args.max_budget is not None:
        overrides["max_budget_usd"] = args.max_budget

    if args.interactive:
        stdin_data = sys.stdin.read()
        asyncio.run(run_interactive(args.agent, conversation_json=stdin_data, **overrides))
    elif args.standing_orders:
        asyncio.run(run_standing_orders(args.agent, **overrides))
    elif args.drives:
        asyncio.run(run_drive_consultation(args.agent, **overrides))
    elif args.dream:
        asyncio.run(run_dream_cycle(args.agent, **overrides))
    elif args.cycle:
        asyncio.run(run_cycle(args.agent, **overrides))
    else:
        asyncio.run(run_agent(args.agent, task_id=args.task, **overrides))


if __name__ == "__main__":
    main()
