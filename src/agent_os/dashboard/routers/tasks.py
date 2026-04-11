"""Task API routes."""

from fastapi import APIRouter, Query

from ..config import TASK_STATUS_DIRS
from ..parsers.frontmatter import parse_frontmatter

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(
    status: str | None = Query(None, description="Filter by status"),
    agent: str | None = Query(None, description="Filter by assigned agent"),
    limit: int = Query(50, description="Max results"),
):
    """List tasks, optionally filtered by status and/or agent."""
    tasks = []

    dirs_to_scan = {}
    if status and status in TASK_STATUS_DIRS:
        dirs_to_scan = {status: TASK_STATUS_DIRS[status]}
    else:
        dirs_to_scan = TASK_STATUS_DIRS

    for status_name, directory in dirs_to_scan.items():
        if not directory.exists():
            continue
        for f in sorted(directory.glob("*.md"), reverse=True):
            meta, body = parse_frontmatter(f)
            if agent and meta.get("assigned_to") != agent:
                continue
            tasks.append(
                {
                    **meta,
                    "body": body,
                    "status": status_name,
                    "_file": f.name,
                }
            )

    # Sort by ID descending (most recent first), limit results
    tasks.sort(key=lambda t: t.get("id", ""), reverse=True)
    return tasks[:limit]


@router.get("/summary")
async def task_summary():
    """Get task counts by status."""
    counts = {}
    for status_name, directory in TASK_STATUS_DIRS.items():
        if directory.exists():
            counts[status_name] = len(list(directory.glob("*.md")))
        else:
            counts[status_name] = 0
    return counts


@router.get("/{task_id}")
async def get_task(task_id: str):
    """Get a single task by ID, searching all status directories."""
    for status_name, directory in TASK_STATUS_DIRS.items():
        if not directory.exists():
            continue
        matches = list(directory.glob(f"{task_id}*"))
        if matches:
            meta, body = parse_frontmatter(matches[0])
            return {**meta, "body": body, "status": status_name, "_file": matches[0].name}
    return {"error": "not found"}
