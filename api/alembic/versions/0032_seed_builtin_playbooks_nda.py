"""seed built-in NDA playbooks (mutual + unilateral) — M3-A3

Idempotent data migration that inserts the two NDA built-in playbooks
into ``playbooks`` + ``playbook_positions`` at version ``1.0.0``.

Source-of-truth files
---------------------

The playbook content is loaded from the canonical YAML files at the
repo root — ``skills/playbooks/nda/playbook.yaml`` (mutual) and
``skills/playbooks/nda-unilateral/playbook.yaml`` (discloser-favorable).

The migration reads these at upgrade time. Future content updates to
the playbooks ship as new migrations (each version bumping
``playbook.version`` and inserting a fresh row); the migration body
here is frozen at v1.0.0 and never re-edited after release.

Idempotency
-----------

The migration checks ``(playbooks.name, playbooks.version)`` before
inserting. If a row with that name + version already exists (either
because the migration ran previously or because an operator
manually seeded the same content), the migration is a no-op for that
playbook. This makes it safe to re-run on partially-migrated
databases.

Not legal advice
----------------

Per the project's contribution posture for built-in playbooks
(M3-A3 PR description + forthcoming CONTRIBUTING.md refresh), the
content shipped here represents one reasonable market position
drafted by the maintainer team. It is not legal advice and operators
are expected to apply their own professional judgment, fork the
playbook for their organization's standards, or replace it entirely.
The disclaimer is also embedded in each playbook's ``description``
field so it surfaces wherever the playbook renders.

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-18
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


# Path resolution: this file lives at
# ``<repo>/api/alembic/versions/0032_*.py``; the skills directory is at
# ``<repo>/skills/``. Walking up four parents gets the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PLAYBOOKS_DIR = _REPO_ROOT / "skills" / "playbooks"

# Slug → YAML file mapping. Order matters: positions in each playbook
# are inserted in ``position_order`` ASC, but the order of the
# playbooks themselves is preserved for deterministic re-runs.
_BUILTIN_NDA_SLUGS: list[str] = ["nda", "nda-unilateral"]


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
            f"Migration 0032 cannot find built-in playbook YAML at {path}. "
            "The skills/ directory must ship alongside api/ for this seed "
            "migration to succeed."
        )
    parsed = yaml.safe_load(path.read_text())
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Migration 0032: playbook YAML at {path} must parse to a dict.")
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

    for slug in _BUILTIN_NDA_SLUGS:
        playbook = _load_playbook_yaml(slug)
        name = str(playbook["name"])
        version = str(playbook["version"])

        # Idempotency: skip if a row with this (name, version) is already
        # present. Lets the migration recover cleanly from partial-apply
        # states (e.g., operator manually seeded one of the two and is
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
    for slug in _BUILTIN_NDA_SLUGS:
        playbook = _load_playbook_yaml(slug)
        # Delete by (name, version) — positions cascade per the
        # ON DELETE CASCADE on playbook_positions.playbook_id.
        bind.execute(
            sa.text("DELETE FROM playbooks WHERE name = :name AND version = :version"),
            {"name": str(playbook["name"]), "version": str(playbook["version"])},
        )
