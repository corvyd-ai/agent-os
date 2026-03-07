"""agent-os prompt assembly — template-driven system prompt construction.

PromptComposer replaces the inline build_system_prompt() in runner.py with
a structured, template-driven approach. Templates live in the prompts/
directory as Jinja2 files.

Usage:
    from agent_os.composer import PromptComposer
    from agent_os.config import get_config

    composer = PromptComposer(config=get_config())
    system_prompt = composer.build_system_prompt(agent_config, task_context="...")
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import core as aios  # aliased as aios for minimal internal churn
from .config import Config, get_config
from .registry import AgentConfig


class PromptComposer:
    """Assemble agent system prompts from Jinja2 templates and runtime state."""

    def __init__(self, *, config: Config | None = None, template_dir: Path | None = None):
        """Initialize with a config and template directory.

        Uses a chain loader: company override dir (if configured) is searched
        first, then package defaults. First match wins — a company only
        overrides the templates it needs to customize.

        Args:
            config: agent-os config (defaults to global singleton)
            template_dir: Directory containing .jinja2 templates.
                          Defaults to ``prompts/`` relative to this file.
        """
        self.config = config or get_config()
        if template_dir is None:
            template_dir = Path(__file__).parent / "prompts"

        search_dirs: list[str] = []
        # Company override dir takes priority
        override = self.config.prompts_override_dir
        if override and override.is_dir():
            search_dirs.append(str(override))
        search_dirs.append(str(template_dir))

        self.env = Environment(
            loader=FileSystemLoader(search_dirs),
            keep_trailing_newline=True,
        )

    def render_template(self, template_name: str, **kwargs) -> str:
        """Render a Jinja2 template with the given variables."""
        t = self.env.get_template(template_name)
        return t.render(**kwargs)

    def build_system_prompt(self, agent_config: AgentConfig, task_context: str | None = None) -> str:
        """Assemble the system prompt: preamble → soul → identity → working memory → broadcasts → context.

        Matches the exact section ordering of the original build_system_prompt()
        in runner.py for behavioral compatibility.
        """
        parts = list(self.get_sections(agent_config, task_context))
        return "\n\n---\n\n".join(content for _name, content in parts)

    def get_sections(self, agent_config: AgentConfig, task_context: str | None = None) -> Iterator[tuple[str, str]]:
        """Yield ordered (section_name, content) pairs for the system prompt.

        This is the canonical ordering:
        1. Preamble
        2. Company values
        3. Soul (Layer 0)
        4. Identity
        5. Working memory (Layer 1)
        6. Active conversations
        7. Inbox awareness
        8. Broadcasts (Layer 2)
        9. System notes (filtered by feedback_routing config)
        10. Quality gates (builder agents only)
        11. Task context (if present)
        """
        cfg = self.config
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # 1. Preamble
        yield (
            "preamble",
            self.render_template(
                "preamble.jinja2",
                company_root=cfg.company_root,
                today=today,
            ),
        )

        # 2. Company Values
        values = aios.read_values(config=cfg)
        if values:
            yield "values", f"# Company Values\n\n{values}"

        # 3. Layer 0: Soul
        soul = aios.read_soul(agent_config.agent_id, config=cfg)
        if soul:
            yield "soul", f"# Your Soul\n\n{soul}"

        # 4. Identity
        yield "identity", f"# Your Identity\n\n{agent_config.system_body}"

        # 5. Layer 1: Working Memory
        wm = aios.read_working_memory(agent_config.agent_id, config=cfg)
        if wm:
            yield "working_memory", f"# Your Working Memory\n\n{wm}"

        # 6. Active conversations
        threads = aios.get_active_threads(agent_config.agent_id, config=cfg)
        if threads:
            pending = aios.get_pending_threads(agent_config.agent_id, config=cfg)
            thread_lines = []
            for meta, _body, path in threads:
                topic = meta.get("topic", "Untitled")
                participants = [p for p in meta.get("participants", []) if p != agent_config.agent_id]
                is_pending = any(p == path for _, _, p in pending)
                status = "**needs your response**" if is_pending else "waiting"
                thread_lines.append(f"- {topic} (with {', '.join(participants)}) — {status}\n  Thread: {path}")
            yield (
                "threads",
                (
                    f"# Active Conversations\n\n"
                    f"{len(pending)} of {len(threads)} threads need your attention:\n\n"
                    + "\n".join(thread_lines)
                    + "\n\nRead and respond to pending threads. Start new ones when "
                    "another agent's perspective would improve your work."
                ),
            )

        # 7. Inbox awareness
        inbox_msgs = aios.read_inbox(agent_config.agent_id, config=cfg)
        if inbox_msgs:
            yield (
                "inbox",
                (
                    f"# Inbox\n\nYou have {len(inbox_msgs)} unread message(s) in your inbox "
                    f"(/company/agents/messages/{agent_config.agent_id}/inbox/). "
                    f"Read them when relevant context would help."
                ),
            )

        # 8. Layer 2: Broadcasts
        broadcasts = aios.read_broadcast(config=cfg)
        if broadcasts:
            broadcast_text = "\n\n---\n\n".join(
                f"**{meta.get('from', 'unknown')}** ({meta.get('date', '?')}): "
                f"**{meta.get('subject', 'No subject')}**\n\n{body}"
                for meta, body, _path in broadcasts
            )
            yield "broadcasts", f"# Broadcast Channel\n\n{broadcast_text}"

        # 9. Open system notes (feedback from operator / dashboard)
        notes = aios.read_feedback(status="open", config=cfg)
        if notes:
            routing = cfg.feedback_routing
            tag_routing: dict[str, set[str]] = {}
            catch_all_id = routing.get("catch_all", "")
            tags_config = routing.get("tags", {})
            for tag_name, agent_ids in tags_config.items():
                if isinstance(agent_ids, list):
                    for aid in agent_ids:
                        tag_routing.setdefault(aid, set()).add(tag_name)
                elif isinstance(agent_ids, str):
                    tag_routing.setdefault(agent_ids, set()).add(tag_name)

            agent_id = agent_config.agent_id
            my_tags = tag_routing.get(agent_id, set())
            is_catch_all = catch_all_id and agent_id.startswith(catch_all_id.split("-")[0] + "-" + catch_all_id.split("-")[1] if "-" in catch_all_id else catch_all_id)

            # Simpler: exact match for catch-all
            is_catch_all = agent_id == catch_all_id or agent_id.startswith(catch_all_id)

            visible_notes = []
            for meta, body, _path in notes:
                note_tags = set(meta.get("tags", []))
                if is_catch_all or note_tags & my_tags:
                    visible_notes.append((meta, body))
                elif not routing:
                    # No routing configured — all agents see all notes
                    visible_notes.append((meta, body))

            if visible_notes:
                note_lines = []
                for meta, body in visible_notes:
                    tags_str = ", ".join(meta.get("tags", []))
                    created = meta.get("created", "?")
                    note_id = meta.get("id", "?")
                    preview = body.split("\n\n")[0].strip() if body else "(empty)"
                    note_lines.append(f"**{note_id}** ({created}) [{tags_str}]\n{preview}")
                yield "system_notes", (
                    "# Open System Notes\n\n"
                    "The following notes have been submitted through the dashboard "
                    "and are awaiting attention:\n\n"
                    + "\n\n".join(note_lines)
                )

        # 10. Quality gates (builder agents only)
        if self.should_include_section("quality_gates", agent_config):
            yield (
                "quality_gates",
                self.render_template(
                    "quality_gates.jinja2",
                    company_root=cfg.company_root,
                ),
            )

        # 11. Task context
        if task_context:
            yield "task_context", (f"# Current Task\n\nYou have been assigned the following task:\n\n{task_context}")

    def should_include_section(self, section_name: str, agent_config: AgentConfig) -> bool:
        """Determine if a conditional section should be included."""
        if section_name == "quality_gates":
            return agent_config.role in self.config.builder_roles
        return True
