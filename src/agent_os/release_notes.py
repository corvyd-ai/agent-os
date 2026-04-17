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
