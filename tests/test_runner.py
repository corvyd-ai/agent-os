"""Tests for runner, PromptComposer, ErrorClassifier, and Config.

No SDK calls. Tests construct AgentConfig directly and call pure functions.
"""

from datetime import UTC
from pathlib import Path

import pytest

from agent_os.composer import PromptComposer
from agent_os.config import Config, configure, get_config
from agent_os.errors import ClaudeErrorClassifier
from agent_os.registry import AgentConfig
from agent_os.runner import (
    _classify_idle_cycle,
    _compute_expected_at,
    _find_product_code_dir,
    _streaming_prompt,
)


def _make_agent_config(**overrides):
    """Build a minimal AgentConfig for testing."""
    defaults = {
        "agent_id": "agent-001-maker",
        "name": "The Maker",
        "role": "Software Engineer",
        "model": "claude-opus-4-6",
        "allowed_tools": ["Read", "Write", "Edit", "Bash"],
        "registry_path": Path("/tmp/fake-registry.md"),
        "system_body": "You are The Maker. You build things.",
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


# ── Config dataclass ─────────────────────────────────────────────────


def test_config_defaults():
    cfg = Config()
    assert cfg.default_model == "claude-opus-4-6"
    assert cfg.max_budget_per_invocation_usd == 5.0
    assert cfg.max_turns_per_invocation == 50


def test_config_derived_paths():
    cfg = Config(company_root=Path("/tmp/test-co"))
    assert cfg.agents_dir == Path("/tmp/test-co/agents")
    assert cfg.tasks_queued == Path("/tmp/test-co/agents/tasks/queued")
    assert cfg.costs_dir == Path("/tmp/test-co/finance/costs")
    assert cfg.values_file == Path("/tmp/test-co/identity/values.md")
    assert cfg.broadcast_dir == Path("/tmp/test-co/agents/messages/broadcast")


def test_config_frozen():
    cfg = Config()
    with pytest.raises(AttributeError):
        cfg.default_model = "something-else"


def test_config_singleton():
    cfg = Config(company_root=Path("/tmp/test-singleton"))
    configure(cfg)
    assert get_config().company_root == Path("/tmp/test-singleton")
    # Restore default
    configure(Config())


def test_config_builder_roles():
    cfg = Config()
    assert "Software Engineer" in cfg.builder_roles
    assert "PM / PMM" not in cfg.builder_roles


# ── PromptComposer ───────────────────────────────────────────────────


def test_build_system_prompt_contains_preamble(aios_fs):
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config()
    prompt = composer.build_system_prompt(agent)
    assert "agent-os" in prompt


def test_build_system_prompt_contains_identity(aios_fs):
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config(system_body="You are The Maker. Craft is everything.")
    prompt = composer.build_system_prompt(agent)
    assert "Craft is everything." in prompt


def test_build_system_prompt_values_injected(aios_fs):
    aios_fs["VALUES_FILE"].write_text("# Values\n\nKeep it simple.")
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config()
    prompt = composer.build_system_prompt(agent)
    assert "Keep it simple." in prompt


def test_build_system_prompt_soul_injected(aios_fs):
    soul_dir = aios_fs["AGENTS_STATE_DIR"] / "agent-001-maker"
    soul_dir.mkdir(parents=True, exist_ok=True)
    (soul_dir / "soul.md").write_text("I find beauty in clean architecture.")
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config()
    prompt = composer.build_system_prompt(agent)
    assert "clean architecture" in prompt


def test_build_system_prompt_quality_gates_for_builder(aios_fs):
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config(role="Software Engineer")
    prompt = composer.build_system_prompt(agent)
    assert "Quality Gates" in prompt


def test_build_system_prompt_no_quality_gates_for_non_builder(aios_fs):
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config(role="PM / PMM")
    prompt = composer.build_system_prompt(agent)
    assert "Quality Gates" not in prompt


def test_build_system_prompt_task_context_appended(aios_fs):
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config()
    prompt = composer.build_system_prompt(agent, task_context="Build the widget service.")
    assert "Build the widget service." in prompt
    assert "Current Task" in prompt


def test_build_system_prompt_layer_ordering(aios_fs):
    """Verify prompt layers appear in correct order: preamble → values → soul → identity → working memory."""
    aios_fs["VALUES_FILE"].write_text("MARKER_VALUES")
    soul_dir = aios_fs["AGENTS_STATE_DIR"] / "agent-001-maker"
    soul_dir.mkdir(parents=True, exist_ok=True)
    (soul_dir / "soul.md").write_text("MARKER_SOUL")
    wm_dir = aios_fs["AGENTS_STATE_DIR"] / "agent-001-maker"
    (wm_dir / "working-memory.md").write_text("MARKER_WM")

    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config()
    prompt = composer.build_system_prompt(agent)

    idx_values = prompt.index("MARKER_VALUES")
    idx_soul = prompt.index("MARKER_SOUL")
    idx_identity = prompt.index("Your Identity")
    idx_wm = prompt.index("MARKER_WM")

    assert idx_values < idx_soul < idx_identity < idx_wm


def test_prompt_composer_get_sections(aios_fs):
    """get_sections yields named sections in order."""
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    agent = _make_agent_config()
    sections = list(composer.get_sections(agent))
    names = [name for name, _ in sections]
    assert "preamble" in names
    assert "identity" in names
    # Quality gates present for builder
    assert "quality_gates" in names


def test_prompt_composer_render_template(aios_fs):
    """render_template works for known templates."""
    cfg = Config(company_root=aios_fs["COMPANY_ROOT"])
    composer = PromptComposer(config=cfg)
    result = composer.render_template("dream.jinja2", agent_id="agent-001-maker")
    assert "dream" in result.lower()
    assert "agent-001-maker" in result


# ── ErrorClassifier ──────────────────────────────────────────────────

_classifier = ClaudeErrorClassifier()


def test_classify_transient():
    cat, retryable = _classifier.classify("rate_limit exceeded")
    assert cat == "transient"
    assert retryable is True


def test_classify_permanent():
    cat, retryable = _classifier.classify("authentication_failed")
    assert cat == "permanent"
    assert retryable is False


def test_classify_unknown():
    cat, retryable = _classifier.classify("something unexpected")
    assert cat == "unknown"
    assert retryable is False


def test_format_exception_detail_regular():
    e = ValueError("something broke")
    result = _classifier.format_detail(e)
    assert "ValueError" in result
    assert "something broke" in result


def test_format_exception_detail_exception_group():
    sub1 = ConnectionError("not ready for writing")
    sub2 = TimeoutError("timed out")
    eg = ExceptionGroup("TaskGroup errors", [sub1, sub2])
    result = _classifier.format_detail(eg)
    assert "ConnectionError" in result
    assert "not ready for writing" in result
    assert "TimeoutError" in result
    assert "timed out" in result


def test_is_benign_transport_cleanup_true():
    """ExceptionGroup with all CLIConnectionError 'not ready' → benign."""
    try:
        from claude_agent_sdk._errors import CLIConnectionError
    except ImportError:
        pytest.skip("CLIConnectionError not available")
    sub = CLIConnectionError("ProcessTransport is not ready for writing")
    eg = ExceptionGroup("errors", [sub])
    assert _classifier.is_benign_cleanup(eg) is True


def test_is_benign_transport_cleanup_false_regular():
    """Regular exceptions are not benign."""
    assert _classifier.is_benign_cleanup(ValueError("oops")) is False


def test_is_benign_transport_cleanup_false_mixed():
    """ExceptionGroup with non-transport errors is not benign."""
    sub1 = ConnectionError("not ready for writing")
    sub2 = ValueError("something else")
    eg = ExceptionGroup("errors", [sub1, sub2])
    assert _classifier.is_benign_cleanup(eg) is False


def test_is_benign_transport_cleanup_empty():
    """Regular exception is not benign."""
    assert _classifier.is_benign_cleanup(RuntimeError("no")) is False


def test_build_error_refs():
    """build_error_refs produces structured data for logging."""
    e = ValueError("test error")
    refs = _classifier.build_error_refs(e, "some stderr")
    assert refs["error_class"] == "ValueError"
    assert refs["error_category"] == "unknown"
    assert refs["retryable"] is False
    assert "stderr" in refs


# ── Runner helpers ───────────────────────────────────────────────────


def test_find_product_code_dir_found(aios_config):
    code_dir = aios_config.company_root / "products" / "jsonyaml" / "code"
    code_dir.mkdir(parents=True)
    result = _find_product_code_dir({"product": "jsonyaml"}, config=aios_config)
    assert result == code_dir


def test_find_product_code_dir_not_found(aios_config):
    result = _find_product_code_dir({"product": "nonexistent"}, config=aios_config)
    assert result is None


def test_find_product_code_dir_no_product_field():
    result = _find_product_code_dir({})
    assert result is None


@pytest.mark.asyncio
async def test_streaming_prompt_format():
    messages = []
    async for msg in _streaming_prompt("Hello, agent"):
        messages.append(msg)
    assert len(messages) == 1
    assert messages[0]["type"] == "user"
    assert messages[0]["message"]["role"] == "user"
    assert messages[0]["message"]["content"] == "Hello, agent"


# ── Cycle classification ────────────────────────────────────────────


def test_classify_idle_cycle_no_tasks(aios_config):
    """Empty queue → idle."""
    result = _classify_idle_cycle("agent-001-maker", config=aios_config)
    assert result == "idle"


def test_classify_idle_cycle_starved(aios_config):
    """Tasks exist but none assigned to this agent → starved."""
    from agent_os.core import _write_frontmatter

    task_path = aios_config.tasks_queued / "task-2026-0101-001.md"
    meta = {
        "id": "task-2026-0101-001",
        "title": "Other agent's task",
        "status": "queued",
        "priority": "medium",
        "assigned_to": "agent-005-grower",
    }
    _write_frontmatter(task_path, meta, "Work.")
    result = _classify_idle_cycle("agent-001-maker", config=aios_config)
    assert result == "starved"


def test_classify_idle_cycle_blocked(aios_config):
    """Task assigned to agent but dependency unsatisfied → blocked."""
    from agent_os.core import _write_frontmatter

    task_path = aios_config.tasks_queued / "task-2026-0101-002.md"
    meta = {
        "id": "task-2026-0101-002",
        "title": "Blocked task",
        "status": "queued",
        "priority": "medium",
        "assigned_to": "agent-001-maker",
        "depends_on": ["task-2026-0101-001"],  # Not in done/
    }
    _write_frontmatter(task_path, meta, "Work.")
    result = _classify_idle_cycle("agent-001-maker", config=aios_config)
    assert result == "blocked"


# ── Schedule tracking (expected_at) ─────────────────────────────────


def test_compute_expected_at_first_run(aios_config):
    """No cadence file → 'first_run'."""
    result = _compute_expected_at("agent-001-maker", "health-scan", 24.0, config=aios_config)
    assert result == "first_run"


def test_compute_expected_at_with_cadence(aios_config):
    """Cadence file exists → expected = last_run + cadence_hours."""
    from datetime import datetime, timedelta

    cadence_dir = aios_config.logs_dir / "agent-001-maker"
    cadence_dir.mkdir(parents=True, exist_ok=True)
    cadence_file = cadence_dir / ".cadence-health-scan"
    last_run = datetime(2026, 3, 3, 7, 0, 0, tzinfo=UTC)
    cadence_file.write_text(last_run.isoformat())

    result = _compute_expected_at("agent-001-maker", "health-scan", 12.0, config=aios_config)
    expected = last_run + timedelta(hours=12)
    assert result == expected.isoformat()
