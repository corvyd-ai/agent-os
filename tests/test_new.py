"""Tests for `agent-os new` — human task creation (core + CLI)."""

import subprocess
import sys

from agent_os.core import _parse_frontmatter, create_task_human

# ── core: create_task_human ──────────────────────────────────────────


class TestCreateTaskHuman:
    def test_defaults_to_backlog(self, aios_config):
        task_id, dest = create_task_human("Fix the bug", config=aios_config)
        assert dest == "backlog"
        assert (aios_config.tasks_backlog / f"{task_id}.md").exists()

    def test_assigned_goes_to_queued(self, aios_config):
        task_id, dest = create_task_human("Fix the bug", assigned_to="agent-001", config=aios_config)
        assert dest == "queued"
        assert (aios_config.tasks_queued / f"{task_id}.md").exists()

    def test_frontmatter_fields(self, aios_config):
        task_id, _ = create_task_human(
            "Build login page",
            body="Acceptance criteria here.",
            assigned_to="agent-001",
            priority="high",
            tags=["feature", "mvp"],
            config=aios_config,
        )
        meta, body = _parse_frontmatter(aios_config.tasks_queued / f"{task_id}.md")
        assert meta["title"] == "Build login page"
        assert meta["created_by"] == "human"
        assert meta["assigned_to"] == "agent-001"
        assert meta["priority"] == "high"
        assert meta["tags"] == ["feature", "mvp"]
        assert meta["status"] == "queued"
        assert "Acceptance criteria here." in body

    def test_unassigned_frontmatter(self, aios_config):
        task_id, _ = create_task_human("Backlog idea", config=aios_config)
        meta, _ = _parse_frontmatter(aios_config.tasks_backlog / f"{task_id}.md")
        assert meta["assigned_to"] == ""
        assert meta["status"] == "backlog"
        assert meta["priority"] == "medium"
        assert meta["tags"] == []

    def test_sequential_ids(self, aios_config):
        id1, _ = create_task_human("First", config=aios_config)
        id2, _ = create_task_human("Second", config=aios_config)
        # Both share a date prefix, sequence numbers increment
        assert id1.rsplit("-", 1)[0] == id2.rsplit("-", 1)[0]
        seq1 = int(id1.rsplit("-", 1)[1])
        seq2 = int(id2.rsplit("-", 1)[1])
        assert seq2 == seq1 + 1

    def test_empty_body_default(self, aios_config):
        task_id, _ = create_task_human("No body", config=aios_config)
        _, body = _parse_frontmatter(aios_config.tasks_backlog / f"{task_id}.md")
        assert body == ""


# ── CLI: agent-os new ────────────────────────────────────────────────


def _init_company(tmp_path):
    """Create a minimal company directory with a registry agent."""
    from agent_os.cli import INIT_DIRS

    root = tmp_path / "test-co"
    for d in INIT_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    # Minimal config
    (root / "agent-os.toml").write_text('[company]\nname = "test-co"\nroot = "."\n')
    # One agent in registry
    (root / "agents" / "registry" / "agent-001-builder.md").write_text(
        "---\nid: agent-001-builder\nname: The Builder\nrole: Engineer\n---\n"
    )
    return root


class TestCmdNew:
    def test_basic_creates_backlog_task(self, tmp_path):
        root = _init_company(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "agent_os", "new", "Fix the bug", "--root", str(root)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "backlog/" in result.stdout
        assert "promote" in result.stdout

    def test_assigned_creates_queued_task(self, tmp_path):
        root = _init_company(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_os",
                "new",
                "Fix the bug",
                "-a",
                "agent-001-builder",
                "--root",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "queued/" in result.stdout
        assert "promote" not in result.stdout

    def test_invalid_agent_errors(self, tmp_path):
        root = _init_company(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_os",
                "new",
                "Fix the bug",
                "-a",
                "nonexistent-agent",
                "--root",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_priority_flag(self, tmp_path):
        root = _init_company(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_os",
                "new",
                "Urgent fix",
                "-p",
                "critical",
                "--root",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Verify the file has the right priority
        backlog = root / "agents" / "tasks" / "backlog"
        files = list(backlog.glob("task-*.md"))
        assert len(files) == 1
        meta, _ = _parse_frontmatter(files[0])
        assert meta["priority"] == "critical"

    def test_tag_flags(self, tmp_path):
        root = _init_company(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_os",
                "new",
                "Tagged task",
                "-t",
                "bugfix",
                "-t",
                "urgent",
                "--root",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        backlog = root / "agents" / "tasks" / "backlog"
        files = list(backlog.glob("task-*.md"))
        assert len(files) == 1
        meta, _ = _parse_frontmatter(files[0])
        assert meta["tags"] == ["bugfix", "urgent"]

    def test_stdin_body(self, tmp_path):
        root = _init_company(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_os",
                "new",
                "Task with body",
                "--root",
                str(root),
            ],
            input="This is the task description from stdin.",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        backlog = root / "agents" / "tasks" / "backlog"
        files = list(backlog.glob("task-*.md"))
        assert len(files) == 1
        _, body = _parse_frontmatter(files[0])
        assert "from stdin" in body
