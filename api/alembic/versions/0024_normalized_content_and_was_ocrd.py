"""add documents.normalized_content and documents.was_ocrd — M2-A1

These two columns are the data substrate the M2 Citation Engine and
tolerant-match step depend on:

* ``normalized_content`` carries the full, canonical PyMuPDF text
  stream. The fidelity invariant
  ``normalized_content[chunk.char_offset_start:chunk.char_offset_end]
  == chunk.content`` is what the verifier consumes when it re-reads
  a citation against its source.
* ``was_ocrd`` is a forward-looking flag: an M2 follow-on task adds
  an OCR fallback for image-only PDFs, and tolerant-match toggles
  OCR-artifact normalization on documents that went through OCR.
  M1's parsers never OCR, so existing rows and new M1 ingests get
  ``FALSE``; the column unblocks the later code path.

Both columns are ``NOT NULL`` with a default so backfill on existing
rows is the schema's job rather than the migration's. The one-time
script ``scripts/backfill_normalized_content.py`` then reconstructs
``normalized_content`` for pre-M2 documents from their chunks.

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "normalized_content",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "was_ocrd",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "was_ocrd")
    op.drop_column("documents", "normalized_content")
