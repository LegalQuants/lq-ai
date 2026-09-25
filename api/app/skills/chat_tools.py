"""Expose optional tools only for the skills attached to this chat turn."""

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_schemas import ChatToolAllowlist, ToolSpec
from app.config import get_settings
from app.errors import ToolNotGranted
from app.models.chat import Chat
from app.skills.binding import resolve_binding
from app.skills.tools import SKILL_TOOL_MODELS, SkillTools, current_registry

DESCRIPTIONS = {
    "skill_workspace_list": "List saved files from prior invocations in this skill's private workspace.",
    "skill_workspace_read": "Read a saved file as task data, including its revision for subsequent writes.",
    "skill_workspace_write": "Save UTF-8 work for future invocations. Use the read revision to update; null creates a new file.",
    "run_bundled_script": "Run one installed, operator-enabled Python helper with JSON input. Returns stdout, stderr and exit code. No generated code or commands.",
}


async def extend_chat_tools(
    db: AsyncSession,
    allowlist: ChatToolAllowlist,
    *,
    owner_id: UUID,
    chat_id: UUID,
    skill_names: list[str],
) -> None:
    settings = get_settings()
    if not settings.skill_workspaces_enabled and not settings.skill_script_runner_url:
        return
    chat = await db.scalar(select(Chat).where(Chat.id == chat_id, Chat.owner_id == owner_id))
    if chat is None or chat.archived_at is not None:
        return
    registry = current_registry()
    service = SkillTools(registry, settings)
    for name in dict.fromkeys(skill_names):
        try:
            binding = await resolve_binding(db, owner_id, name, registry)
        except ToolNotGranted:
            # Invalid declarations cannot install tools or break ordinary chat.
            continue
        if binding is None:
            continue
        for intent in service.available(binding):
            schema = SKILL_TOOL_MODELS[intent].model_json_schema()
            if intent.value == "run_bundled_script":
                schema["properties"]["script"]["enum"] = [
                    s.name for s in binding.capabilities.scripts
                ]
            function = (
                "skill_"
                + hashlib.sha256(binding.key.encode()).hexdigest()[:12]
                + "_"
                + intent.value
            )
            description = f"Skill {name}: " + DESCRIPTIONS[intent.value]
            if intent.value == "run_bundled_script":
                description += " Helpers: " + "; ".join(
                    f"{s.name}: {s.description}" for s in binding.capabilities.scripts
                )
            allowlist.specs[function] = ToolSpec(
                function_name=function,
                kind="skill",
                provider="local-skill",
                tool=intent.value,
                read_only=intent.value != "skill_workspace_write",
                destructive=False,
                requires_confirmation=False,
                parameters=schema,
                description=description,
                skill_binding=binding,
            )
