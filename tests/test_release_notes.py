"""Tests for agent_os.release_notes — platform update notes for agents."""

from pathlib import Path

from agent_os.release_notes import (
    BackfillEntry,
    UpdateNotesResult,
    _append_changelog_entry,
    _build_broadcast_body,
    _changelog_has_entries,
    _render_reference_doc,
    _strip_v,
    build_backfill_entries,
    write_backfill_notes,
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


class TestStripV:
    def test_strips_v_prefix(self):
        assert _strip_v("v0.3.0") == "0.3.0"

    def test_leaves_non_version_tags_alone(self):
        assert _strip_v("stable") == "stable"
        assert _strip_v("release") == "release"

    def test_leaves_single_v_alone(self):
        assert _strip_v("v") == "v"


class TestChangelogHasEntries:
    def test_empty_file(self):
        assert not _changelog_has_entries("")

    def test_header_only(self):
        assert not _changelog_has_entries("# agent-os Platform Changelog\n\nSome description\n")

    def test_with_entry(self):
        text = "# agent-os Platform Changelog\n\n## v0.3.0 — 2026-04-16\n\nchanges\n"
        assert _changelog_has_entries(text)


class TestBuildBackfillEntries:
    def test_no_commits_returns_empty(self):
        entries = build_backfill_entries(commits=[], tags=[], current_version="0.3.0")
        assert entries == []

    def test_no_tags_produces_single_entry(self):
        commits = [
            ("sha1", "feat: first", "2026-01-01T00:00:00Z"),
            ("sha2", "feat: second", "2026-02-01T00:00:00Z"),
            ("sha3", "feat: third", "2026-03-01T00:00:00Z"),
        ]
        entries = build_backfill_entries(commits=commits, tags=[], current_version="0.3.0")
        assert len(entries) == 1
        assert entries[0].version == "0.3.0"
        assert entries[0].previous_version == "initial"
        # Newest first within the entry
        assert entries[0].commit_subjects == ["feat: third", "feat: second", "feat: first"]

    def test_groups_by_tag_boundary(self):
        commits = [
            ("sha1", "feat: A", "2026-01-01T00:00:00Z"),
            ("sha2", "feat: B", "2026-02-01T00:00:00Z"),  # <- v0.1.0
            ("sha3", "feat: C", "2026-02-15T00:00:00Z"),
            ("sha4", "feat: D", "2026-03-01T00:00:00Z"),  # <- v0.2.0
            ("sha5", "feat: E", "2026-04-01T00:00:00Z"),  # post-tag, goes to current
        ]
        tags = [
            ("v0.1.0", "sha2", "2026-02-01T00:00:00Z"),
            ("v0.2.0", "sha4", "2026-03-01T00:00:00Z"),
        ]
        entries = build_backfill_entries(commits=commits, tags=tags, current_version="0.3.0")
        # 3 entries: v0.1.0, v0.2.0, 0.3.0 (unreleased/current)
        assert len(entries) == 3
        # Newest first in the result
        assert entries[0].version == "0.3.0"
        assert entries[0].previous_version == "0.2.0"
        assert entries[0].commit_subjects == ["feat: E"]

        assert entries[1].version == "0.2.0"
        assert entries[1].previous_version == "0.1.0"
        # feat: D is the tagged commit; feat: C is between tags. Both belong to v0.2.0.
        assert set(entries[1].commit_subjects) == {"feat: C", "feat: D"}

        assert entries[2].version == "0.1.0"
        assert entries[2].previous_version == "initial"

    def test_no_post_tag_commits_omits_current_entry(self):
        commits = [
            ("sha1", "feat: A", "2026-01-01T00:00:00Z"),
            ("sha2", "feat: B", "2026-02-01T00:00:00Z"),
        ]
        tags = [
            ("v0.1.0", "sha2", "2026-02-01T00:00:00Z"),
        ]
        entries = build_backfill_entries(commits=commits, tags=tags, current_version="0.1.0")
        # HEAD is the tag — only one entry
        assert len(entries) == 1
        assert entries[0].version == "0.1.0"


class TestWriteBackfillNotes:
    def test_writes_all_three_artifacts(self, aios_config):
        from agent_os.config import Config

        cfg = Config(company_root=aios_config.company_root, log_also_print=False)
        entries = [
            BackfillEntry(
                version="0.3.0",
                previous_version="0.2.0",
                commit_subjects=["feat: thing"],
                timestamp="2026-04-16T12:00:00+00:00",
            ),
            BackfillEntry(
                version="0.2.0",
                previous_version="initial",
                commit_subjects=["feat: earlier"],
                timestamp="2026-03-01T12:00:00+00:00",
            ),
        ]
        result = write_backfill_notes(entries=entries, current_version="0.3.0", config=cfg)

        assert result.errors == []
        assert result.entries_written == 2
        assert result.broadcast_id  # broadcast posted by default

        changelog = Path(result.changelog_path).read_text()
        # Newest on top
        idx_new = changelog.index("v0.3.0")
        idx_old = changelog.index("v0.2.0")
        assert idx_new < idx_old
        # Backfill notice is present and sits above the entries
        assert "backfilled" in changelog.lower()
        idx_note = changelog.lower().index("backfilled")
        assert idx_note < idx_new

    def test_respects_no_broadcast(self, aios_config):
        from agent_os.config import Config

        cfg = Config(company_root=aios_config.company_root, log_also_print=False)
        entries = [
            BackfillEntry(
                version="0.3.0",
                previous_version="initial",
                commit_subjects=["x"],
                timestamp="2026-04-16T12:00:00+00:00",
            )
        ]
        result = write_backfill_notes(entries=entries, current_version="0.3.0", post_broadcast=False, config=cfg)

        assert result.broadcast_id == ""
        # No broadcast file should have been written
        broadcasts = list(cfg.broadcast_dir.glob("*.md"))
        assert broadcasts == []

    def test_refuses_to_clobber_existing_changelog(self, aios_config):
        """If the changelog already has entries, backfill bails unless force=True.
        Protects against accidentally stomping live history after a few
        normal updates have landed."""
        from agent_os.config import Config

        cfg = Config(company_root=aios_config.company_root, log_also_print=False)

        # Simulate a few normal updates having already landed
        write_update_notes(
            previous_commit="a",
            new_commit="b",
            commit_subjects=["live entry"],
            previous_version="0.2.0",
            new_version="0.3.0",
            config=cfg,
        )

        entries = [
            BackfillEntry(
                version="0.1.0",
                previous_version="initial",
                commit_subjects=["historical"],
                timestamp="2026-01-01T00:00:00+00:00",
            )
        ]
        result = write_backfill_notes(entries=entries, current_version="0.3.0", config=cfg)

        # Errors out, changelog path not written
        assert result.errors
        assert any("already has entries" in e for e in result.errors)
        assert result.changelog_path == ""

        # Live entry is still there, untouched
        changelog = (cfg.company_root / "knowledge" / "technical" / "platform-changelog.md").read_text()
        assert "live entry" in changelog
        assert "historical" not in changelog

    def test_force_overwrites(self, aios_config):
        from agent_os.config import Config

        cfg = Config(company_root=aios_config.company_root, log_also_print=False)

        write_update_notes(
            previous_commit="a",
            new_commit="b",
            commit_subjects=["live entry"],
            previous_version="0.2.0",
            new_version="0.3.0",
            config=cfg,
        )

        entries = [
            BackfillEntry(
                version="0.1.0",
                previous_version="initial",
                commit_subjects=["historical"],
                timestamp="2026-01-01T00:00:00+00:00",
            )
        ]
        result = write_backfill_notes(entries=entries, current_version="0.3.0", force=True, config=cfg)

        assert result.errors == []
        changelog = Path(result.changelog_path).read_text()
        assert "historical" in changelog
        # Live entry is gone — --force means what it says
        assert "live entry" not in changelog
