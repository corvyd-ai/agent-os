"""`agent-os task list|show` — read-only task inspection."""

from __future__ import annotations

import json

from .config import Config
from .formatting import _json_default
from .parsers.frontmatter import parse_frontmatter


def _status_dirs(cfg: Config) -> dict[str, object]:
    return {
        "queued": cfg.tasks_queued,
        "in-progress": cfg.tasks_in_progress,
        "in-review": cfg.tasks_in_review,
        "backlog": cfg.tasks_backlog,
        "done": cfg.tasks_done,
        "failed": cfg.tasks_failed,
        "declined": cfg.tasks_declined,
    }


def _collect_tasks(cfg: Config, *, status: str | None = None) -> list[dict]:
    rows: list[dict] = []
    dirs = _status_dirs(cfg)
    targets = [status] if status else list(dirs.keys())
    for s in targets:
        d = dirs.get(s)
        if not d or not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                meta, body = parse_frontmatter(f)
            except Exception:
                continue
            rows.append(
                {
                    "id": meta.get("id", f.stem),
                    "title": meta.get("title", f.stem),
                    "status": s,
                    "assigned_to": meta.get("assigned_to", ""),
                    "priority": meta.get("priority", "medium"),
                    "created": str(meta.get("created", "")),
                    "_path": str(f),
                    "_body": body,
                    "_meta": meta,
                }
            )
    return rows


def render_task_list(
    config: Config,
    *,
    status: str | None = None,
    agent: str | None = None,
) -> str:
    rows = _collect_tasks(config, status=status)
    if agent:
        rows = [r for r in rows if r["assigned_to"] == agent]
    if not rows:
        return "No tasks matched.\n"
    lines = [f"{'id':<28} {'status':<12} {'assigned_to':<28} {'priority':<10} title", "-" * 100]
    for r in rows:
        lines.append(f"{r['id']:<28} {r['status']:<12} {r['assigned_to']:<28} {r['priority']:<10} {r['title']}")
    return "\n".join(lines) + "\n"


def render_task_list_json(
    config: Config,
    *,
    status: str | None = None,
    agent: str | None = None,
) -> str:
    rows = _collect_tasks(config, status=status)
    if agent:
        rows = [r for r in rows if r["assigned_to"] == agent]
    slim = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return json.dumps(slim, indent=2, default=_json_default)


def render_task_show(config: Config, task_id: str) -> str:
    for row in _collect_tasks(config):
        if row["id"] == task_id or row["_path"].endswith(f"/{task_id}.md"):
            lines = [
                f"# {row['id']} — {row['title']}",
                "",
                f"- **status:** {row['status']}",
                f"- **assigned_to:** {row['assigned_to']}",
                f"- **priority:** {row['priority']}",
                f"- **created:** {row['created']}",
                "",
                "## Body",
                "",
                row["_body"].strip() if row["_body"] else "_(no body)_",
                "",
            ]
            return "\n".join(lines) + "\n"
    return f"Task '{task_id}' not found. Try `agent-os task list` to see all tasks.\n"
