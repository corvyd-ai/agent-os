"""Tests for agent-os Config, including TOML loading and override mechanisms."""

from pathlib import Path

import pytest

from agent_os.config import Config


@pytest.fixture
def toml_dir(tmp_path):
    """Create a directory with a company root and return it."""
    company = tmp_path / "company"
    company.mkdir()
    (company / "agents" / "registry").mkdir(parents=True)
    return tmp_path


def _write_toml(path: Path, content: str) -> Path:
    toml_file = path / "agent-os.toml"
    toml_file.write_text(content)
    return toml_file


class TestFromToml:
    def test_basic_company_fields(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            """
[company]
name = "TestCo"
root = "company"
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.company_name == "TestCo"
        assert cfg.company_root == toml_dir / "company"

    def test_runtime_model(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            """
[company]
root = "company"

[runtime]
model = "claude-sonnet-4-6"
builder_roles = ["Software Engineer", "DevOps"]
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.default_model == "claude-sonnet-4-6"
        assert cfg.builder_roles == frozenset({"Software Engineer", "DevOps"})

    def test_budget_overrides(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            """
[company]
root = "company"

[budget]
task = 10.00
dream = 3.00
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.max_budget_per_invocation_usd == 10.00
        assert cfg.dream_max_budget_usd == 3.00
        # Unset fields keep defaults
        assert cfg.standing_orders_max_budget_usd == 2.00

    def test_role_tools(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            """
[company]
root = "company"

[roles]
"Custom Role" = ["Read", "Write", "Bash"]
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.role_tools == {"Custom Role": ["Read", "Write", "Bash"]}

    def test_prompts_override_dir(self, toml_dir):
        prompts = toml_dir / "my-prompts"
        prompts.mkdir()
        toml = _write_toml(
            toml_dir,
            """
[company]
root = "company"

[prompts]
override_dir = "my-prompts"
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.prompts_override_dir == toml_dir / "my-prompts"

    def test_feedback_routing(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            """
[company]
root = "company"

[feedback_routing]
catch_all = "agent-000-steward"

[feedback_routing.tags]
dashboard = ["agent-001-maker"]
strategy = ["agent-006-strategist"]
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.feedback_routing["catch_all"] == "agent-000-steward"
        assert cfg.feedback_routing["tags"]["dashboard"] == ["agent-001-maker"]

    def test_absolute_root(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            f"""
[company]
root = "{toml_dir / "company"}"
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.company_root == toml_dir / "company"

    def test_defaults_preserved_without_toml(self):
        cfg = Config()
        assert cfg.company_name == "My Company"
        assert cfg.role_tools == {}
        assert cfg.feedback_routing == {}
        assert cfg.prompts_override_dir is None

    def test_notifications_event_overrides(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            """
[company]
root = "company"

[notifications]
min_severity = "warning"

[notifications.events]
message_for_human = "info"
daily_digest = "critical"
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.notifications_min_severity == "warning"
        assert cfg.notifications_event_overrides == {
            "message_for_human": "info",
            "daily_digest": "critical",
        }

    def test_notifications_no_event_overrides(self, toml_dir):
        toml = _write_toml(
            toml_dir,
            """
[company]
root = "company"

[notifications]
min_severity = "info"
""",
        )
        cfg = Config.from_toml(toml)
        assert cfg.notifications_event_overrides == {}


class TestDiscoverToml:
    def test_finds_toml_in_directory(self, tmp_path):
        (tmp_path / "agent-os.toml").write_text('[company]\nname = "Found"\n')
        result = Config.discover_toml(tmp_path)
        assert result == tmp_path / "agent-os.toml"

    def test_finds_toml_in_parent(self, tmp_path):
        (tmp_path / "agent-os.toml").write_text('[company]\nname = "Found"\n')
        child = tmp_path / "sub" / "dir"
        child.mkdir(parents=True)
        result = Config.discover_toml(child)
        assert result == tmp_path / "agent-os.toml"

    def test_returns_none_when_missing(self, tmp_path):
        result = Config.discover_toml(tmp_path)
        assert result is None

    def test_env_var_override(self, tmp_path, monkeypatch):
        toml_file = tmp_path / "custom.toml"
        toml_file.write_text('[company]\nname = "EnvVar"\n')
        monkeypatch.setenv("AGENT_OS_CONFIG", str(toml_file))
        result = Config.discover_toml(tmp_path)
        assert result == toml_file


class TestFeedbackDir:
    def test_feedback_dir_property(self):
        cfg = Config(company_root=Path("/tmp/test"))
        assert cfg.feedback_dir == Path("/tmp/test/agents/messages/feedback")
