"""Tests for agent_os.core — filesystem operations, task lifecycle, messaging."""

from datetime import UTC, datetime, timedelta

from agent_os.core import (
    _find_next_task,
    _parse_frontmatter,
    _write_frontmatter,
    append_journal,
    archive_broadcast,
    check_cadence,
    claim_task,
    complete_task,
    decline_task,
    fail_task,
    log_action,
    log_cost,
    mark_cadence,
    mark_processed,
    next_id,
    post_broadcast,
    read_broadcast,
    read_drives,
    read_inbox,
    read_journal,
    read_soul,
    read_values,
    read_working_memory,
    send_message,
    submit_for_review,
)

# ── Frontmatter parsing ──────────────────────────────────────────────


def test_parse_frontmatter_valid(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("---\ntitle: Hello\npriority: high\n---\n\nBody text here.")
    meta, body = _parse_frontmatter(p)
    assert meta["title"] == "Hello"
    assert meta["priority"] == "high"
    assert body == "Body text here."


def test_parse_frontmatter_no_frontmatter(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("Just plain text, no frontmatter.")
    meta, body = _parse_frontmatter(p)
    assert meta == {}
    assert "Just plain text" in body


def test_parse_frontmatter_empty_yaml(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("---\n---\n\nBody only.")
    meta, body = _parse_frontmatter(p)
    assert meta == {}
    assert body == "Body only."


def test_write_and_parse_roundtrip(tmp_path):
    p = tmp_path / "roundtrip.md"
    original_meta = {"id": "task-2026-0101-001", "title": "Test", "priority": "high"}
    original_body = "Description of the task.\n\nMore details."
    _write_frontmatter(p, original_meta, original_body)
    meta, body = _parse_frontmatter(p)
    assert meta["id"] == "task-2026-0101-001"
    assert meta["title"] == "Test"
    assert "Description of the task." in body
    assert "More details." in body


# ── Task lifecycle ────────────────────────────────────────────────────


def _create_task(queued_dir, task_id, assigned_to=None, priority="medium", depends_on=None):
    """Helper: write a task file in queued/."""
    meta = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": "queued",
        "priority": priority,
    }
    if assigned_to:
        meta["assigned_to"] = assigned_to
    if depends_on:
        meta["depends_on"] = depends_on
    body = f"Work for {task_id}."
    path = queued_dir / f"{task_id}.md"
    _write_frontmatter(path, meta, body)
    return path


def test_claim_task_by_id(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    result = claim_task("agent-001-maker", "task-2026-0101-001")
    assert result is not None
    assert result.parent == aios_fs["TASKS_IN_PROGRESS"]
    meta, _ = _parse_frontmatter(result)
    assert meta["status"] == "in-progress"


def test_claim_task_auto_find(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-003-operator")
    result = claim_task("agent-003-operator")
    assert result is not None
    assert "task-2026-0101-001" in result.name


def test_claim_task_empty_queue(aios_fs):
    result = claim_task("agent-001-maker")
    assert result is None


def test_find_next_task_priority_ordering(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker", priority="low")
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-002", assigned_to="agent-001-maker", priority="critical")
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-003", assigned_to="agent-001-maker", priority="high")

    result = _find_next_task("agent-001-maker")
    assert result is not None
    assert "task-2026-0101-002" in result.name  # critical wins


def test_find_next_task_dependency_blocked(aios_fs):
    _create_task(
        aios_fs["TASKS_QUEUED"], "task-2026-0101-002", assigned_to="agent-001-maker", depends_on=["task-2026-0101-001"]
    )
    # Dependency not in done/ → blocked
    result = _find_next_task("agent-001-maker")
    assert result is None


def test_find_next_task_dependency_satisfied(aios_fs):
    # Put dependency in done/
    _create_task(aios_fs["TASKS_DONE"], "task-2026-0101-001")
    _create_task(
        aios_fs["TASKS_QUEUED"], "task-2026-0101-002", assigned_to="agent-001-maker", depends_on=["task-2026-0101-001"]
    )
    result = _find_next_task("agent-001-maker")
    assert result is not None
    assert "task-2026-0101-002" in result.name


def test_find_next_task_skips_other_agent(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-005-grower")
    result = _find_next_task("agent-001-maker")
    assert result is None


def test_find_next_task_short_form_id_match(aios_fs):
    """Short-form assigned_to (agent-001) should match full ID (agent-001-maker)."""
    task_path = aios_fs["TASKS_QUEUED"] / "task-2026-0101-001.md"
    meta = {
        "id": "task-2026-0101-001",
        "title": "Test",
        "status": "queued",
        "priority": "medium",
        "assigned_to": "agent-001",  # short form
    }
    _write_frontmatter(task_path, meta, "Work.")
    result = _find_next_task("agent-001-maker")
    assert result is not None


def test_complete_task(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    result = complete_task("task-2026-0101-001")
    assert result is not None
    assert result.parent == aios_fs["TASKS_DONE"]
    meta, _ = _parse_frontmatter(result)
    assert meta["status"] == "done"


def test_complete_task_outcome_default(aios_fs):
    """complete_task writes outcome: success by default."""
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    result = complete_task("task-2026-0101-001")
    assert result is not None
    meta, _ = _parse_frontmatter(result)
    assert meta["outcome"] == "success"


def test_complete_task_outcome_partial(aios_fs):
    """complete_task can write a custom outcome value."""
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    result = complete_task("task-2026-0101-001", outcome="partial")
    assert result is not None
    meta, _ = _parse_frontmatter(result)
    assert meta["outcome"] == "partial"


def test_fail_task(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    result = fail_task("task-2026-0101-001", "Build failed: missing dependency")
    assert result is not None
    assert result.parent == aios_fs["TASKS_FAILED"]
    content = result.read_text()
    assert "Build failed: missing dependency" in content


def test_fail_task_outcome_default(aios_fs):
    """fail_task writes outcome: failure by default."""
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    result = fail_task("task-2026-0101-001", "Test failure")
    assert result is not None
    meta, _ = _parse_frontmatter(result)
    assert meta["outcome"] == "failure"


def test_fail_task_outcome_cancelled(aios_fs):
    """fail_task can write outcome: cancelled."""
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    result = fail_task("task-2026-0101-001", "No longer needed", outcome="cancelled")
    assert result is not None
    meta, _ = _parse_frontmatter(result)
    assert meta["outcome"] == "cancelled"


def test_fail_task_backstop_from_done(aios_fs):
    """Regression: if a task was already moved to done/ (e.g. by a premature
    MCP complete_task call) and a downstream step then fails, fail_task must
    still relocate the task to failed/ and rewrite the outcome.

    Without this backstop, a commit-phase failure in workspace mode would
    silently leave the task in done/ with outcome: success, producing an
    observability lie — dashboards, watchdogs, and the agent's next cycle
    would all see "success" even though work was lost.
    """
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    complete_task("task-2026-0101-001")  # simulates premature MCP complete_task

    result = fail_task("task-2026-0101-001", "git commit failed: Author identity unknown")

    assert result is not None
    assert result.parent == aios_fs["TASKS_FAILED"]
    meta, _ = _parse_frontmatter(result)
    assert meta["status"] == "failed"
    assert meta["outcome"] == "failure"
    assert "git commit failed" in result.read_text()
    # No stray copy left in done/
    assert not list(aios_fs["TASKS_DONE"].glob("task-2026-0101-001*"))


def test_fail_task_backstop_from_in_review(aios_fs):
    """fail_task should also relocate from in-review/ if a downstream
    failure occurs after submit_for_review."""
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-002", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-002")
    submit_for_review("task-2026-0101-002")

    result = fail_task("task-2026-0101-002", "downstream failure")

    assert result is not None
    assert result.parent == aios_fs["TASKS_FAILED"]
    assert not list(aios_fs["TASKS_IN_REVIEW"].glob("task-2026-0101-002*"))


def test_fail_task_prefers_in_progress_over_done(aios_fs):
    """If a task file somehow exists in both in-progress/ and done/ (this
    shouldn't happen, but file systems are messy), fail the in-progress
    copy — that's the one the runner is actively working on."""
    _create_task(aios_fs["TASKS_IN_PROGRESS"], "task-2026-0101-003")
    # Stray copy in done/ (pathological state)
    _create_task(aios_fs["TASKS_DONE"], "task-2026-0101-003")

    result = fail_task("task-2026-0101-003", "failed")

    assert result is not None
    assert result.parent == aios_fs["TASKS_FAILED"]
    # in-progress/ copy was the one moved
    assert not list(aios_fs["TASKS_IN_PROGRESS"].glob("task-2026-0101-003*"))
    # done/ copy still there (untouched — fail_task only moves one)
    assert list(aios_fs["TASKS_DONE"].glob("task-2026-0101-003*"))


def test_submit_for_review(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001", assigned_to="agent-001-maker")
    claim_task("agent-001-maker", "task-2026-0101-001")
    result = submit_for_review("task-2026-0101-001")
    assert result is not None
    assert result.parent == aios_fs["TASKS_IN_REVIEW"]


def test_decline_task_with_notification(aios_fs):
    """Declining a human task should notify the creating agent."""
    task_path = aios_fs["TASKS_QUEUED"] / "task-2026-0101-001.md"
    meta = {
        "id": "task-2026-0101-001",
        "title": "Buy domain",
        "status": "queued",
        "assigned_to": "human",
        "created_by": "agent-006-strategist",
    }
    _write_frontmatter(task_path, meta, "Purchase example.dev domain.")
    result = decline_task("task-2026-0101-001", "Too expensive")
    assert result is not None
    assert result.parent == aios_fs["TASKS_DECLINED"]

    # Check notification was sent to creator
    creator_inbox = aios_fs["MESSAGES_DIR"] / "agent-006-strategist" / "inbox"
    msgs = list(creator_inbox.glob("*.md"))
    assert len(msgs) == 1
    content = msgs[0].read_text()
    assert "Declined" in content
    assert "Too expensive" in content


# ── ID generation ─────────────────────────────────────────────────────


def test_next_id_first(aios_fs):
    result = next_id("task-2026-0101", aios_fs["TASKS_QUEUED"])
    assert result == "task-2026-0101-001"


def test_next_id_increments(aios_fs):
    _create_task(aios_fs["TASKS_QUEUED"], "task-2026-0101-001")
    result = next_id("task-2026-0101", aios_fs["TASKS_QUEUED"])
    assert result == "task-2026-0101-002"


def test_next_id_scans_all_task_dirs(aios_fs):
    """next_id for tasks should scan across all lifecycle dirs."""
    _create_task(aios_fs["TASKS_DONE"], "task-2026-0101-003")
    result = next_id("task-2026-0101", aios_fs["TASKS_QUEUED"])
    assert result == "task-2026-0101-004"


# ── Messaging ─────────────────────────────────────────────────────────


def test_send_message_creates_inbox_and_outbox(aios_fs):
    msg_id = send_message(
        from_agent="agent-000-steward",
        to_agent="agent-001-maker",
        subject="Build request",
        body="Please build the widget.",
    )
    assert msg_id.startswith("msg-")

    inbox_path = aios_fs["MESSAGES_DIR"] / "agent-001-maker" / "inbox" / f"{msg_id}.md"
    outbox_path = aios_fs["MESSAGES_DIR"] / "agent-000-steward" / "outbox" / f"{msg_id}.md"
    assert inbox_path.exists()
    assert outbox_path.exists()


def test_send_message_correct_frontmatter(aios_fs):
    msg_id = send_message(
        from_agent="agent-000-steward",
        to_agent="agent-001-maker",
        subject="Test",
        body="Body.",
        urgency="high",
    )
    inbox_path = aios_fs["MESSAGES_DIR"] / "agent-001-maker" / "inbox" / f"{msg_id}.md"
    meta, body = _parse_frontmatter(inbox_path)
    assert meta["from"] == "agent-000-steward"
    assert meta["to"] == "agent-001-maker"
    assert meta["urgency"] == "high"
    assert body == "Body."


def test_read_inbox_empty(aios_fs):
    result = read_inbox("agent-001-maker")
    assert result == []


def test_read_inbox_sorted(aios_fs):
    send_message("agent-000-steward", "agent-001-maker", "First", "Body1")
    send_message("agent-005-grower", "agent-001-maker", "Second", "Body2")
    msgs = read_inbox("agent-001-maker")
    assert len(msgs) == 2
    # Should be sorted by filename (chronological)
    assert msgs[0][0]["subject"] == "First"
    assert msgs[1][0]["subject"] == "Second"


def test_mark_processed(aios_fs):
    msg_id = send_message("agent-000-steward", "agent-001-maker", "Test", "Body")
    inbox_path = aios_fs["MESSAGES_DIR"] / "agent-001-maker" / "inbox" / f"{msg_id}.md"
    mark_processed(inbox_path)
    assert not inbox_path.exists()
    processed_path = inbox_path.parent / "processed" / f"{msg_id}.md"
    assert processed_path.exists()


def test_send_message_to_human_emits_notification(aios_fs):
    send_message(
        from_agent="agent-001-maker",
        to_agent="human",
        subject="Need your input",
        body="Blocked on a decision.",
        urgency="high",
    )

    notif_dir = aios_fs["COMPANY_ROOT"] / "operations" / "notifications"
    assert notif_dir.exists()
    files = list(notif_dir.glob("*-message_for_human.md"))
    assert len(files) == 1

    content = files[0].read_text()
    assert "message_for_human" in content
    assert "Message from agent-001-maker" in content
    assert "Need your input" in content
    assert "Blocked on a decision." in content
    assert 'agent_id: "agent-001-maker"' in content


def test_send_message_to_human_maps_urgency_to_severity(aios_fs):
    send_message("agent-001-maker", "human", "Urgent", "The server is on fire.", urgency="critical")

    notif_dir = aios_fs["COMPANY_ROOT"] / "operations" / "notifications"
    files = list(notif_dir.glob("*-message_for_human.md"))
    assert len(files) == 1
    assert "severity: critical" in files[0].read_text()


def test_send_message_to_human_response_requested_in_title(aios_fs):
    send_message(
        "agent-001-maker",
        "human",
        "Approve deploy?",
        "Ready to ship.",
        urgency="high",
        requires_response=True,
    )

    notif_dir = aios_fs["COMPANY_ROOT"] / "operations" / "notifications"
    files = list(notif_dir.glob("*-message_for_human.md"))
    assert len(files) == 1
    assert "[response requested]" in files[0].read_text()


def test_send_message_between_agents_does_not_notify(aios_fs):
    send_message("agent-000-steward", "agent-001-maker", "Hey", "Body", urgency="critical")

    notif_dir = aios_fs["COMPANY_ROOT"] / "operations" / "notifications"
    assert not notif_dir.exists() or not list(notif_dir.glob("*-message_for_human.md"))


# ── Journals ──────────────────────────────────────────────────────────


def test_append_journal_creates_file(aios_fs):
    result = append_journal("agent-001-maker", "First entry.")
    assert result.exists()
    content = result.read_text()
    assert "First entry." in content


def test_append_journal_appends(aios_fs):
    append_journal("agent-001-maker", "Entry one.")
    append_journal("agent-001-maker", "Entry two.")
    journal_file = aios_fs["LOGS_DIR"] / "agent-001-maker" / "journal.md"
    content = journal_file.read_text()
    assert "Entry one." in content
    assert "Entry two." in content


def test_read_journal_max_entries(aios_fs):
    for i in range(15):
        append_journal("agent-001-maker", f"Entry {i}.")
    result = read_journal("agent-001-maker", max_entries=3)
    # Should contain the last 3 entries
    assert "Entry 14." in result
    assert "Entry 13." in result
    assert "Entry 12." in result
    # Should NOT contain the first ones
    assert "Entry 0." not in result


def test_read_journal_missing_file(aios_fs):
    result = read_journal("agent-nonexistent")
    assert result == ""


# ── Cadence tracking ──────────────────────────────────────────────────


def test_check_cadence_never_run(aios_fs):
    assert check_cadence("agent-001-maker", "weekly-reflection", 168) is True


def test_check_cadence_recent(aios_fs):
    mark_cadence("agent-001-maker", "weekly-reflection")
    assert check_cadence("agent-001-maker", "weekly-reflection", 168) is False


def test_check_cadence_old(aios_fs):
    cadence_file = aios_fs["LOGS_DIR"] / "agent-001-maker" / ".cadence-weekly-reflection"
    cadence_file.parent.mkdir(parents=True, exist_ok=True)
    old_time = datetime.now(UTC) - timedelta(hours=200)
    cadence_file.write_text(old_time.isoformat())
    assert check_cadence("agent-001-maker", "weekly-reflection", 168) is True


# ── File reads (values, soul, working memory, drives) ─────────────────


def test_read_values_with_content(aios_fs):
    aios_fs["VALUES_FILE"].write_text("# Values\n\nBe excellent.")
    result = read_values()
    assert "Be excellent." in result


def test_read_values_missing_file(aios_fs):
    result = read_values()
    assert result == ""


def test_read_soul_with_content(aios_fs):
    soul_dir = aios_fs["AGENTS_STATE_DIR"] / "agent-001-maker"
    soul_dir.mkdir(parents=True, exist_ok=True)
    (soul_dir / "soul.md").write_text("I find beauty in clean code.")
    result = read_soul("agent-001-maker")
    assert "clean code" in result


def test_read_soul_missing(aios_fs):
    result = read_soul("agent-nonexistent")
    assert result == ""


def test_read_working_memory(aios_fs):
    wm_dir = aios_fs["AGENTS_STATE_DIR"] / "agent-001-maker"
    wm_dir.mkdir(parents=True, exist_ok=True)
    (wm_dir / "working-memory.md").write_text("Currently thinking about X.")
    result = read_working_memory("agent-001-maker")
    assert "thinking about X" in result


def test_read_working_memory_missing(aios_fs):
    result = read_working_memory("agent-nonexistent")
    assert result == ""


def test_read_drives_with_content(aios_fs):
    aios_fs["DRIVES_FILE"].write_text("# Drives\n\nShip products.")
    result = read_drives()
    assert "Ship products." in result


def test_read_drives_missing(aios_fs):
    result = read_drives()
    assert result == ""


# ── Broadcasts ────────────────────────────────────────────────────────


def test_post_broadcast(aios_fs):
    msg_id = post_broadcast("agent-000-steward", "Hello", "Company update.")
    assert msg_id.startswith("broadcast-")
    broadcast_file = aios_fs["BROADCAST_DIR"] / f"{msg_id}.md"
    assert broadcast_file.exists()


def test_read_broadcast_sorted(aios_fs):
    post_broadcast("agent-000-steward", "First", "Body1.")
    post_broadcast("agent-005-grower", "Second", "Body2.")
    msgs = read_broadcast()
    assert len(msgs) == 2
    assert msgs[0][0]["subject"] == "First"
    assert msgs[1][0]["subject"] == "Second"


def test_archive_broadcast(aios_fs):
    msg_id = post_broadcast("agent-000-steward", "Test", "Body.")
    msg_path = aios_fs["BROADCAST_DIR"] / f"{msg_id}.md"
    archive_broadcast(msg_path)
    assert not msg_path.exists()
    archived = aios_fs["BROADCAST_DIR"] / "archived" / f"{msg_id}.md"
    assert archived.exists()


# ── Logging ───────────────────────────────────────────────────────────


def test_log_action_creates_file(aios_fs):
    log_action("agent-001-maker", "test_action", "Did something", {"key": "val"})
    import json

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    log_file = aios_fs["LOGS_DIR"] / "agent-001-maker" / f"{today}.jsonl"
    assert log_file.exists()
    entry = json.loads(log_file.read_text().strip())
    assert entry["action"] == "test_action"
    assert entry["detail"] == "Did something"


def test_log_cost(aios_fs):
    log_cost("agent-001-maker", "task-001", 1.23, 5000, "claude-opus-4-6", 10)
    import json

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    cost_file = aios_fs["COSTS_DIR"] / f"{today}.jsonl"
    assert cost_file.exists()
    entry = json.loads(cost_file.read_text().strip())
    assert entry["cost_usd"] == 1.23
    assert entry["agent"] == "agent-001-maker"
