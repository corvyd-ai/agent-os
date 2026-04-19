"""agent-os release notes — announce platform updates to running agents.

When ``agent-os update`` pulls new platform code, agents would otherwise
get the new behavior silently — running new code with old mental models.
This module closes that loop by writing both:

1. **A broadcast** — transient "something changed" nudge that lands in
   every agent's Layer 2 context on their next cycle.
2. **A persistent reference doc** — ``knowledge/technical/agent-os-platform.md``,
   regenerated from a bundled template each update. Always reflects the
   CURRENT state of the platform. Agents read this when they need to
   check "how does X actually work here?".
3. **An append-only changelog** — ``knowledge/technical/platform-changelog.md``,
   accumulating a history of updates (commit subjects, dates, versions).

The split matters: broadcasts get archived after 7 days, so they're not
a durable source of truth. New agents joining the company never see old
broadcasts at all. The reference doc and changelog stay accessible
forever.

Usage:
    from agent_os.release_notes import write_update_notes

    result = write_update_notes(
        previous_commit="5023224",
        new_commit="7bbb321",
        commit_subjects=["feat: add observability", "fix: respect runtime user"],
        previous_version="0.2.3",
        new_version="0.3.0",
        config=cfg,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config, get_config


@dataclass
class UpdateNotesResult:
    """What write_update_notes produced."""

    broadcast_id: str = ""
    reference_doc_path: str = ""
    changelog_path: str = ""
    errors: list[str] = field(default_factory=list)


def _load_reference_template() -> str:
    """Read the bundled reference-doc Jinja template from the package."""
    template_path = Path(__file__).parent / "resources" / "agent-os-platform.md.jinja2"
    return template_path.read_text()


def _render_reference_doc(version: str, generated_at: str) -> str:
    """Render the reference doc template.

    Uses a minimal string substitution rather than a full Jinja env to
    avoid coupling this module to a specific Jinja setup — the template
    only uses ``{{ version }}`` and ``{{ generated_at }}`` placeholders.
    If we need conditionals or loops later, swap in jinja2.
    """
    template = _load_reference_template()
    return template.replace("{{ version }}", version).replace("{{ generated_at }}", generated_at)


def _append_changelog_entry(
    changelog_path: Path,
    *,
    previous_version: str,
    new_version: str,
    commit_subjects: list[str],
    timestamp: str,
) -> None:
    """Append a new entry to the platform changelog (creates file if needed).

    Entries are prepended so the most recent update is at the top (after
    the header). The changelog is append-only — old entries are never
    modified or removed.
    """
    header = "# agent-os Platform Changelog\n\nThis file records every platform update that touched this company. Most recent first.\n\n"

    entry_lines = [
        f"## v{new_version} — {timestamp}",
        "",
        f"Updated from v{previous_version} to v{new_version}.",
        "",
    ]
    if commit_subjects:
        entry_lines.append("**Changes:**")
        for subj in commit_subjects:
            entry_lines.append(f"- {subj}")
        entry_lines.append("")
    entry_lines.append("---")
    entry_lines.append("")

    new_entry = "\n".join(entry_lines)

    if changelog_path.exists():
        existing = changelog_path.read_text()
        # Split into header and body, insert new entry after the header
        if existing.startswith("# agent-os Platform Changelog"):
            # Find end of header (first "---" separator or blank line after header paragraph)
            marker = "Most recent first.\n\n"
            idx = existing.find(marker)
            if idx >= 0:
                head_end = idx + len(marker)
                body = existing[head_end:]
                changelog_path.write_text(header + new_entry + body)
                return
        # Fallback: prepend whole new file with existing as body
        changelog_path.write_text(header + new_entry + existing)
    else:
        changelog_path.write_text(header + new_entry)


def _build_broadcast_body(
    *,
    previous_version: str,
    new_version: str,
    commit_subjects: list[str],
    reference_doc_relpath: str,
    changelog_relpath: str,
) -> str:
    """Compose the markdown body for the update broadcast."""
    lines = [
        f"agent-os was updated from **v{previous_version}** to **v{new_version}**.",
        "",
    ]
    if commit_subjects:
        lines.append("**What changed:**")
        for subj in commit_subjects[:10]:  # cap to keep the broadcast skimmable
            lines.append(f"- {subj}")
        if len(commit_subjects) > 10:
            lines.append(f"- …and {len(commit_subjects) - 10} more (see changelog)")
        lines.append("")

    lines.extend(
        [
            "**Your mental model of the platform may be out of date.** Before your next code task, skim:",
            "",
            f"- `{reference_doc_relpath}` — how the platform works right now (regenerated every update)",
            f"- `{changelog_relpath}` — history of platform updates",
            "",
            "If those docs contradict older runbooks or knowledge files in this company, trust these. They are the current source of truth.",
        ]
    )
    return "\n".join(lines)


def write_update_notes(
    *,
    previous_commit: str,
    new_commit: str,
    commit_subjects: list[str],
    previous_version: str,
    new_version: str,
    config: Config | None = None,
) -> UpdateNotesResult:
    """Write platform-update notes to the company filesystem.

    Called by ``agent-os update`` after a successful pull + reinstall.
    Writes three artifacts:

    1. Persistent reference doc at ``knowledge/technical/agent-os-platform.md``
       (regenerated from the bundled template — always reflects current platform).
    2. Append-only changelog at ``knowledge/technical/platform-changelog.md``.
    3. A broadcast at ``agents/messages/broadcast/`` announcing the update.

    Any single artifact failing is captured in ``result.errors`` but does
    not prevent the others from being written — the broadcast is the most
    time-sensitive and should not be blocked by an I/O error on the
    changelog file.
    """
    cfg = config or get_config()
    result = UpdateNotesResult()
    now = datetime.now(cfg.tz)
    timestamp = now.isoformat()

    tech_dir = cfg.company_root / "knowledge" / "technical"
    try:
        tech_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        result.errors.append(f"mkdir knowledge/technical: {e}")
        return result

    # 1. Regenerate the reference doc
    try:
        reference_path = tech_dir / "agent-os-platform.md"
        reference_path.write_text(_render_reference_doc(version=new_version, generated_at=timestamp))
        result.reference_doc_path = str(reference_path)
    except OSError as e:
        result.errors.append(f"write reference doc: {e}")

    # 2. Append to the changelog
    try:
        changelog_path = tech_dir / "platform-changelog.md"
        _append_changelog_entry(
            changelog_path,
            previous_version=previous_version,
            new_version=new_version,
            commit_subjects=commit_subjects,
            timestamp=timestamp,
        )
        result.changelog_path = str(changelog_path)
    except OSError as e:
        result.errors.append(f"append changelog: {e}")

    # 3. Post the broadcast
    try:
        from . import core as aios

        reference_rel = "knowledge/technical/agent-os-platform.md"
        changelog_rel = "knowledge/technical/platform-changelog.md"
        body = _build_broadcast_body(
            previous_version=previous_version,
            new_version=new_version,
            commit_subjects=commit_subjects,
            reference_doc_relpath=reference_rel,
            changelog_relpath=changelog_rel,
        )
        subject = f"Platform update: agent-os v{new_version}"
        result.broadcast_id = aios.post_broadcast("system", subject, body, config=cfg)
    except Exception as e:
        result.errors.append(f"post broadcast: {e}")

    return result


# --- Backfill: one-time bootstrap from git history ---


@dataclass
class BackfillEntry:
    """A single historical changelog entry reconstructed from git.

    Used by ``write_backfill_notes`` to seed the changelog file with
    history that occurred before the release-notes mechanism existed.
    """

    version: str  # target version (tag name, or "unreleased" for post-latest-tag)
    previous_version: str
    commit_subjects: list[str]
    timestamp: str  # when the target version was tagged, or "backfilled" for the trailing group


def build_backfill_entries(
    *,
    commits: list[tuple[str, str, str]],
    tags: list[tuple[str, str, str]],
    current_version: str,
) -> list[BackfillEntry]:
    """Group commits into one entry per tag boundary (+ trailing unreleased).

    Arguments:
        commits: list of (sha, subject, iso_date) in chronological order
                 (oldest → newest). The order matters for grouping.
        tags:    list of (tag_name, sha, iso_date), also chronological.
        current_version: version string for commits after the latest tag.

    Returns entries in reverse chronological order (newest first), which
    is the order the changelog should read top-to-bottom.

    When there are no tags, produces a single "all history" entry. This
    is honest — we aren't inventing version boundaries that didn't exist.
    """
    if not commits:
        return []

    # Fast path: no tags. One entry containing everything.
    if not tags:
        subjects = [subj for _sha, subj, _ts in commits]
        return [
            BackfillEntry(
                version=current_version,
                previous_version="initial",
                commit_subjects=list(reversed(subjects)),  # newest first within the entry
                timestamp=commits[-1][2],
            )
        ]

    # Map sha → tag name for quick boundary lookup
    tag_shas = {sha: tag_name for tag_name, sha, _ts in tags}

    entries: list[BackfillEntry] = []
    bucket_subjects: list[str] = []
    previous_tag_name = "initial"

    # Walk commits in chronological order. When we hit a commit that
    # corresponds to a tagged release, close the current bucket and
    # start a new one.
    for sha, subject, ts in commits:
        bucket_subjects.append(subject)
        if sha in tag_shas:
            tag_name = tag_shas[sha]
            entries.append(
                BackfillEntry(
                    version=_strip_v(tag_name),
                    previous_version=previous_tag_name,
                    commit_subjects=list(reversed(bucket_subjects)),
                    timestamp=ts,
                )
            )
            bucket_subjects = []
            previous_tag_name = _strip_v(tag_name)

    # Any commits after the last tag belong to the current version
    if bucket_subjects:
        entries.append(
            BackfillEntry(
                version=current_version,
                previous_version=previous_tag_name,
                commit_subjects=list(reversed(bucket_subjects)),
                timestamp=commits[-1][2],
            )
        )

    # Return newest first
    entries.reverse()
    return entries


def _strip_v(tag: str) -> str:
    """Normalize 'v0.3.0' → '0.3.0'. Tags without the v prefix pass through."""
    return tag[1:] if tag.startswith("v") and len(tag) > 1 and tag[1].isdigit() else tag


def _build_backfill_broadcast_body(
    *,
    entries: list[BackfillEntry],
    current_version: str,
    reference_doc_relpath: str,
    changelog_relpath: str,
) -> str:
    """Compose the 'we enabled release notes, here's a catch-up' broadcast."""
    total_commits = sum(len(e.commit_subjects) for e in entries)
    lines = [
        "**Release notes are now enabled on this deployment.**",
        "",
        f"The platform changelog has been backfilled with **{len(entries)} version(s)** covering **{total_commits} commit(s)** of history up to the current **v{current_version}**. Future updates will be announced here as they happen.",
        "",
        "**If you haven't checked in a while, your understanding of how agent-os works may be out of date.** Before your next code task, skim:",
        "",
        f"- `{reference_doc_relpath}` — how the platform works right now (regenerated every update)",
        f"- `{changelog_relpath}` — full version history",
        "",
        "If those docs contradict older runbooks or knowledge files in this company, trust these. They are the current source of truth.",
    ]
    return "\n".join(lines)


@dataclass
class BackfillResult:
    """Outcome of write_backfill_notes."""

    broadcast_id: str = ""
    reference_doc_path: str = ""
    changelog_path: str = ""
    entries_written: int = 0
    errors: list[str] = field(default_factory=list)


def write_backfill_notes(
    *,
    entries: list[BackfillEntry],
    current_version: str,
    force: bool = False,
    post_broadcast: bool = True,
    config: Config | None = None,
) -> BackfillResult:
    """One-time bootstrap: seed the changelog + reference doc from git history.

    - Writes ``knowledge/technical/agent-os-platform.md`` (regenerated).
    - Writes ``knowledge/technical/platform-changelog.md`` with each entry,
      newest first. Errors if the file already has non-header content,
      unless ``force=True``.
    - Posts a single "release notes enabled, here's a catch-up" broadcast,
      unless ``post_broadcast=False``.

    Unlike ``write_update_notes``, this is not time-sensitive — it's a
    reference dump, and it says so explicitly in the broadcast.
    """
    cfg = config or get_config()
    result = BackfillResult()
    now = datetime.now(cfg.tz).isoformat()

    tech_dir = cfg.company_root / "knowledge" / "technical"
    try:
        tech_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        result.errors.append(f"mkdir knowledge/technical: {e}")
        return result

    # 1. Regenerate the reference doc (safe to overwrite; it's stateless)
    try:
        ref_path = tech_dir / "agent-os-platform.md"
        ref_path.write_text(_render_reference_doc(version=current_version, generated_at=now))
        result.reference_doc_path = str(ref_path)
    except OSError as e:
        result.errors.append(f"write reference doc: {e}")

    # 2. Safety check: don't blow away a live changelog unless forced
    changelog_path = tech_dir / "platform-changelog.md"
    if changelog_path.exists() and not force:
        existing = changelog_path.read_text()
        if _changelog_has_entries(existing):
            result.errors.append(
                f"changelog already has entries at {changelog_path} — pass force=True to overwrite "
                "(backfill is a one-time bootstrap, not an ongoing operation)"
            )
            return result

    # 3. Write changelog from scratch. We write entries oldest-first using
    # the existing _append helper (which prepends), so the final order is
    # newest-on-top. Start from a clean file.
    try:
        if changelog_path.exists():
            changelog_path.unlink()
        # Walk entries from oldest to newest so each _append_changelog_entry
        # prepends above the previous one.
        for entry in reversed(entries):
            _append_changelog_entry(
                changelog_path,
                previous_version=entry.previous_version,
                new_version=entry.version,
                commit_subjects=entry.commit_subjects,
                timestamp=entry.timestamp,
            )
        # Tag the file as backfilled so it's obvious this wasn't generated
        # live — agents reading it shouldn't infer real-time broadcasts fired.
        if entries:
            header = changelog_path.read_text()
            note = (
                "> **Note:** The entries below this line were **backfilled** from git "
                "history on " + now + ". They describe platform changes that shipped "
                "before the release-notes mechanism existed — no real-time broadcast "
                "was sent at the time. Entries added above this line (from future "
                "`agent-os update` runs) are generated live.\n\n"
            )
            # Insert the note after the existing header paragraph
            marker = "Most recent first.\n\n"
            idx = header.find(marker)
            if idx >= 0:
                head_end = idx + len(marker)
                header = header[:head_end] + note + header[head_end:]
                changelog_path.write_text(header)

        result.changelog_path = str(changelog_path)
        result.entries_written = len(entries)
    except OSError as e:
        result.errors.append(f"write changelog: {e}")

    # 4. Post the catch-up broadcast
    if post_broadcast and entries:
        try:
            from . import core as aios

            body = _build_backfill_broadcast_body(
                entries=entries,
                current_version=current_version,
                reference_doc_relpath="knowledge/technical/agent-os-platform.md",
                changelog_relpath="knowledge/technical/platform-changelog.md",
            )
            subject = f"Release notes enabled — backfilled to v{current_version}"
            result.broadcast_id = aios.post_broadcast("system", subject, body, config=cfg)
        except Exception as e:
            result.errors.append(f"post broadcast: {e}")

    return result


def _changelog_has_entries(text: str) -> bool:
    """True if the changelog has any '## v...' entry lines beyond the header."""
    return any(line.startswith("## v") or line.startswith("## Backfilled") for line in text.splitlines())
