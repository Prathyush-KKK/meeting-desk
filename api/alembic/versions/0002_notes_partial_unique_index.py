"""notes: unique per meeting only while the note is live

A removed note keeps its row for the 30-day recovery window, so the table-wide
``unique(meeting_id, text_hash)`` made pasting the same text again after a delete an
IntegrityError - a 500 on a path the person is entitled to take. The constraint becomes a partial
unique index on ``deleted_at IS NULL``, which Postgres and SQLite both support.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22 04:10:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_notes_meeting_text_live"
CONSTRAINT = "uq_notes_meeting_text"


def upgrade() -> None:
    # SQLite cannot drop a table constraint in place; batch_alter_table rebuilds the table.
    with op.batch_alter_table("notes", schema=None) as batch:
        batch.drop_constraint(CONSTRAINT, type_="unique")
    op.create_index(
        INDEX,
        "notes",
        ["meeting_id", "text_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="notes")
    with op.batch_alter_table("notes", schema=None) as batch:
        batch.create_unique_constraint(CONSTRAINT, ["meeting_id", "text_hash"])
