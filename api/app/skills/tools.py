"""Common optional skill tools for interactive and background invocations."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.config import Settings, get_settings
from app.errors import ToolNotGranted
from app.skills.binding import SkillBinding, revalidate_binding
from app.skills.capabilities import EmptyInput, FileRead, FileWrite, ScriptInput, StrictModel
from app.skills.registry import MutableSkillRegistry
from app.skills.workspace import check_owner, workspace_operation

if TYPE_CHECKING:
    from app.autonomous.guard import ToolResult

SKILL_TOOL_MODELS: dict[ToolIntent, type[StrictModel]] = {
    ToolIntent.skill_workspace_list: EmptyInput,
    ToolIntent.skill_workspace_read: FileRead,
    ToolIntent.skill_workspace_write: FileWrite,
    ToolIntent.run_bundled_script: ScriptInput,
}
SKILL_TOOL_INTENTS = frozenset(SKILL_TOOL_MODELS)


def parse_skill_tool(intent: ToolIntent, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return SKILL_TOOL_MODELS[intent].model_validate(params).model_dump(mode="json")
    except (PydanticValidationError, KeyError, ValueError, RecursionError):
        raise ToolNotGranted("Invalid bounded skill tool arguments") from None


def current_registry() -> MutableSkillRegistry:
    from app.main import app

    holder = getattr(app.state, "skill_registry", None)
    if holder is None:
        raise ToolNotGranted("Skill registry unavailable")
    return holder


class SkillTools:
    def __init__(self, registry: MutableSkillRegistry, settings: Settings | None = None) -> None:
        self.registry, self.settings = registry, settings or get_settings()

    def available(self, binding: SkillBinding) -> tuple[ToolIntent, ...]:
        intents: list[ToolIntent] = []
        if self.settings.skill_workspaces_enabled and binding.capabilities.workspace_version:
            intents.extend(
                (
                    ToolIntent.skill_workspace_list,
                    ToolIntent.skill_workspace_read,
                    ToolIntent.skill_workspace_write,
                )
            )
        if (
            binding.capabilities.scripts
            and binding.bundle_digest
            and self.settings.skill_script_runner_url
            and self.settings.skill_script_runner_token
        ):
            intents.append(ToolIntent.run_bundled_script)
        return tuple(intents)

    async def execute(
        self,
        db: AsyncSession,
        *,
        binding: SkillBinding,
        owner_id: UUID,
        project_id: UUID | None,
        intent: ToolIntent,
        params: dict[str, Any],
    ) -> ToolResult:
        from app.autonomous.guard import ToolResult

        if intent not in self.available(binding):
            raise ToolNotGranted("Optional skill capability is not enabled")
        params = parse_skill_tool(intent, params)
        await revalidate_binding(db, owner_id, binding, self.registry)
        await check_owner(db, owner_id, project_id)
        if intent == ToolIntent.run_bundled_script:
            result = await self.run_script(binding, ScriptInput.model_validate(params))
            # Recheck access and pin after a bounded job, before its result enters
            # the calling prompt/receipt. Orchestration separately fences settlement.
            await revalidate_binding(db, owner_id, binding, self.registry)
            await check_owner(db, owner_id, project_id)
        else:
            operation = intent.value.removeprefix("skill_workspace_")
            result = await workspace_operation(
                db,
                binding=binding,
                owner_id=owner_id,
                project_id=project_id,
                operation=operation,
                params=params,
            )
        outcome = "success"
        if "error" in result:
            outcome = "skill_tool_refused"
        elif intent == ToolIntent.run_bundled_script and result.get("exit_code") != 0:
            outcome = "skill_script_failed"
        return ToolResult(
            cost_usd=Decimal("0"),
            data=result,
            outcome=outcome,
        )

    async def run_script(self, binding: SkillBinding, request: ScriptInput) -> dict[str, Any]:
        if request.script not in {script.name for script in binding.capabilities.scripts}:
            raise ToolNotGranted("Script is not declared by this installed skill")
        url = self.settings.skill_script_runner_url or ""
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
            or len(self.settings.skill_script_runner_token) < 32
        ):
            raise ToolNotGranted("A private authenticated script broker must be configured")
        try:
            async with (
                httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client,
                client.stream(
                    "POST",
                    url.rstrip("/") + "/run",
                    headers={"Authorization": "Bearer " + self.settings.skill_script_runner_token},
                    json={
                        "key": binding.key,
                        "bundle_digest": binding.bundle_digest,
                        "script": request.script,
                        "inputs": request.inputs,
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    return {"error": "runner_unavailable"}
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 524288:
                        return {"error": "invalid_runner_output"}
            result = json.loads(data)
            allowed_errors = {
                "invalid_request",
                "script_not_enabled",
                "runner_busy",
                "bundle_changed",
                "script_timeout",
                "output_limit",
                "script_failed",
                "runner_unavailable",
            }
            if (
                isinstance(result, dict)
                and set(result) == {"error"}
                and result["error"] in allowed_errors
            ):
                return result
            if (
                not isinstance(result, dict)
                or set(result) != {"stdout", "stderr", "exit_code"}
                or type(result["exit_code"]) is not int
                or not all(isinstance(result[key], str) for key in ("stdout", "stderr"))
                or sum(len(result[key].encode()) for key in ("stdout", "stderr")) > 196608
            ):
                return {"error": "invalid_runner_output"}
            return result
        except (httpx.HTTPError, ValueError, TypeError):
            return {"error": "runner_unavailable"}
