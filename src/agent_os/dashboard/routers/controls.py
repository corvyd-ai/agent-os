"""Dashboard controls API — schedule, budget, autonomy, backlog, and task management.

These routes provide interactive controls for the dashboard, allowing the
operator to adjust budget caps, toggle schedules, manage autonomy levels,
handle the task backlog, decline queued tasks, and create new tasks.
"""

import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import (
    COMPANY_ROOT,
    TASKS_DIR,
)

router = APIRouter(prefix="/api", tags=["controls"])

# --- Helpers ---


def _get_toml_path() -> Path:
    from agent_os.config import Config

    toml = Config.discover_toml()
    if toml:
        return toml
    raise HTTPException(status_code=500, detail="agent-os.toml not found")


def _read_toml() -> dict:
    import tomllib

    path = _get_toml_path()
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _update_toml(section: str, updates: dict) -> None:
    """Update agent-os.toml via the platform's toml_writer."""
    from agent_os.toml_writer import update_toml

    update_toml(_get_toml_path(), section, updates)


# --- Schedule routes ---


@router.get("/schedule")
async def get_schedule():
    """Current schedule config + next due + budget status."""
    data = _read_toml()
    schedule = data.get("schedule", {})
    budget = data.get("budget", {})

    # Read scheduler state file
    state_file = COMPANY_ROOT / "operations" / "scheduler-state.json"
    state = {}
    if state_file.exists():
        import contextlib

        with contextlib.suppress(json.JSONDecodeError):
            state = json.loads(state_file.read_text())

    return {
        "config": schedule,
        "budget_summary": {
            "daily_cap": budget.get("daily_cap", 100.0),
            "weekly_cap": budget.get("weekly_cap", 500.0),
        },
        "state": state,
    }


class ScheduleToggle(BaseModel):
    type: str | None = None  # None = master toggle, or "cycles", "drives", etc.
    enabled: bool


@router.post("/schedule/toggle")
async def toggle_schedule(body: ScheduleToggle):
    """Enable/disable scheduler or specific schedule types."""
    if body.type is None:
        _update_toml("schedule", {"enabled": body.enabled})
    else:
        section_map = {
            "cycles": "schedule.cycles",
            "standing_orders": "schedule.standing_orders",
            "drives": "schedule.drives",
            "dreams": "schedule.dreams",
        }
        section = section_map.get(body.type)
        if not section:
            raise HTTPException(status_code=400, detail=f"Unknown schedule type: {body.type}")
        _update_toml(section, {"enabled": body.enabled})

    return {"status": "ok", "type": body.type, "enabled": body.enabled}


class ScheduleTrigger(BaseModel):
    agent_id: str
    mode: str  # "cycle", "drives", "standing_orders", "dream"


@router.post("/schedule/trigger")
async def trigger_schedule(body: ScheduleTrigger):
    """Manual trigger for a specific agent + mode."""
    mode_map = {
        "cycle": "cycle",
        "drives": "drives",
        "standing_orders": "standing-orders",
        "dream": "dream",
    }
    cmd = mode_map.get(body.mode)
    if not cmd:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {body.mode}")

    toml_path = _get_toml_path()
    try:
        result = subprocess.run(
            ["agent-os", cmd, body.agent_id, "--config", str(toml_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "output": result.stdout[-2000:] if result.stdout else "",
            "error": result.stderr[-1000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "output": "", "error": "Command timed out after 5 minutes"}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="agent-os CLI not found") from exc


# --- Budget routes ---


@router.get("/budget")
async def get_budget():
    """Full budget status (daily/weekly/monthly, per-agent)."""
    data = _read_toml()
    budget = data.get("budget", {})

    # Read today's costs (must use company timezone — cost files are written in it)
    from ..config import company_today

    today = company_today()
    costs_file = COMPANY_ROOT / "finance" / "costs" / f"{today}.jsonl"
    daily_spent = 0.0
    agent_spent: dict[str, float] = {}

    if costs_file.exists():
        for line in costs_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                cost = entry.get("cost_usd", 0.0)
                agent = entry.get("agent", "unknown")
                daily_spent += cost
                agent_spent[agent] = agent_spent.get(agent, 0.0) + cost
            except json.JSONDecodeError:
                continue

    daily_cap = budget.get("daily_cap", 100.0)
    agent_caps = budget.get("agent_daily_caps", {})

    return {
        "daily": {
            "spent": round(daily_spent, 2),
            "cap": daily_cap,
            "remaining": round(max(0, daily_cap - daily_spent), 2),
            "pct": round(daily_spent / daily_cap * 100, 1) if daily_cap > 0 else 0,
            "tripped": daily_spent >= daily_cap,
        },
        "weekly_cap": budget.get("weekly_cap", 500.0),
        "monthly_cap": budget.get("monthly_cap", 2000.0),
        "per_agent": {
            agent_id: {
                "spent": round(agent_spent.get(agent_id, 0.0), 2),
                "cap": cap,
                "within": agent_spent.get(agent_id, 0.0) < cap,
            }
            for agent_id, cap in agent_caps.items()
        },
        "per_invocation": {
            "task": budget.get("task", 5.0),
            "standing_orders": budget.get("standing_orders", 2.0),
            "drive_consultation": budget.get("drive_consultation", 1.5),
            "dream": budget.get("dream", 1.5),
        },
    }


class BudgetUpdate(BaseModel):
    daily_cap: float | None = None
    weekly_cap: float | None = None
    monthly_cap: float | None = None


@router.patch("/budget")
async def update_budget(body: BudgetUpdate):
    """Update budget caps -> writes to agent-os.toml."""
    updates = {}
    if body.daily_cap is not None:
        updates["daily_cap"] = body.daily_cap
    if body.weekly_cap is not None:
        updates["weekly_cap"] = body.weekly_cap
    if body.monthly_cap is not None:
        updates["monthly_cap"] = body.monthly_cap

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    _update_toml("budget", updates)
    return {"status": "ok", "updated": updates}


# --- Autonomy routes ---


@router.get("/autonomy")
async def get_autonomy():
    """All agent autonomy levels."""
    data = _read_toml()
    autonomy = data.get("autonomy", {})
    default_level = autonomy.get("default_level", "medium")
    agents = autonomy.get("agents", {})

    # Include all dashboard agents
    dashboard = data.get("dashboard", {})
    agent_ids = dashboard.get("agent_ids", list(agents.keys()))

    return {
        "default_level": default_level,
        "agents": {agent_id: agents.get(agent_id, default_level) for agent_id in agent_ids},
    }


class AutonomyUpdate(BaseModel):
    level: str  # "low", "medium", "high"


@router.patch("/autonomy/{agent_id}")
async def update_autonomy(agent_id: str, body: AutonomyUpdate):
    """Update an agent's autonomy level -> writes to agent-os.toml."""
    if body.level not in ("low", "medium", "high"):
        raise HTTPException(status_code=400, detail=f"Invalid level: {body.level}. Must be low, medium, or high.")

    _update_toml("autonomy.agents", {agent_id: body.level})
    return {"status": "ok", "agent_id": agent_id, "level": body.level}


# --- Backlog routes ---


@router.get("/backlog")
async def get_backlog():
    """List all backlog items."""
    backlog_dir = TASKS_DIR / "backlog"
    if not backlog_dir.exists():
        return {"items": []}

    import yaml

    items = []
    for f in sorted(backlog_dir.glob("*.md")):
        text = f.read_text()
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue
        items.append(
            {
                "id": meta.get("id", f.stem),
                "title": meta.get("title", "Untitled"),
                "created_by": meta.get("created_by", "unknown"),
                "assigned_to": meta.get("assigned_to", ""),
                "priority": meta.get("priority", "medium"),
                "created_at": meta.get("created_at", ""),
                "body": parts[2].strip()[:500],
            }
        )

    # Sort by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda x: priority_order.get(x["priority"], 2))

    return {"items": items}


class BacklogAction(BaseModel):
    reason: str | None = None


@router.post("/backlog/{task_id}/promote")
async def promote_backlog(task_id: str):
    """Promote a backlog item to queued."""
    from agent_os.core import promote_task

    result = promote_task(task_id)
    if result:
        return {"status": "ok", "task_id": task_id, "destination": str(result)}
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found in backlog")


@router.post("/backlog/{task_id}/reject")
async def reject_backlog(task_id: str, body: BacklogAction):
    """Reject a backlog item with reason."""
    reason = body.reason or "No reason given"
    from agent_os.core import reject_task

    result = reject_task(task_id, reason)
    if result:
        return {"status": "ok", "task_id": task_id, "reason": reason, "destination": str(result)}
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found in backlog")


# ---- Queued task management ----


@router.post("/queued/{task_id}/decline")
async def decline_queued(task_id: str, body: BacklogAction):
    """Decline a queued task with reason."""
    reason = body.reason or "No reason given"
    from agent_os.core import decline_task

    result = decline_task(task_id, reason)
    if result:
        return {"status": "ok", "task_id": task_id, "reason": reason, "destination": str(result)}
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found in queued")


# ---- Task creation ----


class TaskCreateRequest(BaseModel):
    title: str
    body: str
    assigned_to: str | None = None
    priority: str = "medium"
    destination: str = "backlog"


@router.post("/tasks/create")
async def create_task_endpoint(req: TaskCreateRequest):
    """Create a new task from the dashboard."""
    from agent_os.core import create_task

    if req.priority not in ("low", "medium", "high", "critical"):
        raise HTTPException(status_code=400, detail=f"Invalid priority: {req.priority}")
    if req.destination not in ("backlog", "queued"):
        raise HTTPException(status_code=400, detail=f"Invalid destination: {req.destination}")

    task_id, destination = create_task(
        created_by="human",
        title=req.title,
        body=req.body,
        assigned_to=req.assigned_to,
        priority=req.priority,
        destination=req.destination,
    )
    return {"status": "ok", "task_id": task_id, "destination": destination}
