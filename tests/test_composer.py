"""Tests for PromptComposer — template chain loading, feedback routing, and failure injection."""

from pathlib import Path

import pytest
import yaml

from agent_os.composer import PromptComposer
from agent_os.config import Config
from agent_os.registry import AgentConfig


@pytest.fixture
def company_root(tmp_path):
    """Create a minimal company filesystem."""
    root = tmp_path / "company"
    for d in [
        "agents/registry",
        "agents/state",
        "agents/tasks/queued",
        "agents/messages/broadcast",
        "agents/messages/threads",
        "agents/messages/feedback",
        "agents/logs",
        "identity",
        "strategy/drives",
        "strategy/proposals/active",
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "identity" / "values.md").write_text("Be excellent.")
    (root / "strategy" / "drives.md").write_text("Ship products.")
    return root


@pytest.fixture
def agent_config():
    return AgentConfig(
        agent_id="agent-001-builder",
        name="The Builder",
        role="Software Engineer",
        model="claude-sonnet-4-6",
        allowed_tools=["Read", "Write"],
        registry_path=Path("/tmp/fake.md"),
        system_body="I build things.",
    )


class TestChainLoader:
    def test_company_template_shadows_default(self, company_root, agent_config, tmp_path):
        """Company override template should take priority over package default."""
        override_dir = tmp_path / "prompts"
        override_dir.mkdir()
        (override_dir / "preamble.jinja2").write_text("COMPANY PREAMBLE for {{ today }}")

        cfg = Config(company_root=company_root, prompts_override_dir=override_dir)
        composer = PromptComposer(config=cfg)

        result = composer.render_template("preamble.jinja2", company_root=company_root, today="2026-03-07")
        assert "COMPANY PREAMBLE" in result

    def test_fallback_to_default_when_no_override(self, company_root, agent_config, tmp_path):
        """Templates not in override dir should fall back to package defaults."""
        override_dir = tmp_path / "prompts"
        override_dir.mkdir()
        # Don't create preamble.jinja2 — should fall back to package default

        cfg = Config(company_root=company_root, prompts_override_dir=override_dir)
        composer = PromptComposer(config=cfg)

        result = composer.render_template("preamble.jinja2", company_root=company_root, today="2026-03-07")
        # Package default preamble should have agent-os content
        assert "agent" in result.lower() or "operating" in result.lower()

    def test_no_override_dir_uses_defaults(self, company_root, agent_config):
        """Without an override dir, package defaults are used."""
        cfg = Config(company_root=company_root)
        composer = PromptComposer(config=cfg)
        result = composer.render_template("preamble.jinja2", company_root=company_root, today="2026-03-07")
        assert len(result) > 0

    def test_nonexistent_override_dir_ignored(self, company_root, agent_config, tmp_path):
        """A configured but nonexistent override dir should be silently ignored."""
        cfg = Config(company_root=company_root, prompts_override_dir=tmp_path / "nope")
        composer = PromptComposer(config=cfg)
        # Should still work with package defaults
        result = composer.render_template("preamble.jinja2", company_root=company_root, today="2026-03-07")
        assert len(result) > 0


class TestFeedbackRouting:
    def _make_note(self, feedback_dir, note_id, tags=None, status="open"):
        import yaml

        meta = {"id": note_id, "status": status, "created": "2026-03-07"}
        if tags:
            meta["tags"] = tags
        content = f"---\n{yaml.dump(meta)}---\n\nNote body for {note_id}"
        (feedback_dir / f"{note_id}.md").write_text(content)

    def test_no_routing_all_agents_see_all(self, company_root, agent_config):
        """Without feedback_routing config, all agents see all notes."""
        feedback_dir = company_root / "agents" / "messages" / "feedback"
        self._make_note(feedback_dir, "note-001", tags=["dashboard"])

        cfg = Config(company_root=company_root)  # No feedback_routing
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(agent_config))
        assert "system_notes" in sections

    def test_catch_all_sees_everything(self, company_root):
        """The catch-all agent sees all notes regardless of tags."""
        feedback_dir = company_root / "agents" / "messages" / "feedback"
        self._make_note(feedback_dir, "note-001", tags=["strategy"])

        steward = AgentConfig(
            agent_id="agent-000-steward",
            name="Steward",
            role="Board Secretary / Human Interface",
            model="claude-sonnet-4-6",
            allowed_tools=["Read"],
            registry_path=Path("/tmp/f.md"),
            system_body="I govern.",
        )

        cfg = Config(
            company_root=company_root,
            feedback_routing={"catch_all": "agent-000-steward", "tags": {"strategy": ["agent-006"]}},
        )
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(steward))
        assert "system_notes" in sections

    def test_tagged_agent_sees_matching_notes(self, company_root):
        """An agent sees notes tagged for their domain."""
        feedback_dir = company_root / "agents" / "messages" / "feedback"
        self._make_note(feedback_dir, "note-001", tags=["dashboard"])

        maker = AgentConfig(
            agent_id="agent-001-maker",
            name="Maker",
            role="Software Engineer",
            model="claude-sonnet-4-6",
            allowed_tools=["Read"],
            registry_path=Path("/tmp/f.md"),
            system_body="I make.",
        )

        cfg = Config(
            company_root=company_root,
            feedback_routing={
                "catch_all": "agent-000-steward",
                "tags": {"dashboard": ["agent-001-maker"]},
            },
        )
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(maker))
        assert "system_notes" in sections

    def test_unrelated_agent_doesnt_see_notes(self, company_root):
        """An agent without matching tags doesn't see the notes."""
        feedback_dir = company_root / "agents" / "messages" / "feedback"
        self._make_note(feedback_dir, "note-001", tags=["dashboard"])

        strategist = AgentConfig(
            agent_id="agent-006-strategist",
            name="Strategist",
            role="PM / PMM",
            model="claude-sonnet-4-6",
            allowed_tools=["Read"],
            registry_path=Path("/tmp/f.md"),
            system_body="I strategize.",
        )

        cfg = Config(
            company_root=company_root,
            feedback_routing={
                "catch_all": "agent-000-steward",
                "tags": {"dashboard": ["agent-001-maker"]},
            },
        )
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(strategist))
        assert "system_notes" not in sections


class TestFailureInjection:
    """Failed tasks appear in the right agents' system prompts."""

    @staticmethod
    def _make_failed_task(failed_dir, task_id, title, assigned_to, reason="Something broke"):
        """Write a minimal failed-task file to the failed/ directory."""
        meta = {
            "id": task_id,
            "title": title,
            "assigned_to": assigned_to,
            "status": "failed",
            "outcome": "failure",
            "created_at": "2026-05-03T10:00:00-07:00",
        }
        body = f"Task body for {task_id}.\n\n## Failure\n\n**Date**: 2026-05-03T12:00:00-07:00\n**Reason**: {reason}\n"
        content = f"---\n{yaml.dump(meta, default_flow_style=False, sort_keys=False)}---\n\n{body}"
        (failed_dir / f"{task_id}.md").write_text(content)

    def test_agent_sees_own_failures(self, company_root, agent_config):
        """A builder agent sees its own recent failures."""
        failed_dir = company_root / "agents" / "tasks" / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        self._make_failed_task(failed_dir, "task-2026-0503-001", "Fix the widget", "agent-001-builder", "Build failed")

        cfg = Config(company_root=company_root)
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(agent_config))

        assert "recent_failures" in sections
        content = sections["recent_failures"]
        assert "task-2026-0503-001" in content
        assert "Fix the widget" in content
        assert "Build failed" in content
        assert "2026-05-03T12:00:00-07:00" in content
        # Should NOT contain the all-agents header
        assert "All Agents" not in content

    def test_agent_does_not_see_other_agents_failures(self, company_root, agent_config):
        """An agent does not see failures assigned to other agents."""
        failed_dir = company_root / "agents" / "tasks" / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        self._make_failed_task(failed_dir, "task-2026-0503-002", "Deploy infra", "agent-003-operator", "SSH timeout")

        cfg = Config(company_root=company_root)
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(agent_config))

        assert "recent_failures" not in sections

    def test_steward_sees_all_agent_failures(self, company_root):
        """The Steward sees failures from all agents (governance data)."""
        steward = AgentConfig(
            agent_id="agent-000-steward",
            name="Steward",
            role="Board Secretary / Human Interface",
            model="claude-sonnet-4-6",
            allowed_tools=["Read"],
            registry_path=Path("/tmp/f.md"),
            system_body="I govern.",
        )

        failed_dir = company_root / "agents" / "tasks" / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        self._make_failed_task(failed_dir, "task-2026-0503-010", "Build dashboard", "agent-001-builder", "Test failure")
        self._make_failed_task(
            failed_dir, "task-2026-0503-011", "Update DNS", "agent-003-operator", "Permission denied"
        )

        cfg = Config(company_root=company_root)
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(steward))

        assert "recent_failures" in sections
        content = sections["recent_failures"]
        # All-agents header
        assert "All Agents" in content
        # Both tasks visible
        assert "task-2026-0503-010" in content
        assert "task-2026-0503-011" in content
        # Agent attribution present in Steward view
        assert "agent-001-builder" in content
        assert "agent-003-operator" in content
        # Reasons present
        assert "Test failure" in content
        assert "Permission denied" in content

    def test_no_failures_no_section(self, company_root, agent_config):
        """When there are no failed tasks, the section is omitted."""
        # Ensure the failed dir exists but is empty
        failed_dir = company_root / "agents" / "tasks" / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)

        cfg = Config(company_root=company_root)
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(agent_config))

        assert "recent_failures" not in sections

    def test_failure_summary_is_concise(self, company_root, agent_config):
        """Summary includes task ID, title, reason, and timestamp — nothing more."""
        failed_dir = company_root / "agents" / "tasks" / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        self._make_failed_task(failed_dir, "task-2026-0503-005", "Run tests", "agent-001-builder", "pytest exit code 1")

        cfg = Config(company_root=company_root)
        composer = PromptComposer(config=cfg)
        sections = dict(composer.get_sections(agent_config))
        content = sections["recent_failures"]

        # Must contain the four required fields
        assert "task-2026-0503-005" in content  # task ID
        assert "Run tests" in content  # title
        assert "pytest exit code 1" in content  # reason
        assert "2026-05-03" in content  # timestamp
        # Must NOT contain the full task body
        assert "Task body for" not in content
