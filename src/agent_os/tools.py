"""agent-os MCP tools — in-process tools for agent task lifecycle and messaging.

Wraps aios.py functions as native Claude Agent SDK tools so agents can manage
tasks, send messages, and log actions without manually editing files.

Usage:
    from runtime.tools import create_aios_tools_server, AIOS_TOOL_NAMES

    server = create_aios_tools_server(agent_id="agent-001-maker")
    options = ClaudeAgentOptions(
        mcp_servers={"aios": server},
        allowed_tools=existing_tools + AIOS_TOOL_NAMES,
    )
"""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import aios
from .config import Config

# Tool names — used by runner.py to add to allowed_tools
AIOS_TOOL_NAMES = [
    "mcp__aios__complete_task",
    "mcp__aios__fail_task",
    "mcp__aios__submit_for_review",
    "mcp__aios__send_message",
    "mcp__aios__post_broadcast",
    "mcp__aios__log_action",
    "mcp__aios__create_task",
    "mcp__aios__promote_task",
]


def _text_response(text: str, is_error: bool = False) -> dict:
    """Build a standard MCP tool text response."""
    resp = {"content": [{"type": "text", "text": text}]}
    if is_error:
        resp["is_error"] = True
    return resp


def build_aios_tools(
    agent_id: str,
    *,
    config: Config | None = None,
    defer_complete: bool = False,
) -> list:
    """Build the list of ``SdkMcpTool`` instances for a given agent.

    Separated from ``create_aios_tools_server`` so tests can reach the raw
    tool handlers without depending on any extra attributes on the server
    config dict — the SDK serializes that dict to JSON when spinning up a
    subprocess, and ``SdkMcpTool`` is not JSON-serializable, so anything
    extra we stash on the returned dict breaks every real agent invocation.

    See ``create_aios_tools_server`` for parameter semantics.
    """
    cfg = config  # Closed over; None means aios functions use their own default

    @tool(
        name="complete_task",
        description=(
            "Mark a task as complete. Moves the task from in-progress/ to done/ "
            "and updates frontmatter status. Use this instead of manually editing "
            "task files."
        ),
        input_schema={"task_id": str},
    )
    async def complete_task_tool(args):
        task_id = args["task_id"]
        if defer_complete:
            aios.log_action(
                agent_id=agent_id,
                action="complete_task_deferred",
                detail=f"Agent requested completion of {task_id}; runner will finalize after commit/push.",
                config=cfg,
            )
            return _text_response(
                f"Task {task_id} marked complete. "
                "The workspace runner will finalize (commit, push, move to done/) after you return."
            )
        result = aios.complete_task(task_id, outcome="success", config=cfg)
        if result:
            return _text_response(f"Task {task_id} moved to done/ at {result}")
        return _text_response(f"Error: task {task_id} not found in in-progress/", is_error=True)

    @tool(
        name="fail_task",
        description=(
            "Mark a task as failed with a reason. Moves the task from in-progress/ "
            "to failed/ and appends the failure reason."
        ),
        input_schema={"task_id": str, "reason": str},
    )
    async def fail_task_tool(args):
        task_id = args["task_id"]
        reason = args["reason"]
        result = aios.fail_task(task_id, reason, outcome="failure", config=cfg)
        if result:
            return _text_response(f"Task {task_id} moved to failed/ at {result}. Reason: {reason}")
        return _text_response(f"Error: task {task_id} not found in in-progress/", is_error=True)

    @tool(
        name="submit_for_review",
        description=("Submit a task for review. Moves from in-progress/ to in-review/."),
        input_schema={"task_id": str},
    )
    async def submit_for_review_tool(args):
        task_id = args["task_id"]
        result = aios.submit_for_review(task_id, config=cfg)
        if result:
            return _text_response(f"Task {task_id} submitted for review at {result}")
        return _text_response(f"Error: task {task_id} not found in in-progress/", is_error=True)

    @tool(
        name="send_message",
        description=(
            "Send a direct message to another agent. Creates a properly formatted message in the recipient's inbox."
        ),
        input_schema={
            "to": str,
            "subject": str,
            "body": str,
            "urgency": str,
        },
    )
    async def send_message_tool(args):
        to_agent = args["to"]
        subject = args["subject"]
        body = args["body"]
        urgency = args.get("urgency", "normal")
        msg_id = aios.send_message(
            from_agent=agent_id,
            to_agent=to_agent,
            subject=subject,
            body=body,
            urgency=urgency,
            config=cfg,
        )
        return _text_response(f'Message {msg_id} sent to {to_agent}: "{subject}"')

    @tool(
        name="post_broadcast",
        description=("Post a message to the company-wide broadcast channel. Visible to all agents."),
        input_schema={"subject": str, "body": str},
    )
    async def post_broadcast_tool(args):
        subject = args["subject"]
        body = args["body"]
        msg_id = aios.post_broadcast(
            from_id=agent_id,
            subject=subject,
            body=body,
            config=cfg,
        )
        return _text_response(f'Broadcast {msg_id} posted: "{subject}"')

    @tool(
        name="log_action",
        description="Log an action to the agent's activity log.",
        input_schema={"action": str, "detail": str},
    )
    async def log_action_tool(args):
        action = args["action"]
        detail = args["detail"]
        aios.log_action(
            agent_id=agent_id,
            action=action,
            detail=detail,
            config=cfg,
        )
        return _text_response(f"Logged: [{action}] {detail}")

    @tool(
        name="create_task",
        description=(
            "Create a task for any agent. Where the task goes (backlog or queued) "
            "depends on your autonomy level. At 'low' autonomy, this will fail. "
            "At 'medium', the task goes to backlog/ for human approval. "
            "At 'high', the task goes directly to queued/."
        ),
        input_schema={
            "title": str,
            "body": str,
            "assigned_to": str,
            "priority": str,
        },
    )
    async def create_task_tool(args):
        title = args["title"]
        body = args["body"]
        assigned_to = args.get("assigned_to", "")
        priority = args.get("priority", "medium")
        try:
            task_id, destination = aios.create_task(
                created_by=agent_id,
                title=title,
                body=body,
                assigned_to=assigned_to or None,
                priority=priority,
                config=cfg,
            )
            return _text_response(f"Task {task_id} created in {destination}/ — {title}")
        except PermissionError as e:
            return _text_response(str(e), is_error=True)

    @tool(
        name="promote_task",
        description=(
            "Promote a task from backlog/ to queued/. Requires high autonomy. "
            "You can only promote tasks assigned to you, or any task if you are "
            "the Steward (agent-000-steward). Tasks marked promotable: false "
            "cannot be promoted by agents. Rate-limited to 2 per cycle "
            "(Steward: 5) and 5 per day."
        ),
        input_schema={"task_id": str},
    )
    async def promote_task_tool(args):
        task_id = args["task_id"]
        # Gate on high autonomy
        autonomy = aios.get_autonomy_level(agent_id, config=cfg)
        if autonomy != "high":
            return _text_response(
                f"Promotion requires high autonomy. Agent {agent_id} has {autonomy!r} autonomy.",
                is_error=True,
            )
        try:
            result = aios.agent_promote_task(task_id, by_agent_id=agent_id, config=cfg)
            return _text_response(f"Promoted {task_id} to queued/ at {result}")
        except (FileNotFoundError, PermissionError) as e:
            return _text_response(str(e), is_error=True)

    return [
        complete_task_tool,
        fail_task_tool,
        submit_for_review_tool,
        send_message_tool,
        post_broadcast_tool,
        log_action_tool,
        create_task_tool,
        promote_task_tool,
    ]


def create_aios_tools_server(
    agent_id: str,
    *,
    config: Config | None = None,
    defer_complete: bool = False,
):
    """Create an in-process MCP server with agent-os lifecycle tools.

    Each invocation creates a fresh server that closes over the calling agent's
    ID and config. This is cheap (in-process, no network) and ensures tools
    always know which agent is invoking them.

    The returned dict is the canonical ``{type, name, instance}`` shape from
    ``create_sdk_mcp_server`` — do not add extra keys. The SDK serializes
    ``mcp_servers`` to JSON when handing it to the CLI subprocess, and
    ``SdkMcpTool`` (or anything else not in the encoder's supported types)
    will crash every real agent invocation with "Object of type SdkMcpTool is
    not JSON serializable". Tests that need raw tool handlers should call
    ``build_aios_tools`` directly.

    Args:
        agent_id: The full agent ID, e.g. "agent-001-maker"
        config: Optional Config override (defaults to global singleton)
        defer_complete: If True, complete_task acknowledges success but does
            not move the task file. The runner is then the single authority
            that finalizes the task after commit/push succeed. This prevents
            an agent from prematurely marking a task done before downstream
            steps (commit, push) have run — otherwise a commit failure would
            land in the wrong directory and appear as success.

    Returns:
        McpSdkServerConfig ready to pass to ClaudeAgentOptions.mcp_servers
    """
    tools = build_aios_tools(agent_id, config=config, defer_complete=defer_complete)
    return create_sdk_mcp_server(name="aios", version="1.0.0", tools=tools)
