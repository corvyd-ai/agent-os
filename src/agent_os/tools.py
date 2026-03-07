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
]


def _text_response(text: str, is_error: bool = False) -> dict:
    """Build a standard MCP tool text response."""
    resp = {"content": [{"type": "text", "text": text}]}
    if is_error:
        resp["is_error"] = True
    return resp


def create_aios_tools_server(agent_id: str, *, config: Config | None = None):
    """Create an in-process MCP server with agent-os lifecycle tools.

    Each invocation creates a fresh server that closes over the calling agent's
    ID and config. This is cheap (in-process, no network) and ensures tools
    always know which agent is invoking them.

    Args:
        agent_id: The full agent ID, e.g. "agent-001-maker"
        config: Optional Config override (defaults to global singleton)

    Returns:
        McpSdkServerConfig ready to pass to ClaudeAgentOptions.mcp_servers
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

    return create_sdk_mcp_server(
        name="aios",
        version="1.0.0",
        tools=[
            complete_task_tool,
            fail_task_tool,
            submit_for_review_tool,
            send_message_tool,
            post_broadcast_tool,
            log_action_tool,
        ],
    )
