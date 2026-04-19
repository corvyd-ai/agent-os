"""Shared implementation for the inspection commands:
`timeline`, `messages`, `strategy`.

All read-only; no side effects on the filesystem.
"""

from __future__ import annotations

from datetime import datetime

from .config import Config
from .parsers.frontmatter import parse_frontmatter
from .parsers.jsonl import parse_jsonl_file

# --------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------

_IDLE_ACTIONS = {"cycle_idle", "cycle_skipped"}


def render_timeline(
    config: Config,
    *,
    date: str | None = None,
    agent: str | None = None,
    hide_idle: bool = False,
    limit: int = 200,
) -> str:
    if date is None:
        date = datetime.now(config.tz).date().isoformat()

    entries: list[tuple[str, str, dict]] = []
    if config.logs_dir.exists():
        for agent_dir in sorted(config.logs_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            if agent and agent_dir.name != agent:
                continue
            for entry in parse_jsonl_file(agent_dir / f"{date}.jsonl"):
                action = entry.get("action", "")
                if hide_idle and action in _IDLE_ACTIONS:
                    continue
                entries.append((entry.get("timestamp", ""), agent_dir.name, entry))

    entries.sort(key=lambda e: e[0], reverse=True)
    entries = entries[:limit]

    if not entries:
        return f"No activity on {date}.\n"

    lines = [f"Activity — {date}"]
    for ts, aid, entry in entries:
        action = entry.get("action", "?")
        ref = entry.get("task") or entry.get("msg") or entry.get("thread") or ""
        suffix = f"  {ref}" if ref else ""
        lines.append(f"  {ts[:19]}  {aid:<28} {action}{suffix}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# messages
# --------------------------------------------------------------------------


def _list_messages(directory, *, limit: int = 50) -> list[tuple[str, str]]:
    """Return (id, subject) pairs for messages in `directory`."""
    if not directory.exists():
        return []
    out: list[tuple[str, str]] = []
    for f in sorted(directory.glob("*.md")):
        try:
            meta, _ = parse_frontmatter(f)
        except Exception:
            continue
        out.append((meta.get("id", f.stem), str(meta.get("subject") or meta.get("topic") or f.stem)))
    return out[:limit]


def render_messages(config: Config, *, channel: str, agent: str | None = None) -> str:
    if channel == "broadcast":
        directory = config.broadcast_dir
        title = "Broadcasts"
    elif channel == "threads":
        directory = config.threads_dir
        title = "Threads"
    elif channel == "human":
        directory = config.human_inbox
        title = "Human inbox"
    elif channel == "inbox":
        if not agent:
            return "Usage: agent-os messages inbox <agent-id>\n"
        directory = config.messages_dir / agent / "inbox"
        title = f"{agent} — inbox"
    else:
        return f"Unknown channel: {channel}\n"

    items = _list_messages(directory)
    lines = [f"# {title}", ""]
    if not items:
        lines.append("_(empty)_")
        return "\n".join(lines) + "\n"
    for mid, subject in items:
        lines.append(f"- `{mid}` — {subject}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# strategy
# --------------------------------------------------------------------------


def render_strategy(config: Config, *, topic: str) -> str:
    if topic == "drives":
        if not config.drives_file.exists():
            return "No drives.md yet.\n"
        return config.drives_file.read_text()

    if topic == "decisions":
        if not config.decisions_dir.exists():
            return "No decisions directory.\n"
        lines = ["# Decisions", ""]
        for f in sorted(config.decisions_dir.glob("*.md")):
            try:
                meta, _ = parse_frontmatter(f)
            except Exception:
                continue
            lines.append(f"- `{meta.get('id', f.stem)}` — {meta.get('title', f.stem)} ({meta.get('date', '')})")
        return "\n".join(lines) + "\n"

    if topic == "proposals":
        lines = ["# Proposals", ""]
        for label, directory in (("Active", config.proposals_active), ("Decided", config.proposals_decided)):
            lines.append(f"## {label}")
            if not directory.exists():
                lines.append("_(none)_")
            else:
                found = False
                for f in sorted(directory.glob("*.md")):
                    try:
                        meta, _ = parse_frontmatter(f)
                    except Exception:
                        continue
                    lines.append(f"- `{meta.get('id', f.stem)}` — {meta.get('title', f.stem)}")
                    found = True
                if not found:
                    lines.append("_(none)_")
            lines.append("")
        return "\n".join(lines) + "\n"

    return f"Unknown strategy topic: {topic}\n"
