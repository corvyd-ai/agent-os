"""TDD tests for `agent-os agent list` and `agent-os agent show`."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from agent_os.config import Config


def _register(cfg: Config, agent_id: str, *, name: str = "The Agent", role: str = "Software Engineer") -> None:
    cfg.registry_dir.mkdir(parents=True, exist_ok=True)
    (cfg.registry_dir / f"{agent_id}.md").write_text(
        f"---\nid: {agent_id}\nname: {name}\nrole: {role}\n---\n\n# Agent description\n\nDescription goes here.\n"
    )


# --- agent list ------------------------------------------------------------


def test_render_agent_list_empty(aios_config: Config):
    from agent_os.agent_cmd import render_agent_list

    out = render_agent_list(aios_config)
    assert isinstance(out, str)
    assert "no agents" in out.lower() or out.strip() != ""


def test_render_agent_list_shows_ids_and_roles(aios_config: Config):
    from agent_os.agent_cmd import render_agent_list

    _register(aios_config, "agent-001-maker", name="The Maker", role="Software Engineer")
    _register(aios_config, "agent-002-writer", name="The Writer", role="Content Writer")

    out = render_agent_list(aios_config)
    assert "agent-001-maker" in out
    assert "agent-002-writer" in out
    assert "Software Engineer" in out


def test_render_agent_list_json(aios_config: Config):
    from agent_os.agent_cmd import render_agent_list_json

    _register(aios_config, "agent-001-maker")
    parsed = json.loads(render_agent_list_json(aios_config))
    assert isinstance(parsed, list)
    assert any(a["agent_id"] == "agent-001-maker" for a in parsed)


# --- agent show ------------------------------------------------------------


def test_render_agent_show_missing_returns_hint(aios_config: Config):
    from agent_os.agent_cmd import render_agent_show

    out = render_agent_show(aios_config, "agent-does-not-exist")
    assert "not found" in out.lower() or "unknown" in out.lower()


def test_render_agent_show_returns_role_and_body(aios_config: Config):
    from agent_os.agent_cmd import render_agent_show

    _register(aios_config, "agent-001-maker", name="The Maker", role="Software Engineer")
    out = render_agent_show(aios_config, "agent-001-maker")
    assert "agent-001-maker" in out
    assert "Software Engineer" in out
    # Body from the registry markdown should surface somewhere in the output.
    assert "Description goes here" in out


def test_render_agent_show_includes_today_cost(aios_config: Config):
    import json as _json

    from agent_os.agent_cmd import render_agent_show

    _register(aios_config, "agent-001-maker")
    today = datetime.now(aios_config.tz).date().isoformat()
    aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.costs_dir / f"{today}.jsonl").write_text(
        _json.dumps({"agent": "agent-001-maker", "task": "task-x", "cost_usd": 1.5}) + "\n"
    )

    out = render_agent_show(aios_config, "agent-001-maker")
    assert "1.5" in out or "1.50" in out


def test_render_agent_show_shows_recent_activity(aios_config: Config):
    import json as _json

    from agent_os.agent_cmd import render_agent_show

    agent = "agent-001-maker"
    _register(aios_config, agent)
    today = datetime.now(aios_config.tz).date().isoformat()
    ts = datetime.now(UTC).isoformat()
    (aios_config.logs_dir / agent).mkdir(parents=True, exist_ok=True)
    (aios_config.logs_dir / agent / f"{today}.jsonl").write_text(
        _json.dumps({"action": "task_complete", "task": "task-abc", "timestamp": ts}) + "\n"
    )

    out = render_agent_show(aios_config, agent)
    assert "task_complete" in out or "task-abc" in out


# --- CLI wiring ------------------------------------------------------------


def test_cli_registers_agent_subparser():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["agent", "list"])
    assert args.command == "agent"
    assert args.agent_action == "list"

    args = parser.parse_args(["agent", "show", "agent-001-maker"])
    assert args.agent_action == "show"
    assert args.agent_id == "agent-001-maker"
