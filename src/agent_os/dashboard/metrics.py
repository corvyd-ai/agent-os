"""Health metrics computation — read-only analysis of the agent-os filesystem.

Computes five metric categories:
  A. Autonomy Score (0-100)
  B. Task Effectiveness
  C. Cycle Efficiency
  D. Governance Health
  E. System Health

All computation is read-only against the agent-os filesystem.
Graceful handling of missing data — new installations won't have history.
"""

from datetime import UTC, datetime, timedelta

from .config import (
    AGENT_ALIASES,
    AGENT_IDS,
    COSTS_DIR,
    DECISIONS_DIR,
    LOGS_DIR,
    PROPOSALS_ACTIVE,
    PROPOSALS_DECIDED,
    TASK_STATUS_DIRS,
    THREADS_DIR,
    company_date,
)
from .parsers.frontmatter import parse_frontmatter
from .parsers.jsonl import parse_jsonl_file


def _normalize_agent(agent_id: str) -> str:
    return AGENT_ALIASES.get(agent_id, agent_id)


def _collect_logs(agent_id: str, days: int) -> list[dict]:
    """Collect activity log entries for an agent over N days."""
    today = company_date()
    entries = []
    for i in range(days):
        date = today - timedelta(days=i)
        entries.extend(parse_jsonl_file(LOGS_DIR / agent_id / f"{date}.jsonl"))
    return entries


def _collect_costs(days: int) -> list[dict]:
    """Collect cost entries over N days."""
    today = company_date()
    entries = []
    for i in range(days):
        date = today - timedelta(days=i)
        entries.extend(parse_jsonl_file(COSTS_DIR / f"{date}.jsonl"))
    return entries


def _collect_tasks(statuses: list[str] | None = None) -> list[dict]:
    """Collect task metadata from specified status directories."""
    if statuses is None:
        statuses = list(TASK_STATUS_DIRS.keys())
    tasks = []
    for status in statuses:
        directory = TASK_STATUS_DIRS.get(status)
        if not directory or not directory.exists():
            continue
        for f in directory.glob("*.md"):
            try:
                meta, _body = parse_frontmatter(f)
                meta["_status"] = status
                meta["_file"] = f.name
                tasks.append(meta)
            except Exception:
                continue
    return tasks


def _collect_threads() -> list[dict]:
    """Collect thread metadata."""
    threads = []
    if not THREADS_DIR.exists():
        return threads
    for f in THREADS_DIR.glob("*.md"):
        try:
            meta, body = parse_frontmatter(f)
            # Extract response timestamps from body sections
            responses = []
            for line in body.splitlines():
                if line.startswith("## ") and " — " in line:
                    parts = line.split(" — ", 1)
                    if len(parts) == 2:
                        agent = parts[0].lstrip("# ").strip()
                        ts = parts[1].strip()
                        responses.append({"agent": agent, "timestamp": ts})
            meta["_responses"] = responses
            threads.append(meta)
        except Exception:
            continue
    return threads


def _collect_proposals() -> list[dict]:
    """Collect all proposals (active + decided)."""
    proposals = []
    for directory, status in [(PROPOSALS_ACTIVE, "active"), (PROPOSALS_DECIDED, "decided")]:
        if not directory.exists():
            continue
        for f in directory.glob("*.md"):
            try:
                meta, _ = parse_frontmatter(f)
                meta["_dir_status"] = status
                proposals.append(meta)
            except Exception:
                continue
    return proposals


def _collect_decisions() -> list[dict]:
    """Collect all decisions."""
    decisions = []
    if not DECISIONS_DIR.exists():
        return decisions
    for f in DECISIONS_DIR.glob("*.md"):
        try:
            meta, _ = parse_frontmatter(f)
            decisions.append(meta)
        except Exception:
            continue
    return decisions


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division that returns default when denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _parse_ts(value) -> datetime | None:
    """Best-effort parse of various timestamp formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    s = str(value).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# A. Autonomy Score
# ---------------------------------------------------------------------------


def compute_autonomy(agent_id: str, days: int) -> dict:
    """Compute autonomy metrics for a single agent.

    - Productive cycle ratio: productive_cycles / total_cycles
    - Escalation rate: human_tasks_created / total_tasks_completed
    - Self-initiated work ratio: drive_tasks / total_tasks
    - Decision autonomy: agent_decisions / (agent + human decisions)
    """
    logs = _collect_logs(agent_id, days)

    # Productive cycle ratio
    cycle_actions = [e for e in logs if e.get("action", "").startswith("cycle_") or e.get("action") == "sdk_complete"]
    idle_cycles = [e for e in logs if e.get("action") == "cycle_idle"]
    total_cycles = max(len(cycle_actions), 1)
    productive_cycles = total_cycles - len(idle_cycles)
    productive_ratio = _safe_ratio(productive_cycles, total_cycles, 0.5)

    # Task-based metrics (system-wide for the period, filtered to agent)
    all_tasks = _collect_tasks()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    # Tasks completed by this agent in the period
    done_by_agent = [
        t
        for t in all_tasks
        if t.get("_status") == "done"
        and _normalize_agent(t.get("assigned_to", "")) == agent_id
        and _is_within_period(t, cutoff)
    ]

    # Human tasks created by this agent
    human_tasks = [
        t
        for t in all_tasks
        if t.get("assigned_to") == "human"
        and _normalize_agent(t.get("created_by", "")) == agent_id
        and _is_within_period(t, cutoff)
    ]

    # Self-initiated: created_by == assigned_to (drive-initiated work)
    self_initiated = [t for t in done_by_agent if _normalize_agent(t.get("created_by", "")) == agent_id]

    total_completed = len(done_by_agent)
    escalation_rate = _safe_ratio(len(human_tasks), max(total_completed, 1))
    self_initiated_ratio = _safe_ratio(len(self_initiated), max(total_completed, 1))

    # Decision autonomy (system-wide metric, not per-agent)
    decisions = _collect_decisions()
    period_decisions = [d for d in decisions if _is_decision_within_period(d, cutoff)]
    agent_decisions = [d for d in period_decisions if d.get("decided_by") != "human"]
    human_decisions = [d for d in period_decisions if d.get("decided_by") == "human"]
    decision_autonomy = _safe_ratio(
        len(agent_decisions),
        len(agent_decisions) + len(human_decisions),
        0.5,  # No decisions = neutral
    )

    # Composite: weighted average → 0-100
    # Higher productive ratio = more autonomous
    # Lower escalation = more autonomous
    # Higher self-initiated = more autonomous
    # Higher decision autonomy = more autonomous
    composite = productive_ratio * 30 + (1 - escalation_rate) * 25 + self_initiated_ratio * 20 + decision_autonomy * 25
    score = _clamp(composite * 100 / 100)  # already 0-100 weighted sum

    return {
        "score": round(score, 1),
        "productive_cycle_ratio": round(productive_ratio, 3),
        "escalation_rate": round(escalation_rate, 3),
        "self_initiated_ratio": round(self_initiated_ratio, 3),
        "decision_autonomy": round(decision_autonomy, 3),
        "productive_cycles": productive_cycles,
        "total_cycles": total_cycles - len(idle_cycles) + len(idle_cycles),  # just total
        "tasks_completed": total_completed,
        "human_tasks_created": len(human_tasks),
        "self_initiated_tasks": len(self_initiated),
    }


def _is_within_period(task: dict, cutoff: datetime) -> bool:
    """Check if a task's created date falls within the period."""
    created = _parse_ts(task.get("created"))
    if created is None:
        return True  # Include tasks with no parseable date
    return created >= cutoff


def _is_decision_within_period(decision: dict, cutoff: datetime) -> bool:
    """Check if a decision falls within the period."""
    dt = _parse_ts(decision.get("date"))
    if dt is None:
        return True
    return dt >= cutoff


# ---------------------------------------------------------------------------
# B. Task Effectiveness
# ---------------------------------------------------------------------------


def compute_effectiveness(agent_id: str, days: int) -> dict:
    """Compute task effectiveness metrics for a single agent.

    - Completion rate: done / (done + failed)
    - Task velocity: mean completion time (estimated from task age)
    - Throughput: completed tasks per 24h
    """
    all_tasks = _collect_tasks()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    agent_tasks = [
        t for t in all_tasks if _normalize_agent(t.get("assigned_to", "")) == agent_id and _is_within_period(t, cutoff)
    ]

    done = [t for t in agent_tasks if t.get("_status") == "done"]
    failed = [t for t in agent_tasks if t.get("_status") == "failed"]

    completion_rate = _safe_ratio(len(done), len(done) + len(failed), 1.0)
    throughput = _safe_ratio(len(done), days) if days > 0 else 0

    # Velocity: estimate from cost log durations for this agent's tasks
    costs = _collect_costs(days)
    agent_task_costs = [
        c
        for c in costs
        if _normalize_agent(c.get("agent", "")) == agent_id and (c.get("task") or "").startswith("task-")
    ]
    durations = [c.get("duration_ms", 0) for c in agent_task_costs if c.get("duration_ms", 0) > 0]
    mean_duration_ms = _safe_ratio(sum(durations), len(durations)) if durations else 0

    # Score: weighted composite
    # High completion rate is good (40%)
    # Higher throughput relative to capacity (30%)
    # Lower mean duration is more efficient (30%)
    throughput_score = min(throughput / 3.0, 1.0)  # 3 tasks/day = perfect
    # Duration score: faster is better, cap at 10min ideal
    duration_score = 1.0 - min(mean_duration_ms / (30 * 60 * 1000), 1.0) if mean_duration_ms > 0 else 0.5

    score = _clamp(completion_rate * 40 + throughput_score * 30 + duration_score * 30)

    return {
        "score": round(score, 1),
        "completion_rate": round(completion_rate, 3),
        "throughput_per_day": round(throughput, 2),
        "mean_duration_ms": round(mean_duration_ms),
        "tasks_done": len(done),
        "tasks_failed": len(failed),
        "tasks_total": len(agent_tasks),
    }


# ---------------------------------------------------------------------------
# C. Cycle Efficiency
# ---------------------------------------------------------------------------


def compute_efficiency(agent_id: str, days: int) -> dict:
    """Compute cost efficiency metrics for a single agent.

    - Cost per completed task
    - Cost per turn trend
    - Idle cost ratio
    - Budget utilization per mode
    """
    costs = _collect_costs(days)
    agent_costs = [c for c in costs if _normalize_agent(c.get("agent", "")) == agent_id]

    total_cost = sum(c.get("cost_usd", 0) for c in agent_costs)
    total_turns = sum(c.get("num_turns", 0) for c in agent_costs)

    # Task costs vs other costs
    task_costs = [c for c in agent_costs if (c.get("task") or "").startswith("task-")]
    drive_costs = [c for c in agent_costs if (c.get("task") or "") == "drive-consultation"]
    standing_costs = [c for c in agent_costs if (c.get("task") or "").startswith("standing-order")]

    task_total_cost = sum(c.get("cost_usd", 0) for c in task_costs)

    # Done tasks for this agent in the period
    all_tasks = _collect_tasks(["done"])
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    done_by_agent = [
        t for t in all_tasks if _normalize_agent(t.get("assigned_to", "")) == agent_id and _is_within_period(t, cutoff)
    ]

    cost_per_task = _safe_ratio(task_total_cost, len(done_by_agent))
    cost_per_turn = _safe_ratio(total_cost, total_turns)

    # Idle cost ratio: drive/standing costs when no productive work happened
    # Approximate: non-task cost / total cost
    non_task_cost = total_cost - task_total_cost
    idle_cost_ratio = _safe_ratio(non_task_cost, total_cost) if total_cost > 0 else 0

    # Score: lower cost per task is better, lower idle ratio is better
    # Normalize cost_per_task: $2 = perfect, $10 = poor
    cost_score = 1.0 - min(cost_per_task / 10.0, 1.0) if cost_per_task > 0 else 0.5
    idle_score = 1.0 - idle_cost_ratio
    turn_efficiency = 1.0 - min(cost_per_turn / 0.15, 1.0) if cost_per_turn > 0 else 0.5

    score = _clamp(cost_score * 35 + idle_score * 35 + turn_efficiency * 30)

    return {
        "score": round(score, 1),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_task_usd": round(cost_per_task, 4),
        "cost_per_turn_usd": round(cost_per_turn, 4),
        "idle_cost_ratio": round(idle_cost_ratio, 3),
        "total_turns": total_turns,
        "task_invocations": len(task_costs),
        "drive_invocations": len(drive_costs),
        "standing_order_invocations": len(standing_costs),
    }


# ---------------------------------------------------------------------------
# D. Governance Health
# ---------------------------------------------------------------------------


def compute_governance(days: int) -> dict:
    """Compute governance metrics (system-wide, not per-agent).

    - Proposal throughput: decided / active per period
    - Decision latency (mean days from proposal to decision)
    - Thread resolution rate
    - Thread response time
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    # Proposals
    proposals = _collect_proposals()
    active_proposals = [p for p in proposals if p.get("_dir_status") == "active"]
    decided_proposals = [p for p in proposals if p.get("_dir_status") == "decided"]

    # Filter to period
    period_decided = [p for p in decided_proposals if _is_decision_within_period(p, cutoff)]
    proposal_throughput = _safe_ratio(len(period_decided), max(len(active_proposals) + len(period_decided), 1))

    # Decision latency: we can't easily compute proposal→decision time without
    # matching proposals to decisions. Approximate from decision dates.
    decisions = _collect_decisions()
    period_decisions = [d for d in decisions if _is_decision_within_period(d, cutoff)]

    # Threads
    threads = _collect_threads()
    resolved_threads = [t for t in threads if t.get("status") == "resolved"]
    active_threads = [t for t in threads if t.get("status") == "active"]
    total_threads = len(threads)
    resolution_rate = _safe_ratio(len(resolved_threads), total_threads, 1.0)

    # Thread response time: time between first and second message
    response_times_hours = []
    for t in threads:
        responses = t.get("_responses", [])
        if len(responses) >= 2:
            t1 = _parse_ts(responses[0].get("timestamp"))
            t2 = _parse_ts(responses[1].get("timestamp"))
            if t1 and t2:
                delta = (t2 - t1).total_seconds() / 3600
                if 0 < delta < 168:  # Sanity: < 1 week
                    response_times_hours.append(delta)

    mean_response_hours = (
        _safe_ratio(sum(response_times_hours), len(response_times_hours)) if response_times_hours else 0
    )

    # Score
    throughput_score = proposal_throughput  # 0-1
    resolution_score = resolution_rate  # 0-1
    # Response time: < 2h = perfect, > 24h = poor
    response_score = 1.0 - min(mean_response_hours / 24.0, 1.0) if mean_response_hours > 0 else 0.5
    decision_score = min(len(period_decisions) / max(days / 7, 1), 1.0)  # ~1 decision per week = good

    score = _clamp(
        (throughput_score * 25 + resolution_score * 30 + response_score * 25 + decision_score * 20) * 100 / 100
    )

    return {
        "score": round(score, 1),
        "active_proposals": len(active_proposals),
        "decided_proposals_in_period": len(period_decided),
        "proposal_throughput": round(proposal_throughput, 3),
        "decisions_in_period": len(period_decisions),
        "total_threads": total_threads,
        "resolved_threads": len(resolved_threads),
        "active_threads": len(active_threads),
        "resolution_rate": round(resolution_rate, 3),
        "mean_response_hours": round(mean_response_hours, 1),
    }


# ---------------------------------------------------------------------------
# E. System Health
# ---------------------------------------------------------------------------


def compute_system_health(agent_id: str, days: int) -> dict:
    """Compute system health metrics for a single agent.

    - Error rate from activity logs
    - Standing order completion rate
    - Schedule adherence (invocations per day)
    - Mean recovery time after errors
    """
    logs = _collect_logs(agent_id, days)

    # Error rate
    error_actions = {"error", "task_failed", "sdk_error", "cycle_error"}
    errors = [e for e in logs if e.get("action", "") in error_actions]
    total_entries = len(logs) if logs else 1
    error_rate = _safe_ratio(len(errors), total_entries)

    # Cost-log based standing orders
    costs = _collect_costs(days)
    agent_standing_costs = [
        c
        for c in costs
        if _normalize_agent(c.get("agent", "")) == agent_id and (c.get("task") or "").startswith("standing-order")
    ]

    # Schedule adherence: how many days had at least one activity?
    active_days = set()
    for entry in logs:
        ts = _parse_ts(entry.get("timestamp"))
        if ts:
            active_days.add(ts.date())

    schedule_adherence = _safe_ratio(len(active_days), days, 1.0)

    # Mean recovery time: time between error and next successful action
    recovery_times_minutes = []
    sorted_logs = sorted(logs, key=lambda e: e.get("timestamp", ""))
    last_error_ts = None
    for entry in sorted_logs:
        action = entry.get("action", "")
        if action in error_actions:
            last_error_ts = _parse_ts(entry.get("timestamp"))
        elif last_error_ts and action not in error_actions and action != "cycle_idle":
            recovery_ts = _parse_ts(entry.get("timestamp"))
            if recovery_ts:
                delta = (recovery_ts - last_error_ts).total_seconds() / 60
                if 0 < delta < 1440:  # Sanity: < 24h
                    recovery_times_minutes.append(delta)
                last_error_ts = None

    mean_recovery_min = (
        _safe_ratio(sum(recovery_times_minutes), len(recovery_times_minutes)) if recovery_times_minutes else 0
    )

    # Score
    error_score = 1.0 - min(error_rate * 10, 1.0)  # 10% errors = 0 score
    adherence_score = schedule_adherence
    # Recovery: < 15min = perfect, > 2h = poor
    recovery_score = 1.0 - min(mean_recovery_min / 120, 1.0) if mean_recovery_min > 0 else 1.0  # No errors = perfect

    score = _clamp((error_score * 40 + adherence_score * 35 + recovery_score * 25) * 100 / 100)

    return {
        "score": round(score, 1),
        "error_rate": round(error_rate, 4),
        "error_count": len(errors),
        "total_log_entries": total_entries,
        "schedule_adherence": round(schedule_adherence, 3),
        "active_days": len(active_days),
        "expected_days": days,
        "standing_order_invocations": len(agent_standing_costs),
        "mean_recovery_minutes": round(mean_recovery_min, 1),
    }


# ---------------------------------------------------------------------------
# Aggregation — per-agent and system-wide
# ---------------------------------------------------------------------------


def compute_agent_health(agent_id: str, days: int) -> dict:
    """Compute all health metrics for a single agent."""
    autonomy = compute_autonomy(agent_id, days)
    effectiveness = compute_effectiveness(agent_id, days)
    efficiency = compute_efficiency(agent_id, days)
    system = compute_system_health(agent_id, days)

    # Composite score: weighted average of all agent-level scores
    composite = (
        autonomy["score"] * 0.25 + effectiveness["score"] * 0.30 + efficiency["score"] * 0.20 + system["score"] * 0.25
    )

    return {
        "agent_id": agent_id,
        "days": days,
        "composite_score": round(composite, 1),
        "autonomy": autonomy,
        "effectiveness": effectiveness,
        "efficiency": efficiency,
        "system_health": system,
    }


def compute_all_health(days: int = 7) -> dict:
    """Compute health metrics for all agents + system-wide governance.

    Returns per-agent scores and a system composite.
    """
    agents = {}
    for agent_id in AGENT_IDS:
        agents[agent_id] = compute_agent_health(agent_id, days)

    governance = compute_governance(days)

    # System-wide composite
    agent_scores = [a["composite_score"] for a in agents.values()]
    mean_agent_score = _safe_ratio(sum(agent_scores), len(agent_scores)) if agent_scores else 0

    system_composite = round(
        mean_agent_score * 0.70 + governance["score"] * 0.30,
        1,
    )

    return {
        "system_composite": system_composite,
        "governance": governance,
        "agents": agents,
        "period_days": days,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def compute_health_with_trends() -> dict:
    """Compute health for both 7-day and 30-day windows, providing trend data."""
    health_7d = compute_all_health(days=7)
    health_30d = compute_all_health(days=30)

    # Compute trend direction for each agent
    agent_trends = {}
    for agent_id in AGENT_IDS:
        score_7d = health_7d["agents"][agent_id]["composite_score"]
        score_30d = health_30d["agents"][agent_id]["composite_score"]
        delta = round(score_7d - score_30d, 1)
        if delta > 2:
            direction = "improving"
        elif delta < -2:
            direction = "declining"
        else:
            direction = "stable"
        agent_trends[agent_id] = {
            "score_7d": score_7d,
            "score_30d": score_30d,
            "delta": delta,
            "direction": direction,
        }

    # System trend
    sys_delta = round(health_7d["system_composite"] - health_30d["system_composite"], 1)
    if sys_delta > 2:
        sys_direction = "improving"
    elif sys_delta < -2:
        sys_direction = "declining"
    else:
        sys_direction = "stable"

    return {
        "current": health_7d,
        "baseline": health_30d,
        "trends": {
            "system": {
                "score_7d": health_7d["system_composite"],
                "score_30d": health_30d["system_composite"],
                "delta": sys_delta,
                "direction": sys_direction,
            },
            "agents": agent_trends,
        },
        "computed_at": datetime.now(UTC).isoformat(),
    }
