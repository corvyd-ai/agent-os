"""TDD tests for remaining read-only inspection commands:
  - agent-os timeline [--agent X] [--date D] [--hide-idle]
  - agent-os messages {broadcast|threads|human|inbox <agent>}
  - agent-os strategy {drives|decisions|proposals}

Red-first for each command's core behavior. Rendering details (tables vs
markdown) are covered at the render-function level, not via subprocess.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from agent_os.config import Config


def _register(cfg: Config, agent_id: str) -> None:
    cfg.registry_dir.mkdir(parents=True, exist_ok=True)
    (cfg.registry_dir / f"{agent_id}.md").write_text(f"---\nid: {agent_id}\n---\n")


# --------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------


def test_render_timeline_empty(aios_config: Config):
    from agent_os.read_cmds import render_timeline

    out = render_timeline(aios_config)
    assert "no activity" in out.lower() or out.strip() != ""


def test_render_timeline_merges_across_agents(aios_config: Config):
    from agent_os.read_cmds import render_timeline

    today = datetime.now(aios_config.tz).date().isoformat()
    ts = datetime.now(UTC).isoformat()
    for agent in ("agent-001-maker", "agent-002-writer"):
        _register(aios_config, agent)
        (aios_config.logs_dir / agent).mkdir(parents=True, exist_ok=True)
        (aios_config.logs_dir / agent / f"{today}.jsonl").write_text(
            json.dumps({"action": "task_complete", "task": f"task-{agent[-1]}", "timestamp": ts}) + "\n"
        )

    out = render_timeline(aios_config)
    assert "agent-001-maker" in out
    assert "agent-002-writer" in out


def test_render_timeline_hide_idle_drops_cycle_idle(aios_config: Config):
    from agent_os.read_cmds import render_timeline

    agent = "agent-001-maker"
    _register(aios_config, agent)
    today = datetime.now(aios_config.tz).date().isoformat()
    ts = datetime.now(UTC).isoformat()
    (aios_config.logs_dir / agent).mkdir(parents=True, exist_ok=True)
    (aios_config.logs_dir / agent / f"{today}.jsonl").write_text(
        json.dumps({"action": "cycle_idle", "timestamp": ts})
        + "\n"
        + json.dumps({"action": "task_complete", "task": "task-x", "timestamp": ts})
        + "\n"
    )

    with_idle = render_timeline(aios_config, hide_idle=False)
    without_idle = render_timeline(aios_config, hide_idle=True)
    assert "cycle_idle" in with_idle
    assert "cycle_idle" not in without_idle


def test_render_timeline_agent_filter(aios_config: Config):
    from agent_os.read_cmds import render_timeline

    today = datetime.now(aios_config.tz).date().isoformat()
    ts = datetime.now(UTC).isoformat()
    for agent in ("agent-001-maker", "agent-002-writer"):
        _register(aios_config, agent)
        (aios_config.logs_dir / agent).mkdir(parents=True, exist_ok=True)
        (aios_config.logs_dir / agent / f"{today}.jsonl").write_text(
            json.dumps({"action": "task_complete", "task": "task-x", "timestamp": ts}) + "\n"
        )

    out = render_timeline(aios_config, agent="agent-001-maker")
    assert "agent-001-maker" in out
    assert "agent-002-writer" not in out


# --------------------------------------------------------------------------
# messages
# --------------------------------------------------------------------------


def _write_msg(path, *, msg_id: str, subject: str, **fm) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {msg_id}", f'subject: "{subject}"']
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("body")
    path.write_text("\n".join(lines))


def test_render_messages_broadcast(aios_config: Config):
    from agent_os.read_cmds import render_messages

    _write_msg(aios_config.broadcast_dir / "broadcast-001.md", msg_id="broadcast-001", subject="Release!")
    out = render_messages(aios_config, channel="broadcast")
    assert "broadcast-001" in out
    assert "Release!" in out


def test_render_messages_threads(aios_config: Config):
    from agent_os.read_cmds import render_messages

    _write_msg(aios_config.threads_dir / "thread-001.md", msg_id="thread-001", subject="Discuss roadmap")
    out = render_messages(aios_config, channel="threads")
    assert "thread-001" in out
    assert "Discuss roadmap" in out


def test_render_messages_human(aios_config: Config):
    from agent_os.read_cmds import render_messages

    _write_msg(aios_config.human_inbox / "msg-001.md", msg_id="msg-001", subject="For you")
    out = render_messages(aios_config, channel="human")
    assert "msg-001" in out
    assert "For you" in out


def test_render_messages_agent_inbox(aios_config: Config):
    from agent_os.read_cmds import render_messages

    agent = "agent-001-maker"
    inbox = aios_config.messages_dir / agent / "inbox"
    _write_msg(inbox / "msg-001.md", msg_id="msg-001", subject="Ping")
    out = render_messages(aios_config, channel="inbox", agent=agent)
    assert "msg-001" in out
    assert "Ping" in out


# --------------------------------------------------------------------------
# strategy
# --------------------------------------------------------------------------


def test_render_strategy_drives(aios_config: Config):
    from agent_os.read_cmds import render_strategy

    aios_config.strategy_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.strategy_dir / "drives.md").write_text("# Drives\n\n## Kill the dashboard\n\nBody.\n")

    out = render_strategy(aios_config, topic="drives")
    assert "Kill the dashboard" in out


def test_render_strategy_decisions(aios_config: Config):
    from agent_os.read_cmds import render_strategy

    aios_config.decisions_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.decisions_dir / "decision-001.md").write_text(
        '---\nid: decision-001\ntitle: "Adopt TDD"\ndate: 2026-04-19\n---\n\nBody.\n'
    )

    out = render_strategy(aios_config, topic="decisions")
    assert "decision-001" in out
    assert "Adopt TDD" in out


def test_render_strategy_proposals_includes_active_and_decided(aios_config: Config):
    from agent_os.read_cmds import render_strategy

    aios_config.proposals_active.mkdir(parents=True, exist_ok=True)
    (aios_config.proposals_active / "proposal-a.md").write_text(
        '---\nid: proposal-a\ntitle: "Active one"\nstatus: active\n---\n'
    )
    aios_config.proposals_decided.mkdir(parents=True, exist_ok=True)
    (aios_config.proposals_decided / "proposal-b.md").write_text(
        '---\nid: proposal-b\ntitle: "Decided one"\nstatus: decided\n---\n'
    )

    out = render_strategy(aios_config, topic="proposals")
    assert "Active one" in out
    assert "Decided one" in out


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------


def test_cli_registers_timeline():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["timeline"])
    assert args.command == "timeline"
    assert hasattr(args, "date")
    assert hasattr(args, "hide_idle")


def test_cli_registers_messages():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["messages", "broadcast"])
    assert args.command == "messages"
    assert args.channel == "broadcast"


def test_cli_registers_strategy():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["strategy", "drives"])
    assert args.command == "strategy"
    assert args.topic == "drives"
