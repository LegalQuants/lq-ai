"""add documents.ingest_status + ingest_failure_reason — M3-0.3 / DE-276

Adds two columns to ``documents`` so the ingest pipeline can record
post-parse outcomes (embed success, embed failure, partial embed) that
``files.ingestion_status`` does not cover. Parse failures continue to
land at the file level (``files.ingestion_status='failed'`` +
``ingestion_error``) — the file row never produces a ``documents`` row
when parse fails, so the document-level column only describes what
happens after the document is materialized.

Surfaced during the M2-C2 manual verification on 2026-05-16: a
KB-grounded chat returned "I don't have any NDA document in our
conversation" despite the document showing as ingested. The 16 chunks
were correctly persisted but every chunk's embedding was NULL —
``embed_chunks_for_file_job`` had crashed with a ``KeyError`` and the
gap was undetectable from any operator-visible surface. The
``documents`` row sat at "ready" via ``files.ingestion_status`` while
hybrid retrieval silently degraded to FTS-only across the deployment.

Schema change
-------------

* ``documents.ingest_status TEXT NOT NULL DEFAULT 'ok'`` — enum
  (``'ok'``, ``'parse_failed'``, ``'embed_failed'``, ``'partial'``)
  enforced at the storage layer via CHECK constraint. New rows default
  to ``'ok'`` so the existing creation path doesn't need to change;
  the embed worker flips to ``'embed_failed'`` or ``'partial'`` on
  failure. ``'parse_failed'`` is a reserved value for forward
  compatibility — today parse failures stop before a documents row is
  created (the file row tracks them via ``files.ingestion_status``),
  so no code path writes this value in v0.3, but the enum slot exists
  for future placeholder-row designs.
* ``documents.ingest_failure_reason TEXT NULL`` — free-form failure
  message. Populated alongside ``ingest_status`` when set to
  ``'embed_failed'`` or ``'partial'``; ``NULL`` for ``'ok'`` rows.
* Partial index ``idx_documents_ingest_status`` on the failure-state
  values so the admin ingest-health endpoint's aggregate counts
  filter quickly without scanning ``'ok'`` rows.

Backfill
--------

The migration sets ``ingest_status='ok'`` for every existing document
(via the column default). This is the optimistic interpretation: rows
in the table today have been through the pipeline, and the silent
embed-failure bug from the M2-C2 episode is corrected in the same M3
phase. Operators with concerns about pre-migration state can re-run
ingest per-file via the existing flow; the new
``/api/v1/admin/ingest-health`` endpoint surfaces aggregate counts so
they can spot anomalies.

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "ingest_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'ok'"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "ingest_failure_reason",
            sa.Text(),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_documents_ingest_status",
        "documents",
        "ingest_status IN ('ok','parse_failed','embed_failed','partial')",
    )
    # Partial index — only the failure-state rows. The 'ok' rows are
    # the steady-state majority; including them would bloat the index
    # and add write cost on the dominant insert path.
    op.create_index(
        "idx_documents_ingest_status",
        "documents",
        ["ingest_status"],
        postgresql_where=sa.text("ingest_status IN ('parse_failed','embed_failed','partial')"),
    )


def downgrade() -> None:
    op.drop_index("idx_documents_ingest_status", table_name="documents")
    op.drop_constraint("ck_documents_ingest_status", "documents", type_="check")
    op.drop_column("documents", "ingest_failure_reason")
    op.drop_column("documents", "ingest_status")
