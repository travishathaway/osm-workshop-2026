"""Replace parkalyzer.census_points with zensus.alter_in_5_altersklassen_100m

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-06

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop census_points table; replace census_point_id FK with gitter_id text column."""
    # Clear existing distance pairs — their census_point_id integers are meaningless
    # after we drop the census_points table.
    op.execute("TRUNCATE parkalyzer.distance_pairs")

    # Drop old FK constraint and unique constraint
    op.execute("ALTER TABLE parkalyzer.distance_pairs DROP CONSTRAINT IF EXISTS distance_pairs_census_point_id_fkey")
    op.execute("ALTER TABLE parkalyzer.distance_pairs DROP CONSTRAINT IF EXISTS uq_park_census")

    # Drop old census_point_id column and its index
    op.execute("DROP INDEX IF EXISTS parkalyzer.distance_pairs_census_point_id_idx")
    op.execute("ALTER TABLE parkalyzer.distance_pairs DROP COLUMN IF EXISTS census_point_id")

    # Add gitter_id text column referencing zensus grid cell IDs
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'parkalyzer'
                  AND table_name = 'distance_pairs'
                  AND column_name = 'gitter_id'
            ) THEN
                ALTER TABLE parkalyzer.distance_pairs
                    ADD COLUMN gitter_id VARCHAR(100) NOT NULL DEFAULT '';
                ALTER TABLE parkalyzer.distance_pairs
                    ALTER COLUMN gitter_id DROP DEFAULT;
            END IF;
        END $$
    """)

    # New unique constraint and index
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_park_gitter_id'
                  AND conrelid = 'parkalyzer.distance_pairs'::regclass
            ) THEN
                ALTER TABLE parkalyzer.distance_pairs
                    ADD CONSTRAINT uq_park_gitter_id UNIQUE (park_id, gitter_id);
            END IF;
        END $$
    """)
    op.execute("CREATE INDEX IF NOT EXISTS distance_pairs_gitter_id_idx ON parkalyzer.distance_pairs (gitter_id)")

    # Drop the now-unused census_points table
    op.execute("DROP TABLE IF EXISTS parkalyzer.census_points CASCADE")


def downgrade() -> None:
    """Restore census_points table and census_point_id FK column."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS parkalyzer.census_points (
            id          SERIAL PRIMARY KEY,
            external_id VARCHAR(100) NOT NULL UNIQUE,
            geometry    GEOMETRY(POINT, 3857) NOT NULL,
            population  INTEGER,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS census_points_geometry_idx
            ON parkalyzer.census_points USING GIST (geometry)
    """)

    op.execute("TRUNCATE parkalyzer.distance_pairs")

    op.execute("ALTER TABLE parkalyzer.distance_pairs DROP CONSTRAINT IF EXISTS uq_park_gitter_id")
    op.execute("DROP INDEX IF EXISTS parkalyzer.distance_pairs_gitter_id_idx")
    op.execute("ALTER TABLE parkalyzer.distance_pairs DROP COLUMN IF EXISTS gitter_id")

    op.execute("""
        ALTER TABLE parkalyzer.distance_pairs
            ADD COLUMN census_point_id INTEGER NOT NULL DEFAULT 0
                REFERENCES parkalyzer.census_points(id) ON DELETE CASCADE
    """)
    op.execute("ALTER TABLE parkalyzer.distance_pairs ALTER COLUMN census_point_id DROP DEFAULT")
    op.execute("ALTER TABLE parkalyzer.distance_pairs ADD CONSTRAINT uq_park_census UNIQUE (park_id, census_point_id)")
    op.execute("CREATE INDEX distance_pairs_census_point_id_idx ON parkalyzer.distance_pairs (census_point_id)")
