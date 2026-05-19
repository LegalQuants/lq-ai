"""seed built-in MSA / DPA playbooks (MSA-SaaS, DPA-GDPR, MSA-Commercial-Purchase) — M3-A5

Idempotent data migration that inserts the three M3-A5 built-in playbooks
into ``playbooks`` + ``playbook_positions`` at version ``1.0.0``.

Source-of-truth files
---------------------

The playbook content is loaded from the canonical YAML files at the
repo root:

* ``skills/playbooks/msa-saas/playbook.yaml`` — MSA — SaaS (customer-perspective)
* ``skills/playbooks/dpa-gdpr/playbook.yaml`` — DPA — GDPR (controller-to-processor)
* ``skills/playbooks/msa-commercial-purchase/playbook.yaml`` — MSA — Commercial Services (purchase-side)

The migration reads these at upgrade time, mirroring the M3-A3 seed
migration 0032 pattern. Future content updates to the playbooks ship as
new migrations (each version bumping ``playbook.version`` and inserting
a fresh row); the migration body here is frozen at v1.0.0 and never
re-edited after release.

Idempotency
-----------

The migration checks ``(playbooks.name, playbooks.version)`` before
inserting. If a row with that name + version already exists (either
because the migration ran previously or because an operator manually
seeded the same content), the migration is a no-op for that playbook.
This makes it safe to re-run on partially-migrated databases.

Not legal advice
----------------

Per the project's posture for built-in playbooks (Decision F locked at
M3-A3 kickoff; clarified further at M3-A5 kickoff 2026-05-19), the
content shipped here represents starting-point market positions
drafted from public templates as a head-start for in-house counsel
installing LQ.AI. **The maintainer team has not reviewed or validated
the legal substance.** Operators are expected to apply their own
professional judgment, fork the playbook for their organization's
standards, or replace it entirely. The disclaimer is also embedded in
each playbook's ``description`` field so it surfaces wherever the
playbook renders.

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-19
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


# Path resolution: this file lives at
# ``<repo>/api/alembic/versions/0033_*.py``; the skills directory is at
# ``<repo>/skills/``. Walking up four parents gets the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PLAYBOOKS_DIR = _REPO_ROOT / "skills" / "playbooks"

# Slug → YAML file mapping. Order matters: positions in each playbook
# are inserted in ``position_order`` ASC, but the order of the
# playbooks themselves is preserved for deterministic re-runs.
_BUILTIN_M3_A5_SLUGS: list[str] = [
    "msa-saas",
    "dpa-gdpr",
    "msa-commercial-purchase",
]


def _load_playbook_yaml(slug: str) -> dict[str, Any]:
    """Read and parse ``skills/playbooks/<slug>/playbook.yaml``.

    Raises :class:`RuntimeError` with a clear message if the file is
    missing — that condition would indicate a deployment-packaging bug
    (the migration ships in the same image as the playbook YAML files;
    they must travel together).
    """
    path = _PLAYBOOKS_DIR / slug / "playbook.yaml"
    if not path.exists():
        raise RuntimeError(
            f"Migration 0033 cannot find built-in playbook YAML at {path}. "
            "The skills/ directory must ship alongside api/ for this seed "
            "migration to succeed."
        )
    parsed = yaml.safe_load(path.read_text())
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Migration 0033: playbook YAML at {path} must parse to a dict.")
    return parsed


def upgrade() -> None:
    bind = op.get_bind()
    playbooks_table = sa.table(
        "playbooks",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.Text()),
        sa.column("contract_type", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("version", sa.Text()),
    )
    positions_table = sa.table(
        "playbook_positions",
        sa.column("playbook_id", postgresql.UUID(as_uuid=True)),
        sa.column("issue", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("standard_language", sa.Text()),
        sa.column("fallback_tiers", postgresql.JSONB()),
        sa.column("redline_strategy", sa.Text()),
        sa.column("severity_if_missing", sa.Text()),
        sa.column("detection_keywords", postgresql.ARRAY(sa.Text())),
        sa.column("detection_examples", postgresql.ARRAY(sa.Text())),
        sa.column("position_order", sa.Integer()),
    )

    for slug in _BUILTIN_M3_A5_SLUGS:
        playbook = _load_playbook_yaml(slug)
        name = str(playbook["name"])
        version = str(playbook["version"])

        # Idempotency: skip if a row with this (name, version) is already
        # present. Lets the migration recover cleanly from partial-apply
        # states (e.g., operator manually seeded one of the three and is
        # now applying the migration).
        existing_id_result = bind.execute(
            sa.text("SELECT id FROM playbooks WHERE name = :name AND version = :version"),
            {"name": name, "version": version},
        )
        if existing_id_result.scalar_one_or_none() is not None:
            continue

        playbook_id = bind.execute(
            playbooks_table.insert()
            .values(
                name=name,
                contract_type=str(playbook["contract_type"]),
                description=str(playbook.get("description", "")),
                version=version,
            )
            .returning(playbooks_table.c.id)
        ).scalar_one()

        position_rows: list[dict[str, Any]] = []
        for position in playbook.get("positions") or []:
            position_rows.append(
                {
                    "playbook_id": playbook_id,
                    "issue": str(position["issue"]),
                    "description": str(position.get("description", "")),
                    "standard_language": str(position["standard_language"]),
                    "fallback_tiers": position.get("fallback_tiers") or [],
                    "redline_strategy": str(position.get("redline_strategy", "")),
                    "severity_if_missing": str(position["severity_if_missing"]),
                    "detection_keywords": list(position.get("detection_keywords") or []),
                    "detection_examples": list(position.get("detection_examples") or []),
                    "position_order": int(position.get("position_order", 0)),
                }
            )
        if position_rows:
            bind.execute(positions_table.insert(), position_rows)


def downgrade() -> None:
    bind = op.get_bind()
    for slug in _BUILTIN_M3_A5_SLUGS:
        playbook = _load_playbook_yaml(slug)
        # Delete by (name, version) — positions cascade per the
        # ON DELETE CASCADE on playbook_positions.playbook_id.
        bind.execute(
            sa.text("DELETE FROM playbooks WHERE name = :name AND version = :version"),
            {"name": str(playbook["name"]), "version": str(playbook["version"])},
        )
