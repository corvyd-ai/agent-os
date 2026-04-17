"""Tests for agent_os.release_notes — platform update notes for agents."""

from pathlib import Path

from agent_os.release_notes import (
    UpdateNotesResult,
    _append_changelog_entry,
    _build_broadcast_body,
    _render_reference_doc,
    write_update_notes,
)


class TestRenderReferenceDoc:
    def test_includes_version(self):
        rendered = _render_reference_doc(version="0.3.0", generated_at="2026-04-16T12:00:00")
        assert "v0.3.0" in rendered
        assert "2026-04-16T12:00:00" in rendered

    def test_still_contains_workspace_section(self):
        """The reference doc's whole point is to explain the workspace SDLC.
        If this ever stops rendering, agents lose that guidance."""
        rendered = _render_reference_doc(version="0.3.0", generated_at="now")
        assert "Workspace SDLC" in rendered
        assert "Do not run `git` commands" in rendered


class TestAppendChangelogEntry:
    def test_creates_file_with_header(self, tmp_path):
        path = tmp_path / "platform-changelog.md"
        _append_changelog_entry(
            path,
            previous_version="0.2.3",
            new_version="0.3.0",
            commit_subjects=["feat: add thing", "fix: thing"],
            timestamp="2026-04-16T12:00:00",
        )
        content = path.read_text()
        assert "# agent-os Platform Changelog" in content
        assert "v0.3.0" in content
        assert "feat: add thing" in content

    def test_prepends_new_entry(self, tmp_path):
        path = tmp_path / "platform-changelog.md"
        _append_changelog_entry(
            path,
            previous_version="0.1.0",
            new_version="0.2.0",
            commit_subjects=["feat: first update"],
            timestamp="2026-04-14T12:00:00",
        )
        _append_changelog_entry(
            path,
            previous_version="0.2.0",
            new_version="0.3.0",
            commit_subjects=["feat: second update"],
            timestamp="2026-04-16T12:00:00",
        )
        content = path.read_text()
        # Newer entry should appear before older entry
        idx_new = content.index("v0.3.0")
        idx_old = content.index("v0.2.0")
        assert idx_new < idx_old

    def test_preserves_existing_entries(self, tmp_path):
        path = tmp_path / "platform-changelog.md"
        _append_changelog_entry(
            path,
            previous_version="0.1.0",
            new_version="0.2.0",
            commit_subjects=["feat: v2"],
            timestamp="2026-04-14T12:00:00",
        )
        _append_changelog_entry(
            path,
            previous_version="0.2.0",
            new_version="0.3.0",
            commit_subjects=["feat: v3"],
            timestamp="2026-04-16T12:00:00",
        )
        content = path.read_text()
        assert "feat: v2" in content
        assert "feat: v3" in content
        # Header appears exactly once
        assert content.count("# agent-os Platform Changelog") == 1


class TestBuildBroadcastBody:
    def test_mentions_both_version_numbers(self):
        body = _build_broadcast_body(
            previous_version="0.2.3",
            new_version="0.3.0",
            commit_subjects=["feat: x"],
            reference_doc_relpath="knowledge/technical/agent-os-platform.md",
            changelog_relpath="knowledge/technical/platform-changelog.md",
        )
        assert "v0.2.3" in body
        assert "v0.3.0" in body

    def test_points_to_reference_doc(self):
        body = _build_broadcast_body(
            previous_version="0.2.3",
            new_version="0.3.0",
            commit_subjects=[],
            reference_doc_relpath="knowledge/technical/agent-os-platform.md",
            changelog_relpath="knowledge/technical/platform-changelog.md",
        )
        assert "knowledge/technical/agent-os-platform.md" in body

    def test_warns_about_stale_mental_model(self):
        """The broadcast's core message is 'your understanding may be stale' —
        this prevents agents from continuing to act on outdated runbooks."""
        body = _build_broadcast_body(
            previous_version="0.2.3",
            new_version="0.3.0",
            commit_subjects=["feat: x"],
            reference_doc_relpath="r.md",
            changelog_relpath="c.md",
        )
        assert "out of date" in body.lower() or "stale" in body.lower()

    def test_caps_long_commit_lists(self):
        subjects = [f"commit {i}" for i in range(25)]
        body = _build_broadcast_body(
            previous_version="0.2.3",
            new_version="0.3.0",
            commit_subjects=subjects,
            reference_doc_relpath="r.md",
            changelog_relpath="c.md",
        )
        # First 10 should appear, rest should be summarized
        assert "commit 0" in body
        assert "commit 9" in body
        assert "15 more" in body or "and 15" in body


class TestWriteUpdateNotes:
    def test_writes_all_three_artifacts(self, aios_config):
        from agent_os.config import Config

        cfg = Config(company_root=aios_config.company_root, log_also_print=False)
        result = write_update_notes(
            previous_commit="abc123",
            new_commit="def456",
            commit_subjects=["feat: add observability", "fix: respect runtime user"],
            previous_version="0.2.3",
            new_version="0.3.0",
            config=cfg,
        )

        assert isinstance(result, UpdateNotesResult)
        assert result.errors == []

        # 1. Reference doc
        assert result.reference_doc_path
        ref_path = Path(result.reference_doc_path)
        assert ref_path.exists()
        ref_content = ref_path.read_text()
        assert "v0.3.0" in ref_content
        assert "Workspace SDLC" in ref_content

        # 2. Changelog
        assert result.changelog_path
        changelog_path = Path(result.changelog_path)
        assert changelog_path.exists()
        changelog_content = changelog_path.read_text()
        assert "v0.3.0" in changelog_content
        assert "feat: add observability" in changelog_content

        # 3. Broadcast
        assert result.broadcast_id
        broadcasts = list(cfg.broadcast_dir.glob("*.md"))
        assert len(broadcasts) == 1
        broadcast_content = broadcasts[0].read_text()
        assert "v0.3.0" in broadcast_content
        assert "v0.2.3" in broadcast_content

    def test_regenerates_reference_doc_on_each_call(self, aios_config):
        """Reference doc reflects the CURRENT version — must be overwritten,
        not accumulated."""
        from agent_os.config import Config

        cfg = Config(company_root=aios_config.company_root, log_also_print=False)

        write_update_notes(
            previous_commit="a",
            new_commit="b",
            commit_subjects=[],
            previous_version="0.1.0",
            new_version="0.2.0",
            config=cfg,
        )
        write_update_notes(
            previous_commit="b",
            new_commit="c",
            commit_subjects=[],
            previous_version="0.2.0",
            new_version="0.3.0",
            config=cfg,
        )

        ref_path = cfg.company_root / "knowledge" / "technical" / "agent-os-platform.md"
        content = ref_path.read_text()
        # Old version no longer appears in the reference doc
        assert "v0.3.0" in content
        # The doc should not contain v0.2.0 as the current version (it may
        # appear nowhere since the reference doc renders the current version
        # only — not history)
        assert "**agent-os v0.2.0**" not in content

    def test_changelog_accumulates_across_updates(self, aios_config):
        """The changelog is the opposite of the reference doc: it accumulates,
        never overwrites."""
        from agent_os.config import Config

        cfg = Config(company_root=aios_config.company_root, log_also_print=False)

        write_update_notes(
            previous_commit="a",
            new_commit="b",
            commit_subjects=["first feature"],
            previous_version="0.1.0",
            new_version="0.2.0",
            config=cfg,
        )
        write_update_notes(
            previous_commit="b",
            new_commit="c",
            commit_subjects=["second feature"],
            previous_version="0.2.0",
            new_version="0.3.0",
            config=cfg,
        )

        changelog = (cfg.company_root / "knowledge" / "technical" / "platform-changelog.md").read_text()
        assert "first feature" in changelog
        assert "second feature" in changelog
