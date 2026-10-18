"""write_batches, and transfers.text_norm as a column

Two additions:

* ``write_batches`` - the idempotency record every Google write goes through. The row is written
  ``pending`` and committed before the call, settled ``done`` with the stored answer after it, and
  left ``failed`` when Google refuses. A repeated ``batch_id`` replays the stored answer instead of
  writing twice. See ``app/write_batch.py``.
* ``transfers.text_norm`` - "has this point gone across before?" was a scan of every transfer ever
  made with the JSON snapshot decoded per row. It is now an indexed column, asked per workbook.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22 04:20:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "write_batches",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("transfer", "sheet_save", "add_row", name="write_batch_kind", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "done", "failed", name="write_batch_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=320), nullable=False),
        sa.Column("workbook_id", sa.Uuid(), nullable=True),
        sa.Column("sheet_id", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "result",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    with op.batch_alter_table("write_batches", schema=None) as batch:
        batch.create_index(batch.f("ix_write_batches_status"), ["status"], unique=False)

    with op.batch_alter_table("transfers", schema=None) as batch:
        batch.add_column(sa.Column("text_norm", sa.Text(), nullable=False, server_default=""))
        batch.create_index(batch.f("ix_transfers_text_norm"), ["text_norm"], unique=False)

    # Backfill from the snapshot the column was extracted from, so the repeat check keeps seeing
    # everything that went across before this migration.
    bind = op.get_bind()
    transfers = sa.table(
        "transfers",
        sa.column("id", sa.Uuid()),
        sa.column("text_norm", sa.Text()),
        sa.column("snapshot", sa.JSON()),
    )
    for row in bind.execute(sa.select(transfers.c.id, transfers.c.snapshot)).mappings():
        snapshot = row["snapshot"] or {}
        norm = snapshot.get("text_norm") if isinstance(snapshot, dict) else None
        if norm:
            bind.execute(
                sa.update(transfers).where(transfers.c.id == row["id"]).values(text_norm=norm)
            )


def downgrade() -> None:
    with op.batch_alter_table("transfers", schema=None) as batch:
        batch.drop_index(batch.f("ix_transfers_text_norm"))
        batch.drop_column("text_norm")
    with op.batch_alter_table("write_batches", schema=None) as batch:
        batch.drop_index(batch.f("ix_write_batches_status"))
    op.drop_table("write_batches")
