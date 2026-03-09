"""Conversation API routes — real-time chat with agent-os agents."""

import asyncio
import fcntl
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import AGENT_ALIASES, AGENT_IDS, CONVERSATIONS_DIR

router = APIRouter(prefix="/api", tags=["conversation"])


def _resolve_agent_id(agent_id: str) -> str | None:
    """Resolve a short or full agent ID to the canonical form."""
    # Direct match
    if agent_id in AGENT_IDS:
        return agent_id
    # Alias match
    if agent_id in AGENT_ALIASES:
        return AGENT_ALIASES[agent_id]
    # Short form: "agent-000" -> "agent-000-steward"
    for full_id in AGENT_IDS:
        if full_id.startswith(agent_id):
            return full_id
    return None


def _conversations_dir() -> Path:
    """Return the conversations directory, creating it if needed."""
    d = CONVERSATIONS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_conversation(conv_id: str) -> dict | None:
    """Load a conversation from disk."""
    path = _conversations_dir() / f"{conv_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_conversation(conv: dict) -> None:
    """Save a conversation to disk."""
    path = _conversations_dir() / f"{conv['id']}.json"
    path.write_text(json.dumps(conv, indent=2))


def _new_conversation(agent_id: str) -> dict:
    """Create a new conversation record."""
    conv_id = f"conv-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    return {
        "id": conv_id,
        "agent_id": agent_id,
        "created": now,
        "updated": now,
        "turns": [],
        "total_cost_usd": 0.0,
    }


class SendRequest(BaseModel):
    agent_id: str
    message: str
    conversation_id: str | None = None


def _get_config_path() -> str | None:
    """Find the agent-os.toml config path."""
    from agent_os.config import Config

    toml = Config.discover_toml()
    return str(toml) if toml else None


@router.post("/conversation/send")
async def send_message(req: SendRequest):
    """Send a message to an agent and stream the response as SSE."""
    agent_id = _resolve_agent_id(req.agent_id)
    if not agent_id:
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': f'Unknown agent: {req.agent_id}'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # Load or create conversation
    conv = None
    if req.conversation_id:
        conv = _load_conversation(req.conversation_id)
    if conv is None:
        conv = _new_conversation(agent_id)

    # Build conversation JSON for the runner
    runner_input = json.dumps({
        "conversation_id": conv["id"],
        "agent_id": agent_id,
        "turns": conv["turns"],
        "message": req.message,
    })

    lock_path = f"/tmp/agent-os-cycle-{agent_id}.lock"

    async def event_stream():
        lock_fd = None
        proc = None
        assistant_text_parts = []
        cost_usd = 0.0

        try:
            # Try to acquire the agent lock (non-blocking)
            lock_fd = open(lock_path, "w")  # noqa: SIM115 — fd must stay open for flock
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Agent is currently busy (running a cron cycle). Try again in a few minutes.'})}\n\n"
                lock_fd.close()
                return

            # Build the command — use agent-os CLI
            cmd = ["agent-os", "cycle", agent_id, "--interactive"]
            config_path = _get_config_path()
            if config_path:
                cmd.extend(["--config", config_path])

            # Spawn the runner subprocess
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Send conversation JSON to stdin and close it
            proc.stdin.write(runner_input.encode())
            await proc.stdin.drain()
            proc.stdin.close()

            # Read stdout line by line and forward as SSE
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    continue  # Skip non-JSON output (e.g. SDK debug messages)

                # Accumulate assistant text for persistence
                if event.get("type") == "text":
                    assistant_text_parts.append(event.get("text", ""))
                elif event.get("type") == "complete":
                    cost_usd = event.get("cost_usd", 0.0)

                yield f"data: {json.dumps(event)}\n\n"

            # Wait for process to finish
            await proc.wait()

            # Read any stderr for debugging (don't send to client)
            stderr_data = await proc.stderr.read()
            if stderr_data and proc.returncode != 0:
                stderr_text = stderr_data.decode()[:500]
                yield f"data: {json.dumps({'type': 'error', 'message': f'Runner error: {stderr_text}'})}\n\n"

            # Save conversation with the new turn
            assistant_text = "".join(assistant_text_parts)
            if assistant_text.strip():
                conv["turns"].append({"role": "human", "content": req.message})
                conv["turns"].append({"role": "assistant", "content": assistant_text})
                conv["total_cost_usd"] = round(conv["total_cost_usd"] + cost_usd, 4)
                conv["updated"] = datetime.now(UTC).isoformat()
                _save_conversation(conv)

                yield f"data: {json.dumps({'type': 'conversation_saved', 'conversation_id': conv['id']})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            if proc and proc.returncode is None:
                proc.kill()
            if lock_fd:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()
                except Exception:
                    pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/conversation/status/{agent_id}")
async def agent_status(agent_id: str):
    """Check if an agent is available for conversation."""
    resolved = _resolve_agent_id(agent_id)
    if not resolved:
        return {"available": False, "error": f"Unknown agent: {agent_id}"}

    lock_path = f"/tmp/agent-os-cycle-{resolved}.lock"
    try:
        fd = open(lock_path, "w")  # noqa: SIM115 — fd must stay open for flock
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
        return {"available": True, "agent_id": resolved}
    except BlockingIOError:
        return {"available": False, "agent_id": resolved, "reason": "busy"}


@router.get("/conversations")
async def list_conversations():
    """List all saved conversations, most recent first."""
    conv_dir = _conversations_dir()
    conversations = []
    for f in sorted(conv_dir.glob("conv-*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            # Build a preview from the first human message
            preview = ""
            for turn in data.get("turns", []):
                if turn["role"] == "human":
                    preview = turn["content"][:100]
                    break
            conversations.append({
                "id": data["id"],
                "agent_id": data["agent_id"],
                "created": data["created"],
                "updated": data.get("updated", data["created"]),
                "preview": preview,
                "turn_count": len(data.get("turns", [])),
                "total_cost_usd": data.get("total_cost_usd", 0.0),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    # Sort by updated time, most recent first
    conversations.sort(key=lambda c: c["updated"], reverse=True)
    return conversations


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """Get a full conversation with all turns."""
    conv = _load_conversation(conv_id)
    if conv is None:
        return {"error": "Conversation not found"}
    return conv
