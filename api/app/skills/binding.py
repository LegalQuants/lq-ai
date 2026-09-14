"""Resolve exact skill identities without granting authority from skill text."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolNotGranted
from app.models.team import TeamMember
from app.models.user_skill import UserSkill
from app.skills.capabilities import SkillCapabilities
from app.skills.registry import MutableSkillRegistry, SkillRecord


@dataclass(frozen=True)
class SkillBinding:
    name: str
    key: str
    digest: str
    capabilities: SkillCapabilities
    bundle_digest: str | None = None


def bind_record(record: SkillRecord) -> SkillBinding:
    from app.autonomous.orchestration.policy import load_pinned_skill

    pinned = load_pinned_skill(record)
    return SkillBinding(
        name=record.name,
        key=f"{record.source}:{record.name}",
        digest=pinned.pin.digest,
        capabilities=record.frontmatter.lq_ai.capabilities
        if record.frontmatter.lq_ai
        else SkillCapabilities(),
        bundle_digest=pinned.bundle_digest,
    )


def _bind_row(row: UserSkill) -> SkillBinding:
    try:
        capabilities = SkillCapabilities.model_validate(
            (row.frontmatter_extra or {}).get("capabilities", {})
        )
    except ValidationError:
        raise ToolNotGranted("Invalid optional skill capabilities") from None
    if capabilities.scripts:
        raise ToolNotGranted("Database skills cannot install executable scripts")
    digest = hashlib.sha256(
        json.dumps(
            [str(row.id), row.version, row.body, row.frontmatter_extra],
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return SkillBinding(row.slug, f"{row.scope}:{row.id}", digest, capabilities)


def _visible_rows(owner_id: UUID) -> Select[tuple[UserSkill]]:
    return (
        select(UserSkill)
        .where(
            UserSkill.archived_at.is_(None),
            ((UserSkill.scope == "user") & (UserSkill.owner_user_id == owner_id))
            | (
                (UserSkill.scope == "team")
                & UserSkill.owner_team_id.in_(
                    select(TeamMember.team_id).where(TeamMember.user_id == owner_id)
                )
            ),
        )
        .execution_options(populate_existing=True)
    )


async def resolve_binding(
    db: AsyncSession,
    owner_id: UUID,
    name: str,
    registry: MutableSkillRegistry,
) -> SkillBinding | None:
    rows = list(
        await db.scalars(
            _visible_rows(owner_id)
            .where(UserSkill.slug == name)
            .order_by(UserSkill.updated_at.desc(), UserSkill.id.desc())
        )
    )
    row = next((r for r in rows if r.scope == "user"), rows[0] if rows else None)
    if row is not None:
        return _bind_row(row)
    record = registry.current().get(name)
    return bind_record(record) if record else None


async def revalidate_binding(
    db: AsyncSession,
    owner_id: UUID,
    binding: SkillBinding,
    registry: MutableSkillRegistry,
) -> None:
    source, identity = binding.key.split(":", 1)
    if source in {"user", "team"}:
        row = await db.scalar(_visible_rows(owner_id).where(UserSkill.id == UUID(identity)))
        current = _bind_row(row) if row else None
    else:
        record = registry.current().get(identity)
        current = bind_record(record) if record and record.source == source else None
    if current != binding:
        raise ToolNotGranted("Skill changed or access was revoked; start a new invocation")
