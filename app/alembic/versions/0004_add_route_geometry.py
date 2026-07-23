"""Add route geometry column to distance_pairs

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable route GEOMETRY(LINESTRING, 4326) column to distance_pairs."""
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'parkalyzer'
                  AND table_name = 'distance_pairs'
                  AND column_name = 'route'
            ) THEN
                ALTER TABLE parkalyzer.distance_pairs
                    ADD COLUMN route GEOMETRY(LINESTRING, 4326);
            END IF;
        END $$
    """)


def downgrade() -> None:
    """Drop route column from distance_pairs."""
    op.execute(
        "ALTER TABLE parkalyzer.distance_pairs DROP COLUMN IF EXISTS route"
    )
