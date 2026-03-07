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
import json
import os
import random
import subprocess
import sys
import time
from datetime import UTC, datetime
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
from .composer import PromptComposer
from .config import Config, get_config
from .errors import ClaudeErrorClassifier
from .registry import load_agent
from .tools import AIOS_TOOL_NAMES, create_aios_tools_server

# --- Shared infrastructure ---

_error_classifier = ClaudeErrorClassifier()


def _now_iso() -> str:
    """Current UTC time in ISO format."""
    return datetime.now(UTC).isoformat()


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

    def __init__(self):
        self.lines: list[str] = []

    def callback(self, line: str) -> None:
        self.lines.append(line)
        print(f"[agent-os][stderr] {line}", flush=True)

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
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    model: str | None = None,
    stderr_capture: StderrCapture | None = None,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions with agent-os MCP tools injected."""
    cfg = config or get_config()

    prompt_bytes = len(system_prompt.encode("utf-8"))
    if prompt_bytes > 120_000:
        print(
            f"[agent-os] WARNING: system prompt is {prompt_bytes:,} bytes "
            f"(agent {agent_config.agent_id}). Linux MAX_ARG_STRLEN is 131072. "
            f"Risk of 'Argument list too long' failure.",
            flush=True,
        )
        aios.log_action(
            agent_config.agent_id,
            "prompt_size_warning",
            f"System prompt {prompt_bytes:,} bytes — approaching 128KB CLI limit",
            config=cfg,
        )

    aios_server = create_aios_tools_server(agent_id=agent_config.agent_id, config=cfg)
    opts_kwargs = dict(
        system_prompt=system_prompt,
        allowed_tools=agent_config.allowed_tools + AIOS_TOOL_NAMES,
        permission_mode="bypassPermissions",
        model=model or agent_config.model,
        max_turns=max_turns or cfg.max_turns_per_invocation,
        max_budget_usd=max_budget_usd or cfg.max_budget_per_invocation_usd,
        cwd=str(cfg.company_root),
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

    Checks the environment variable and common secret file locations.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return

    # Check common locations for a key file
    candidates = [
        Path("secrets/anthropic_api_key.txt"),
        Path.home() / ".anthropic" / "api_key.txt",
    ]
    for key_file in candidates:
        if key_file.exists():
            os.environ["ANTHROPIC_API_KEY"] = key_file.read_text().strip()
            return

    print("[agent-os] ERROR: No ANTHROPIC_API_KEY set.")
    print("  Set the environment variable: export ANTHROPIC_API_KEY=your-key-here")
    print("  Or place your key in: secrets/anthropic_api_key.txt")
    sys.exit(1)


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
    last_exc = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            backoff = (2**attempt) + random.uniform(0, 1)
            print(f"[agent-os] Retry {attempt}/{max_retries} after {backoff:.1f}s...", flush=True)
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
                        print(f"[agent-os] API error in stream: {message.error}", flush=True)

                    for block in message.content:
                        if hasattr(block, "text"):
                            print(block.text, flush=True)
                        elif hasattr(block, "name"):
                            print(f"  [tool: {block.name}]", flush=True)
                        if hasattr(block, "is_error") and block.is_error:
                            tool_errors += 1
                            error_text = getattr(block, "text", str(block))
                            print(f"[agent-os] Tool error: {error_text}", flush=True)

                elif isinstance(message, ResultMessage):
                    result_msg = message
                    suffix = ""
                    if tool_errors:
                        suffix = f" ({tool_errors} tool error(s))"
                    if api_errors:
                        suffix += f" ({len(api_errors)} API error(s))"
                    print(f"\n[agent-os] {label} complete: {message.subtype} ({message.num_turns} turns){suffix}")

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
                print(f"[agent-os] Transient error during {label}: {detail}", flush=True)
                continue

            if category == "permanent":
                print(f"[agent-os] Permanent error during {label} — not retrying", flush=True)
            raise RuntimeError(f"SDK error during {label}: {detail}") from e

        except Exception as e:
            if result_msg is not None and _error_classifier.is_benign_cleanup(e):
                print(f"[agent-os] Note: benign transport cleanup after {label} (result already received)", flush=True)
                return result_msg

            last_exc = e

            if CLIConnectionError is not _Unavailable and isinstance(e, CLIConnectionError):
                detail = _error_classifier.format_detail(e)
                combined = f"{detail} {stderr_capture.text if stderr_capture else ''}"
                _category, retryable = _error_classifier.classify(combined)
                if retryable and attempt < max_retries:
                    print(f"[agent-os] Transient error during {label}: {detail}", flush=True)
                    continue

            if isinstance(e, ExceptionGroup):
                detail = _error_classifier.format_detail(e)
                combined = f"{detail} {stderr_capture.text if stderr_capture else ''}"
                _category, retryable = _error_classifier.classify(combined)
                if retryable and attempt < max_retries:
                    print(f"[agent-os] Transient error during {label}: {detail}", flush=True)
                    continue

            detail = _error_classifier.format_detail(e)
            raise RuntimeError(f"SDK error during {label}: {detail}") from e

    detail = _error_classifier.format_detail(last_exc) if last_exc else "unknown error"
    raise RuntimeError(f"SDK error during {label} (after {max_retries} retries): {detail}") from last_exc


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
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    print(f"[agent-os] Loaded agent: {agent_config.agent_id} ({agent_config.role})", flush=True)
    print(f"[agent-os] Model: {agent_config.model}", flush=True)
    print(f"[agent-os] Tools: {', '.join(agent_config.allowed_tools)}", flush=True)

    task_context = None
    task_meta = None

    if task_id:
        task_path = aios.claim_task(agent_config.agent_id, task_id, config=cfg)
        if not task_path:
            print(f"[agent-os] ERROR: Could not claim task {task_id}")
            sys.exit(1)
        print(f"[agent-os] Claimed task: {task_path.name}", flush=True)

        task_meta, task_body = aios._parse_frontmatter(task_path)
        task_context = task_path.read_text()
        prompt = build_task_prompt(agent_config, task_meta, task_body)

        aios.log_action(
            agent_config.agent_id,
            "claimed_task",
            f"Claimed {task_id}",
            {"task_id": task_id, "path": str(task_path)},
            config=cfg,
        )
    else:
        print("[agent-os] ERROR: Must specify --task or --cycle")
        sys.exit(1)

    system_prompt = composer.build_system_prompt(agent_config, task_context)

    os.environ.pop("CLAUDECODE", None)
    _ensure_api_key()

    print("[agent-os] Invoking Claude...", flush=True)
    aios.log_action(
        agent_config.agent_id,
        "sdk_invoke",
        "Calling Claude Agent SDK",
        {"model": agent_config.model, "task": task_id},
        config=cfg,
    )

    stderr_capture = StderrCapture()
    options = _make_options(
        agent_config,
        system_prompt,
        config=cfg,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        stderr_capture=stderr_capture,
    )

    try:
        result_msg = await _run_query(
            prompt,
            options,
            label=f"task {task_id}",
            stderr_capture=stderr_capture,
            max_retries=2,
        )
    except RuntimeError as e:
        error_detail = str(e)
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e, stderr_capture.text, task=task_id)
        print(f"[agent-os] ERROR: {error_detail}")
        aios.log_action(agent_config.agent_id, "sdk_error", error_detail, {**error_refs, "task": task_id}, config=cfg)
        if task_id:
            aios.fail_task(task_id, error_detail, error_refs=error_refs, config=cfg)
        sys.exit(1)

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        duration = result_msg.duration_ms
        turns = result_msg.num_turns

        aios.log_cost(agent_config.agent_id, task_id, cost, duration, agent_config.model, turns, config=cfg)
        aios.log_action(
            agent_config.agent_id,
            "sdk_complete",
            f"Done: ${cost:.4f}, {turns} turns, {duration}ms",
            {"task": task_id, "cost_usd": cost, "turns": turns},
            config=cfg,
        )

        print(f"[agent-os] Cost: ${cost:.4f} | Turns: {turns} | Duration: {duration}ms", flush=True)

        if task_id and not result_msg.is_error:
            if agent_config.role in cfg.builder_roles and task_meta:
                code_dir = _find_product_code_dir(task_meta, config=cfg)
                if code_dir:
                    print(f"[agent-os] Running quality gates on {code_dir}...", flush=True)
                    aios.log_action(
                        agent_config.agent_id,
                        "quality_gates_start",
                        f"Running pre-done checks on {code_dir}",
                        {"task_id": task_id, "code_dir": str(code_dir)},
                        config=cfg,
                    )

                    gates_passed, gate_output = _run_quality_gates(code_dir, config=cfg)
                    print(gate_output, flush=True)

                    if gates_passed:
                        aios.log_action(
                            agent_config.agent_id,
                            "quality_gates_passed",
                            "All quality gates passed",
                            {"task_id": task_id},
                            config=cfg,
                        )
                        aios.complete_task(task_id, config=cfg)
                        aios.log_action(
                            agent_config.agent_id,
                            "completed_task",
                            f"Completed {task_id}",
                            {"task_id": task_id},
                            config=cfg,
                        )
                        print(f"[agent-os] Task {task_id} moved to done/")
                    else:
                        aios.log_action(
                            agent_config.agent_id,
                            "quality_gates_failed",
                            "Quality gates failed — task moved to failed/",
                            {"task_id": task_id, "output": gate_output[:500]},
                            config=cfg,
                        )
                        aios.fail_task(task_id, f"Quality gates failed:\n{gate_output[-1000:]}", config=cfg)
                        print(f"[agent-os] Task {task_id} FAILED quality gates — moved to failed/")
                else:
                    aios.complete_task(task_id, config=cfg)
                    aios.log_action(
                        agent_config.agent_id,
                        "completed_task",
                        f"Completed {task_id} (no product code dir — quality gates skipped)",
                        {"task_id": task_id},
                        config=cfg,
                    )
                    print(f"[agent-os] Task {task_id} moved to done/ (quality gates: N/A)")
            else:
                aios.complete_task(task_id, config=cfg)
                aios.log_action(
                    agent_config.agent_id, "completed_task", f"Completed {task_id}", {"task_id": task_id}, config=cfg
                )
                print(f"[agent-os] Task {task_id} moved to done/")
        elif task_id and result_msg.is_error:
            aios.fail_task(task_id, result_msg.result or "Agent returned error", config=cfg)
            print(f"[agent-os] Task {task_id} moved to failed/")


async def run_drive_consultation(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """Consult drives — agents think about what the company needs."""
    cfg = config or get_config()
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    expected_at = _now_iso()  # Drive consultations run on cron schedule; expected = now
    print(f"[agent-os] {agent_key}: running drive consultation...", flush=True)
    aios.log_action(
        agent_key, "drive_consultation_start", "Consulting drives (scheduled)", {"expected_at": expected_at}, config=cfg
    )

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

    stderr_capture = StderrCapture()
    options = _make_options(
        agent_config,
        system_prompt,
        config=cfg,
        max_turns=max_turns or cfg.drive_consultation_max_turns,
        max_budget_usd=max_budget_usd or cfg.drive_consultation_max_budget_usd,
        stderr_capture=stderr_capture,
    )

    try:
        result_msg = await _run_query(
            prompt,
            options,
            label=f"drive consultation ({agent_key})",
            stderr_capture=stderr_capture,
            max_retries=1,
        )
    except RuntimeError as e:
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e, stderr_capture.text)
        print(f"[agent-os] ERROR in drive consultation: {e}", flush=True)
        aios.log_action(agent_key, "drive_consultation_error", str(e), error_refs, config=cfg)
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
        aios.log_action(
            agent_key,
            "drive_consultation_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns},
            config=cfg,
        )
        print(f"[agent-os] Cost: ${cost:.4f} | Turns: {result_msg.num_turns}", flush=True)

    aios.log_action(agent_key, "drive_consultation_done", "Drive consultation finished", config=cfg)


async def run_dream_cycle(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """Nightly dream cycle — agents reorganize their memory state."""
    cfg = config or get_config()
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    print(f"[agent-os] {agent_key}: entering dream cycle...", flush=True)
    aios.log_action(agent_key, "dream_start", "Entering dream cycle (nightly memory reorganization)", config=cfg)

    system_prompt = composer.build_system_prompt(agent_config)

    prompt = composer.render_template("dream.jinja2", agent_id=agent_key)

    os.environ.pop("CLAUDECODE", None)
    _ensure_api_key()

    dream_model = cfg.dream_model
    print(f"[agent-os] Dream model: {dream_model}", flush=True)

    stderr_capture = StderrCapture()
    options = _make_options(
        agent_config,
        system_prompt,
        config=cfg,
        max_turns=max_turns or cfg.dream_max_turns,
        max_budget_usd=max_budget_usd or cfg.dream_max_budget_usd,
        model=dream_model,
        stderr_capture=stderr_capture,
    )

    try:
        result_msg = await _run_query(
            prompt,
            options,
            label=f"dream cycle ({agent_key})",
            stderr_capture=stderr_capture,
            max_retries=1,
        )
    except RuntimeError as e:
        error_refs = _error_classifier.build_error_refs(e.__cause__ or e, stderr_capture.text)
        print(f"[agent-os] ERROR in dream cycle: {e}", flush=True)
        aios.log_action(agent_key, "dream_error", str(e), error_refs, config=cfg)
        return

    if result_msg:
        cost = result_msg.total_cost_usd or 0.0
        aios.log_cost(
            agent_key, "dream-cycle", cost, result_msg.duration_ms, dream_model, result_msg.num_turns, config=cfg
        )
        aios.log_action(
            agent_key,
            "dream_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns},
            config=cfg,
        )
        print(f"[agent-os] Cost: ${cost:.4f} | Turns: {result_msg.num_turns}", flush=True)

    aios.log_action(agent_key, "dream_done", "Dream cycle finished", config=cfg)


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

    aios.log_action(
        agent_key,
        "thread_response_start",
        f"Responding to {len(pending_threads)} thread(s)",
        {"thread_count": len(pending_threads)},
        config=cfg,
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

    stderr_capture = StderrCapture()
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
        print(f"[agent-os] ERROR in thread response: {e}")
        aios.log_action(agent_key, "thread_response_error", str(e), error_refs, config=cfg)
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
        aios.log_action(
            agent_key,
            "thread_response_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns},
            config=cfg,
        )
        print(f"[agent-os] Cost: ${cost:.4f} | Turns: {result_msg.num_turns}", flush=True)


async def run_message_triage(agent_id: str, *, config: Config | None = None) -> None:
    """Process unread inbox messages — lightweight triage using Sonnet."""
    cfg = config or get_config()
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

    inbox_msgs = aios.read_inbox(agent_key, config=cfg)
    if not inbox_msgs:
        return

    print(f"[agent-os] {agent_key}: {len(inbox_msgs)} inbox message(s), triaging...", flush=True)
    aios.log_action(
        agent_key,
        "message_triage_start",
        f"Triaging {len(inbox_msgs)} message(s)",
        {"count": len(inbox_msgs)},
        config=cfg,
    )

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

    stderr_capture = StderrCapture()
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
        print(f"[agent-os] ERROR in message triage: {e}")
        aios.log_action(agent_key, "message_triage_error", str(e), error_refs, config=cfg)
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
        aios.log_action(
            agent_key,
            "message_triage_complete",
            f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
            {"cost_usd": cost, "turns": result_msg.num_turns, "model": cfg.message_triage_model},
            config=cfg,
        )
        print(
            f"[agent-os] Cost: ${cost:.4f} | Turns: {result_msg.num_turns} | Model: {cfg.message_triage_model}",
            flush=True,
        )


async def run_cycle(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """One-shot cycle for cron: check tasks, triage messages, respond to threads."""
    cfg = config or get_config()
    agent_config = load_agent(agent_id, config=cfg)

    next_task = aios._find_next_task(agent_config.agent_id, config=cfg)
    if next_task:
        task_id = next_task.stem
        print(f"[agent-os] {agent_config.agent_id}: found task {task_id}, running...", flush=True)
        await run_agent(agent_id, task_id=task_id, config=cfg, max_turns=max_turns, max_budget_usd=max_budget_usd)
        return

    inbox_msgs = aios.read_inbox(agent_config.agent_id, config=cfg)
    if inbox_msgs:
        await run_message_triage(agent_id, config=cfg)
        return

    pending = aios.get_pending_threads(agent_config.agent_id, config=cfg)
    if pending:
        print(f"[agent-os] {agent_config.agent_id}: {len(pending)} thread(s) need response, running...", flush=True)
        await run_thread_response(agent_id, pending, config=cfg)
        return

    # Classify the idle cycle for health metrics
    cycle_type = _classify_idle_cycle(agent_config.agent_id, config=cfg)
    aios.log_action(
        agent_config.agent_id, "cycle_idle", "Nothing to do, exiting", {"cycle_type": cycle_type}, config=cfg
    )
    print(f"[agent-os] {agent_config.agent_id}: nothing to do ({cycle_type}), exiting", flush=True)


async def run_standing_orders(
    agent_id: str, *, config: Config | None = None, max_turns: int | None = None, max_budget_usd: float | None = None
) -> None:
    """Run standing orders for an agent — read from registry metadata.

    Checks cadence first: if the order isn't due yet, exits immediately ($0).
    When due, loads the prompt from the standing order file and invokes Claude.
    """
    cfg = config or get_config()
    composer = PromptComposer(config=cfg)

    agent_config = load_agent(agent_id, config=cfg)
    agent_key = agent_config.agent_id

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
        print(f"[agent-os] {agent_key}: standing order '{order_name}' is due, running...", flush=True)
        aios.log_action(
            agent_key,
            "standing_order_start",
            f"Running standing order: {order_name}",
            {"order": order_name, "cadence_hours": cadence_hours, "expected_at": expected_at},
            config=cfg,
        )

        # Load prompt from file
        prompt_file = order_config.get("prompt_file", "")
        prompt_path = cfg.agents_dir / prompt_file
        if not prompt_path.exists():
            print(f"[agent-os] ERROR: Standing order prompt file not found: {prompt_path}")
            aios.log_action(
                agent_key,
                "standing_order_error",
                f"Prompt file not found: {prompt_path}",
                {"order": order_name},
                config=cfg,
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
        _ensure_api_key()

        stderr_capture = StderrCapture()
        options = _make_options(
            agent_config,
            system_prompt,
            config=cfg,
            max_turns=max_turns or cfg.standing_orders_max_turns,
            max_budget_usd=max_budget_usd or cfg.standing_orders_max_budget_usd,
            stderr_capture=stderr_capture,
        )

        try:
            result_msg = await _run_query(
                order_prompt,
                options,
                label=f"standing order '{order_name}' ({agent_key})",
                stderr_capture=stderr_capture,
                max_retries=2,
            )
        except RuntimeError as e:
            error_refs = _error_classifier.build_error_refs(e.__cause__ or e, stderr_capture.text, order=order_name)
            print(f"[agent-os] ERROR in standing order '{order_name}': {e}")
            aios.log_action(agent_key, "standing_order_error", str(e), {**error_refs, "order": order_name}, config=cfg)
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
            aios.log_action(
                agent_key,
                "standing_order_complete",
                f"Done: ${cost:.4f}, {result_msg.num_turns} turns",
                {"order": order_name, "cost_usd": cost},
                config=cfg,
            )
            print(f"[agent-os] Cost: ${cost:.4f} | Turns: {result_msg.num_turns}", flush=True)

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
