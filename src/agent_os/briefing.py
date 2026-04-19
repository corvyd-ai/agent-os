"""LLM-optimized session bootstrap summary.

The `agent-os briefing` command is the canonical first move for a Claude
Code session attached to an agent-os company: dense, no-color, no-chart
markdown that catches the session up on operational state fast.
"""

from __future__ import annotations

from datetime import datetime

from agent_os import __version__
from agent_os.budget import check_budget
from agent_os.config import Config
from agent_os.metrics import compute_all_health
from agent_os.parsers.frontmatter import parse_frontmatter
from agent_os.parsers.jsonl import parse_jsonl_file
from agent_os.registry import list_agents


def _render_header(cfg: Config) -> str:
    today = datetime.now(cfg.tz).date().isoformat()
    return f"# {cfg.company_name} — briefing ({today})\n\n- agent-os version: `{__version__}`\n- timezone: `{cfg.tz}`\n"


def _render_operational_status(cfg: Config) -> str:
    status = check_budget(config=cfg)
    lines = ["## Operational status\n"]

    sched_bits = []
    sched_bits.append("scheduler **enabled**" if cfg.schedule_enabled else "scheduler **disabled**")
    if cfg.schedule_enabled:
        sched_bits.append("cycles on" if cfg.schedule_cycles_enabled else "cycles off")
    lines.append("- " + ", ".join(sched_bits))

    lines.append(f"- today's spend: **${status.daily_spent:.2f}** / ${status.daily_cap:.2f} ({status.daily_pct:.0f}%)")
    lines.append(f"- weekly: ${status.weekly_spent:.2f} / ${status.weekly_cap:.2f}")
    lines.append(f"- monthly: ${status.monthly_spent:.2f} / ${status.monthly_cap:.2f}")

    if status.circuit_breaker_tripped:
        lines.append("- ⚠️  **circuit breaker tripped** — daily/weekly/monthly cap reached")

    return "\n".join(lines) + "\n"


def _render_roster(cfg: Config, *, scope: str | None = None) -> str:
    agents = list_agents(config=cfg)
    if scope:
        agents = [a for a in agents if a.agent_id == scope]
    if not agents:
        return "## Agents\n\n_No agents registered._\n"
    lines = ["## Agents\n"]
    for ac in agents:
        lines.append(f"- `{ac.agent_id}` — {ac.role or 'unspecified role'}")
    return "\n".join(lines) + "\n"


def _queue_dirs(cfg: Config) -> dict[str, object]:
    # Ordered for display — the order matches the directory-as-status model.
    return {
        "queued": cfg.tasks_queued,
        "in-progress": cfg.tasks_in_progress,
        "in-review": cfg.tasks_in_review,
        "backlog": cfg.tasks_backlog,
        "done": cfg.tasks_done,
        "failed": cfg.tasks_failed,
        "declined": cfg.tasks_declined,
    }


def _frontmatter_summaries(
    directory,
    *,
    label_keys: tuple[str, ...] = ("title", "subject", "topic"),
    limit: int | None = None,
) -> list[tuple[str, str]]:
    """Return (id, label) pairs for frontmatter files in `directory`.

    `label_keys` is searched in order; first hit wins. This supports tasks
    (which use `title`), messages/broadcasts (`subject`), and threads (`topic`).
    """
    if not directory.exists():
        return []
    items: list[tuple[str, str]] = []
    for f in sorted(directory.glob("*.md")):
        try:
            meta, _ = parse_frontmatter(f)
        except Exception:
            continue
        label = f.stem
        for key in label_keys:
            if meta.get(key):
                label = str(meta[key])
                break
        items.append((meta.get("id", f.stem), label))
    if limit is not None:
        items = items[:limit]
    return items


def _task_summaries(directory, limit: int | None = None) -> list[tuple[str, str]]:
    """Return (id, title) pairs — convenience wrapper used for task sections."""
    return _frontmatter_summaries(directory, label_keys=("title",), limit=limit)


def _render_work_queue(cfg: Config) -> str:
    counts = {status: len(list(d.glob("*.md"))) if d.exists() else 0 for status, d in _queue_dirs(cfg).items()}
    lines = ["## Work queue\n"]
    summary = ", ".join(f"**{status}** {n}" for status, n in counts.items() if n > 0) or "_all empty_"
    lines.append(summary)
    lines.append("")

    queued = _task_summaries(cfg.tasks_queued, limit=5)
    if queued:
        lines.append("### Top queued")
        for task_id, title in queued:
            lines.append(f"- `{task_id}` — {title}")
        lines.append("")

    in_progress = _task_summaries(cfg.tasks_in_progress, limit=5)
    if in_progress:
        lines.append("### In progress")
        for task_id, title in in_progress:
            lines.append(f"- `{task_id}` — {title}")
        lines.append("")

    backlog = _task_summaries(cfg.tasks_backlog, limit=5)
    if backlog:
        lines.append("### Backlog — awaiting promotion")
        for task_id, title in backlog:
            lines.append(f"- `{task_id}` — {title}")
        lines.append("")

    return "\n".join(lines)


def _first_paragraph(text: str) -> str:
    """Return the first non-empty paragraph (separated by blank lines) of text."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    para = paragraphs[0]
    # Strip a leading markdown heading so the focus line reads cleanly.
    lines = [ln for ln in para.splitlines() if not ln.startswith("#")]
    return "\n".join(lines).strip()


def _render_strategic_context(cfg: Config) -> str:
    lines = ["## Strategic context\n"]

    focus_file = cfg.strategy_dir / "current-focus.md"
    if focus_file.exists():
        focus = _first_paragraph(focus_file.read_text())
        if focus:
            lines.append(f"**Current focus:** {focus}\n")

    if cfg.drives_file.exists():
        drives_text = cfg.drives_file.read_text()
        # Pull out drive headings (## ...).
        drive_names = [ln[3:].strip() for ln in drives_text.splitlines() if ln.startswith("## ")]
        if drive_names:
            lines.append("**Drives:**")
            for name in drive_names:
                lines.append(f"- {name}")
            lines.append("")

    active_dir = cfg.proposals_active
    if active_dir.exists():
        proposals = _task_summaries(active_dir, limit=10)
        if proposals:
            lines.append("**Active proposals:**")
            for pid, title in proposals:
                lines.append(f"- `{pid}` — {title}")
            lines.append("")

    if len(lines) == 1:
        lines.append("_No strategic context set (no current-focus.md, drives.md, or active proposals)._\n")

    return "\n".join(lines) + "\n"


def _render_messages(cfg: Config) -> str:
    lines = ["## Messages needing attention\n"]

    # Broadcasts — show last 5 by filename sort (ids embed the date).
    broadcasts = (
        _frontmatter_summaries(cfg.broadcast_dir, label_keys=("subject", "title"), limit=5)
        if cfg.broadcast_dir.exists()
        else []
    )
    if broadcasts:
        lines.append("**Broadcasts (recent):**")
        for bid, subject in broadcasts:
            lines.append(f"- `{bid}` — {subject}")
        lines.append("")

    # Human inbox — count + latest subjects.
    inbox_count = 0
    inbox_items: list[tuple[str, str]] = []
    if cfg.human_inbox.exists():
        inbox_items = _frontmatter_summaries(cfg.human_inbox, label_keys=("subject", "title"), limit=5)
        inbox_count = len(list(cfg.human_inbox.glob("*.md")))
    lines.append(f"**Human inbox:** {inbox_count} unread")
    for mid, subject in inbox_items:
        lines.append(f"- `{mid}` — {subject}")
    lines.append("")

    # Active threads.
    active_threads: list[tuple[str, str]] = []
    if cfg.threads_dir.exists():
        for f in sorted(cfg.threads_dir.glob("*.md")):
            try:
                meta, _ = parse_frontmatter(f)
            except Exception:
                continue
            if meta.get("status", "active") != "resolved":
                active_threads.append((meta.get("id", f.stem), meta.get("subject") or meta.get("topic", f.stem)))
    if active_threads:
        lines.append("**Active threads:**")
        for tid, topic in active_threads[:5]:
            lines.append(f"- `{tid}` — {topic}")
        lines.append("")

    if len(lines) == 1:
        lines.append("_No outstanding messages._\n")

    return "\n".join(lines) + "\n"


# Idle/no-op log actions we hide from the recent-activity feed. These are the
# log rows agents emit when they found nothing to do on a cycle — useful for
# uptime analytics, noisy for a briefing.
_IDLE_ACTIONS = {"cycle_idle", "cycle_skipped"}


def _render_recent_activity(cfg: Config, *, limit: int = 15, scope: str | None = None) -> str:
    if not cfg.logs_dir.exists():
        return "## Recent activity\n\n_No activity logs yet._\n"

    today = datetime.now(cfg.tz).date()
    dates = [today.isoformat()]
    if today.day > 1:
        dates.append(today.replace(day=today.day - 1).isoformat())

    entries: list[tuple[str, str, dict]] = []
    for agent_dir in sorted(cfg.logs_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        if scope and agent_dir.name != scope:
            continue
        for date in dates:
            for entry in parse_jsonl_file(agent_dir / f"{date}.jsonl"):
                action = entry.get("action", "")
                if action in _IDLE_ACTIONS:
                    continue
                ts = entry.get("timestamp", "")
                entries.append((ts, agent_dir.name, entry))

    entries.sort(key=lambda e: e[0], reverse=True)
    entries = entries[:limit]

    lines = ["## Recent activity\n"]
    if not entries:
        lines.append("_No activity today._")
        return "\n".join(lines) + "\n"
    for ts, agent_id, entry in entries:
        action = entry.get("action", "?")
        ref = entry.get("task") or entry.get("msg") or entry.get("thread") or ""
        suffix = f" ({ref})" if ref else ""
        lines.append(f"- `{ts[:19]}` **{agent_id}** — {action}{suffix}")

    return "\n".join(lines) + "\n"


def _render_health_snapshot(cfg: Config, *, scope: str | None = None) -> str:
    try:
        health = compute_all_health(days=7, config=cfg)
    except Exception as e:  # pragma: no cover — defensive
        return f"## Health\n\n_Health engine errored: {e}_\n"

    agents = health.get("agents", {})
    if scope:
        agents = {k: v for k, v in agents.items() if k == scope}
        lines = [f"## Health snapshot — {scope} (7-day)\n"]
    else:
        lines = ["## Health snapshot (7-day)\n"]
        lines.append(f"**System composite:** {health['system_composite']}/100")
    if not agents:
        lines.append("_No registered agents yet._")
        return "\n".join(lines) + "\n"

    for agent_id in sorted(agents):
        score = agents[agent_id]["composite_score"]
        lines.append(f"- `{agent_id}` — composite **{score}**/100")
    return "\n".join(lines) + "\n"


def _collect_attention_flags(cfg: Config) -> list[str]:
    flags: list[str] = []

    status = check_budget(config=cfg)
    if status.circuit_breaker_tripped:
        flags.append("🔴 Budget circuit breaker **tripped** — spending has hit or exceeded a cap.")
    elif status.daily_pct >= 80:
        flags.append(f"🟡 Daily budget at **{status.daily_pct:.0f}%** — consider throttling.")

    failed_today = 0
    today = datetime.now(cfg.tz).date().isoformat()
    if cfg.tasks_failed.exists():
        for f in cfg.tasks_failed.glob("*.md"):
            try:
                meta, _ = parse_frontmatter(f)
            except Exception:
                continue
            if today in str(meta.get("created", "")):
                failed_today += 1
    if failed_today:
        flags.append(f"🟡 {failed_today} task(s) failed today — check `agent-os task list --status failed`.")

    backlog_count = len(list(cfg.tasks_backlog.glob("*.md"))) if cfg.tasks_backlog.exists() else 0
    if backlog_count > 0:
        flags.append(f"🟡 {backlog_count} backlog item(s) awaiting human promotion.")

    return flags


def _render_attention_rollup(cfg: Config) -> str:
    flags = _collect_attention_flags(cfg)
    lines = ["## What to pay attention to\n"]
    if not flags:
        lines.append("_No red/yellow flags._")
        return "\n".join(lines) + "\n"
    for flag in flags:
        lines.append(f"- {flag}")
    return "\n".join(lines) + "\n"


def render_briefing(config: Config, *, depth: str = "short", agent: str | None = None) -> str:
    """Render an LLM-optimized markdown briefing of current company state.

    `depth="short"` keeps the output compact; `"full"` retains the same structure
    but expands sections (e.g. more queued tasks, more timeline entries).
    `agent` scopes the briefing to a single agent when supplied — the roster,
    recent activity, and health snapshot are filtered to that agent.
    """
    sections = [
        _render_header(config),
        _render_operational_status(config),
        _render_attention_rollup(config),
        _render_roster(config, scope=agent),
        _render_work_queue(config),
        _render_strategic_context(config),
        _render_messages(config),
        _render_recent_activity(config, limit=30 if depth == "full" else 12, scope=agent),
        _render_health_snapshot(config, scope=agent),
    ]
    return "\n".join(sections) + "\n"
