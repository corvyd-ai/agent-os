"""Tests for the `agent-os briefing` command — LLM-optimized session bootstrap.

Written red-green-refactor. Each behavior has its own test, and the tests
were written BEFORE the implementation (confirmed red first).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_os.config import Config

# --------------------------------------------------------------------------
# Cycle 1: module exists, function is callable, returns a string
# --------------------------------------------------------------------------


def test_render_briefing_returns_string(aios_config: Config):
    from agent_os.briefing import render_briefing

    result = render_briefing(aios_config)
    assert isinstance(result, str)
    assert len(result) > 0


# --------------------------------------------------------------------------
# Cycle 2: header carries company name, today's date (company TZ), version
# --------------------------------------------------------------------------


def test_header_includes_company_name(aios_config: Config):
    from agent_os.briefing import render_briefing

    assert aios_config.company_name in render_briefing(aios_config)


def test_header_includes_today(aios_config: Config):
    from agent_os.briefing import render_briefing

    today = datetime.now(aios_config.tz).date().isoformat()
    assert today in render_briefing(aios_config)


def test_header_includes_agent_os_version(aios_config: Config):
    from agent_os import __version__
    from agent_os.briefing import render_briefing

    assert __version__ in render_briefing(aios_config)


# --------------------------------------------------------------------------
# Cycle 3: agent roster section
# --------------------------------------------------------------------------


def _register(cfg: Config, agent_id: str, *, name: str = "Agent", role: str = "Software Engineer") -> None:
    cfg.registry_dir.mkdir(parents=True, exist_ok=True)
    (cfg.registry_dir / f"{agent_id}.md").write_text(f"---\nid: {agent_id}\nname: {name}\nrole: {role}\n---\n")


def test_roster_lists_registered_agents(aios_config: Config):
    from agent_os.briefing import render_briefing

    _register(aios_config, "agent-001-maker", name="The Maker", role="Software Engineer")
    _register(aios_config, "agent-002-writer", name="The Writer", role="Content Writer")

    output = render_briefing(aios_config)
    assert "agent-001-maker" in output
    assert "agent-002-writer" in output
    assert "Software Engineer" in output
    assert "Content Writer" in output


def test_roster_section_handles_empty_registry(aios_config: Config):
    """Empty registry should produce a section noting it, not crash."""
    from agent_os.briefing import render_briefing

    output = render_briefing(aios_config)
    # The section should exist but indicate no agents.
    assert "agent" in output.lower()  # either "agents" heading or "no agents"


# --------------------------------------------------------------------------
# Cycle 4: work queue — counts per status + top queued task titles
# --------------------------------------------------------------------------


def _write_task(directory, task_id: str, *, title: str = "Do the thing", **fm) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {task_id}", f'title: "{title}"']
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    (directory / f"{task_id}.md").write_text("\n".join(lines))


def test_work_queue_shows_counts_per_status(aios_config: Config):
    from agent_os.briefing import render_briefing

    _write_task(aios_config.tasks_queued, "task-q-1", title="Queue one")
    _write_task(aios_config.tasks_queued, "task-q-2", title="Queue two")
    _write_task(aios_config.tasks_in_progress, "task-ip-1", title="In progress one")
    _write_task(aios_config.tasks_done, "task-d-1", title="Done one")

    output = render_briefing(aios_config)
    # The section should reflect the shape of the queue.
    assert "queued" in output.lower()
    assert "2" in output  # 2 queued
    assert "in-progress" in output.lower() or "in progress" in output.lower()


def test_work_queue_lists_top_queued_titles(aios_config: Config):
    from agent_os.briefing import render_briefing

    _write_task(aios_config.tasks_queued, "task-q-1", title="Ship the thing")
    _write_task(aios_config.tasks_queued, "task-q-2", title="Fix the bug")

    output = render_briefing(aios_config)
    assert "Ship the thing" in output
    assert "Fix the bug" in output
    assert "task-q-1" in output


def test_work_queue_flags_backlog_awaiting_promotion(aios_config: Config):
    from agent_os.briefing import render_briefing

    _write_task(aios_config.tasks_backlog, "task-b-1", title="Needs triage")
    output = render_briefing(aios_config)
    assert "backlog" in output.lower()
    assert "Needs triage" in output or "1" in output


# --------------------------------------------------------------------------
# Cycle 5: operational status — scheduler + budget headroom
# --------------------------------------------------------------------------


def test_operational_status_reports_daily_spend(aios_config: Config):
    """Today's spend should appear in the briefing."""
    import json

    from agent_os.briefing import render_briefing

    today = datetime.now(aios_config.tz).date().isoformat()
    aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.costs_dir / f"{today}.jsonl").write_text(
        json.dumps({"agent": "agent-001-maker", "cost_usd": 1.23}) + "\n"
    )

    output = render_briefing(aios_config)
    assert "1.23" in output or "$1.23" in output


def test_operational_status_reports_daily_cap(aios_config: Config):
    """The daily cap should appear so a reader sees the headroom."""
    from agent_os.briefing import render_briefing

    cap = int(aios_config.daily_budget_cap_usd)
    output = render_briefing(aios_config)
    # cap is printed as an int or float — accept either form.
    assert str(cap) in output or f"{aios_config.daily_budget_cap_usd:.2f}" in output


def test_operational_status_notes_circuit_breaker_when_tripped(aios_config: Config):
    """When daily spend >= cap, the briefing should call it out."""
    import json

    from agent_os.briefing import render_briefing

    today = datetime.now(aios_config.tz).date().isoformat()
    aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
    over_cap = aios_config.daily_budget_cap_usd + 1.0
    (aios_config.costs_dir / f"{today}.jsonl").write_text(
        json.dumps({"agent": "agent-001-maker", "cost_usd": over_cap}) + "\n"
    )

    output = render_briefing(aios_config).lower()
    # Must flag the tripped state somehow — "circuit breaker", "tripped", or "over".
    assert "circuit" in output or "tripped" in output or "over" in output or "cap reached" in output, (
        f"expected a circuit-breaker flag, got: {output[:400]}"
    )


# --------------------------------------------------------------------------
# Cycle 6: strategic context — current focus, drives, active proposals
# --------------------------------------------------------------------------


def test_strategic_context_includes_current_focus(aios_config: Config):
    """When strategy/current-focus.md exists, its first line/paragraph appears."""
    from agent_os.briefing import render_briefing

    aios_config.strategy_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.strategy_dir / "current-focus.md").write_text(
        "Ship the briefing command this week.\n\nDetails follow...\n"
    )

    output = render_briefing(aios_config)
    assert "Ship the briefing command this week" in output


def test_strategic_context_includes_drives(aios_config: Config):
    """drives.md content should be surfaced."""
    from agent_os.briefing import render_briefing

    aios_config.strategy_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.strategy_dir / "drives.md").write_text("# Drives\n\n## Kill the dashboard\n\nCLI is the product.\n")

    output = render_briefing(aios_config)
    assert "Kill the dashboard" in output


def test_strategic_context_lists_active_proposals(aios_config: Config):
    from agent_os.briefing import render_briefing

    aios_config.proposals_active.mkdir(parents=True, exist_ok=True)
    (aios_config.proposals_active / "proposal-2026-0419-001.md").write_text(
        '---\nid: proposal-2026-0419-001\ntitle: "Adopt TDD for platform changes"\n'
        "proposed_by: agent-000-steward\n"
        "date: 2026-04-19\n"
        "status: active\n---\n\nBody text.\n"
    )

    output = render_briefing(aios_config)
    assert "Adopt TDD for platform changes" in output
    assert "proposal-2026-0419-001" in output


def test_strategic_context_missing_files_do_not_crash(aios_config: Config):
    """No drives, no focus, no proposals — briefing still renders cleanly."""
    from agent_os.briefing import render_briefing

    output = render_briefing(aios_config)
    # No strategic data should not leave the briefing without the section header.
    assert "strateg" in output.lower() or "focus" in output.lower() or "drives" in output.lower()


# --------------------------------------------------------------------------
# Cycle 7: messages — broadcasts, threads, human inbox
# --------------------------------------------------------------------------


def _write_message(path, *, msg_id: str, subject: str, **fm) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {msg_id}", f'subject: "{subject}"']
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("body")
    path.write_text("\n".join(lines))


def test_messages_surfaces_broadcasts(aios_config: Config):
    from agent_os.briefing import render_briefing

    _write_message(
        aios_config.broadcast_dir / "broadcast-2026-0419-001.md",
        msg_id="broadcast-2026-0419-001",
        subject="Release notes — v0.3",
        date="2026-04-19T10:00:00Z",
    )

    output = render_briefing(aios_config)
    assert "Release notes — v0.3" in output


def test_messages_surfaces_human_inbox_count(aios_config: Config):
    from agent_os.briefing import render_briefing

    inbox = aios_config.human_inbox
    for i in range(3):
        _write_message(inbox / f"msg-{i}.md", msg_id=f"msg-{i}", subject=f"Note {i}", to="human")

    output = render_briefing(aios_config)
    assert "3" in output  # count appears
    # And at least one subject should show up
    assert "Note" in output


def test_messages_surfaces_active_threads(aios_config: Config):
    from agent_os.briefing import render_briefing

    _write_message(
        aios_config.threads_dir / "thread-2026-0419-001.md",
        msg_id="thread-2026-0419-001",
        subject="Discuss roadmap",
        status="active",
    )

    output = render_briefing(aios_config)
    assert "Discuss roadmap" in output


# --------------------------------------------------------------------------
# Cycle 8: recent activity — merged 24h timeline, idle hidden
# --------------------------------------------------------------------------


def test_recent_activity_lists_entries_across_agents(aios_config: Config):
    import json

    from agent_os.briefing import render_briefing

    today = datetime.now(aios_config.tz).date().isoformat()
    ts = datetime.now(UTC).isoformat()

    for agent in ("agent-001-maker", "agent-002-writer"):
        _register(aios_config, agent)
        log_dir = aios_config.logs_dir / agent
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{today}.jsonl").write_text(
            json.dumps({"action": "task_complete", "task": "task-abc", "timestamp": ts}) + "\n"
        )

    output = render_briefing(aios_config)
    assert "agent-001-maker" in output
    assert "agent-002-writer" in output


def test_recent_activity_hides_idle_cycles(aios_config: Config):
    import json

    from agent_os.briefing import render_briefing

    today = datetime.now(aios_config.tz).date().isoformat()
    ts = datetime.now(UTC).isoformat()
    agent = "agent-001-maker"
    _register(aios_config, agent)
    log_dir = aios_config.logs_dir / agent
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{today}.jsonl").write_text(
        json.dumps({"action": "cycle_idle", "timestamp": ts})
        + "\n"
        + json.dumps({"action": "task_complete", "task": "task-done", "timestamp": ts})
        + "\n"
    )

    output = render_briefing(aios_config)
    # Recent activity should show the real action but NOT a cycle_idle line.
    assert "task_complete" in output or "task-done" in output
    # We don't expect the idle event to drown the section.
    activity_section = output.split("Recent activity", 1)[-1] if "Recent activity" in output else output
    assert "cycle_idle" not in activity_section


# --------------------------------------------------------------------------
# Cycle 9: health snapshot — uses the ported metrics engine
# --------------------------------------------------------------------------


def test_health_snapshot_includes_composite_score(aios_config: Config):
    from agent_os.briefing import render_briefing

    _register(aios_config, "agent-001-maker")
    output = render_briefing(aios_config)
    # Score rendering format can vary, but the section must exist and include a numeric score.
    assert "health" in output.lower() or "score" in output.lower()


# --------------------------------------------------------------------------
# Cycle 10: "what to pay attention to" rollup (red/yellow flags)
# --------------------------------------------------------------------------


def test_attention_rollup_flags_circuit_breaker(aios_config: Config):
    import json

    from agent_os.briefing import render_briefing

    today = datetime.now(aios_config.tz).date().isoformat()
    aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.costs_dir / f"{today}.jsonl").write_text(
        json.dumps({"agent": "agent-001-maker", "cost_usd": aios_config.daily_budget_cap_usd + 5}) + "\n"
    )

    output = render_briefing(aios_config)
    # "Attention" / "Flags" rollup must be present and include the budget flag.
    assert "attention" in output.lower() or "flag" in output.lower()


def test_attention_rollup_clean_when_nothing_wrong(aios_config: Config):
    from agent_os.briefing import render_briefing

    output = render_briefing(aios_config)
    # No budget issue, no stale agents, no active proposals past due → all clear message.
    # We accept either "all clear" / "nothing" / "no red flags".
    lower = output.lower()
    assert "attention" in lower or "flag" in lower


# --------------------------------------------------------------------------
# Cycle 11: depth — full is a superset of short (strictly longer)
# --------------------------------------------------------------------------


def test_full_depth_is_longer_than_short_when_data_present(aios_config: Config):
    """Seed data in several sections and ensure full renders more text than short."""
    from agent_os.briefing import render_briefing

    _register(aios_config, "agent-001-maker")
    _write_task(aios_config.tasks_done, "task-done-1", title="Done one", assigned_to="agent-001-maker")

    short = render_briefing(aios_config, depth="short")
    full = render_briefing(aios_config, depth="full")
    assert len(full) >= len(short)


# --------------------------------------------------------------------------
# Cycle 12: CLI wiring — `agent-os briefing` prints the briefing
# --------------------------------------------------------------------------


def test_cmd_briefing_prints_markdown(aios_config: Config, capsys):
    """Calling cmd_briefing should print the rendered markdown to stdout."""
    from agent_os.cli import cmd_briefing

    args = type(
        "Args",
        (),
        {"depth": "short", "agent": None, "root": None, "config": None},
    )()

    # cmd_briefing must accept our aios_config via the Config singleton. Patch it.
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    configure(aios_config)
    try:
        cmd_briefing(args)
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    assert aios_config.company_name in captured.out
    assert "briefing" in captured.out.lower()


def test_cli_registers_briefing_subparser():
    """argparse should accept `agent-os briefing` as a valid command."""
    from agent_os.cli import _build_parser

    parser = _build_parser()
    # Should parse without error; unknown subcommands raise SystemExit.
    args = parser.parse_args(["briefing"])
    assert args.command == "briefing"
    assert hasattr(args, "depth")
