"""TDD tests for `agent-os health`. Thin wrapper over the metrics engine
with human/JSON output modes.

Written red-first.
"""

from __future__ import annotations

import json

from agent_os.config import Config


def _register(cfg: Config, agent_id: str) -> None:
    cfg.registry_dir.mkdir(parents=True, exist_ok=True)
    (cfg.registry_dir / f"{agent_id}.md").write_text(f"---\nid: {agent_id}\n---\n")


# --------------------------------------------------------------------------
# Cycle 1: render_health returns a human-readable string with a system composite
# --------------------------------------------------------------------------


def test_render_health_returns_string(aios_config: Config):
    from agent_os.health_cmd import render_health

    out = render_health(aios_config)
    assert isinstance(out, str)
    assert len(out) > 0


def test_render_health_includes_system_composite_label(aios_config: Config):
    from agent_os.health_cmd import render_health

    out = render_health(aios_config)
    assert "system" in out.lower() or "composite" in out.lower()


# --------------------------------------------------------------------------
# Cycle 2: per-agent rows appear when registry has entries
# --------------------------------------------------------------------------


def test_render_health_lists_registered_agents(aios_config: Config):
    from agent_os.health_cmd import render_health

    _register(aios_config, "agent-001-maker")
    _register(aios_config, "agent-002-writer")

    out = render_health(aios_config)
    assert "agent-001-maker" in out
    assert "agent-002-writer" in out


def test_render_health_filters_to_single_agent(aios_config: Config):
    from agent_os.health_cmd import render_health

    _register(aios_config, "agent-001-maker")
    _register(aios_config, "agent-002-writer")

    out = render_health(aios_config, agent="agent-001-maker")
    assert "agent-001-maker" in out
    assert "agent-002-writer" not in out


# --------------------------------------------------------------------------
# Cycle 3: JSON mode returns parseable JSON with expected shape
# --------------------------------------------------------------------------


def test_render_health_json_is_parseable(aios_config: Config):
    from agent_os.health_cmd import render_health_json

    _register(aios_config, "agent-001-maker")
    payload = render_health_json(aios_config)

    parsed = json.loads(payload)
    assert "system_composite" in parsed
    assert "agents" in parsed
    assert "agent-001-maker" in parsed["agents"]


def test_render_health_json_respects_days(aios_config: Config):
    from agent_os.health_cmd import render_health_json

    payload = render_health_json(aios_config, days=30)
    parsed = json.loads(payload)
    assert parsed["period_days"] == 30


# --------------------------------------------------------------------------
# Cycle 4: CLI wiring — `agent-os health` registers + dispatches
# --------------------------------------------------------------------------


def test_cli_registers_health_subparser():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["health"])
    assert args.command == "health"
    assert hasattr(args, "days")
    assert hasattr(args, "format")


def test_cli_health_json_flag(capsys, aios_config: Config):
    from agent_os.cli import cmd_health
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    _register(aios_config, "agent-001-maker")

    args = type(
        "Args",
        (),
        {
            "format": "json",
            "agent": None,
            "days": 7,
            "root": str(aios_config.company_root),
            "config": None,
        },
    )()

    configure(aios_config)
    try:
        cmd_health(args)
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "agents" in parsed
    # Tighten: the seeded agent should actually appear.
    assert "agent-001-maker" in parsed["agents"]
