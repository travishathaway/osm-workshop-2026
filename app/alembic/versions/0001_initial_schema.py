"""Create parkalyzer schema and initial tables

Revision ID: 0001
Revises:
Create Date: 2026-07-05

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create parkalyzer schema and all tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS parkalyzer")

    op.execute("""
        CREATE TABLE IF NOT EXISTS parkalyzer.parks (
            id          SERIAL PRIMARY KEY,
            osm_id      BIGINT NOT NULL UNIQUE,
            name        VARCHAR(500),
            geometry    GEOMETRY(POLYGON, 4326) NOT NULL,
            area        DOUBLE PRECISION,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS parks_geometry_idx
            ON parkalyzer.parks USING GIST (geometry)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS parkalyzer.census_points (
            id          SERIAL PRIMARY KEY,
            external_id VARCHAR(100) NOT NULL UNIQUE,
            geometry    GEOMETRY(POINT, 4326) NOT NULL,
            population  INTEGER,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS census_points_geometry_idx
            ON parkalyzer.census_points USING GIST (geometry)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS parkalyzer.distance_pairs (
            id                SERIAL PRIMARY KEY,
            park_id           INTEGER NOT NULL
                                REFERENCES parkalyzer.parks(id) ON DELETE CASCADE,
            census_point_id   INTEGER NOT NULL
                                REFERENCES parkalyzer.census_points(id) ON DELETE CASCADE,
            distance_meters   DOUBLE PRECISION,
            duration_seconds  DOUBLE PRECISION,
            computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (park_id, census_point_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS distance_pairs_park_id_idx
            ON parkalyzer.distance_pairs (park_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS distance_pairs_census_point_id_idx
            ON parkalyzer.distance_pairs (census_point_id)
    """)


def downgrade() -> None:
    """Drop all parkalyzer tables and schema."""
    op.execute("DROP TABLE IF EXISTS parkalyzer.distance_pairs CASCADE")
    op.execute("DROP TABLE IF EXISTS parkalyzer.census_points CASCADE")
    op.execute("DROP TABLE IF EXISTS parkalyzer.parks CASCADE")
    op.execute("DROP SCHEMA IF EXISTS parkalyzer CASCADE")
