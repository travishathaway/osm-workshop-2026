"""Add osm_type and tags to parks; widen geometry type to GEOMETRY

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE parkalyzer.parks
            ADD COLUMN IF NOT EXISTS osm_type VARCHAR(100)
    """)
    op.execute("""
        ALTER TABLE parkalyzer.parks
            ADD COLUMN IF NOT EXISTS tags JSONB
    """)
    # Widen from POLYGON to GEOMETRY so multipolygons and other types are accepted.
    op.execute("""
        ALTER TABLE parkalyzer.parks
            ALTER COLUMN geometry TYPE GEOMETRY(GEOMETRY, 3857)
            USING geometry::GEOMETRY(GEOMETRY, 3857)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE parkalyzer.parks
            DROP COLUMN IF EXISTS tags
    """)
    op.execute("""
        ALTER TABLE parkalyzer.parks
            DROP COLUMN IF EXISTS osm_type
    """)
    op.execute("""
        ALTER TABLE parkalyzer.parks
            ALTER COLUMN geometry TYPE GEOMETRY(POLYGON, 3857)
            USING geometry::GEOMETRY(POLYGON, 3857)
    """)
