from __future__ import annotations

import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from parkalyzer.constants import GEOMETRY_SRID, SCHEMA_NAME


class Geometry(sa.types.UserDefinedType):
    """Minimal PostGIS geometry type for SQLAlchemy 2.0 (no geoalchemy2 required).

    Values round-trip as hex-encoded WKB. Use PostGIS functions in queries
    (ST_AsGeoJSON, ST_AsText, etc.) when human-readable output is needed.
    Autogenerate will not detect changes to this type — alter geometry
    columns via hand-written migration files.
    """

    cache_ok = True

    def __init__(self, geometry_type: str = "GEOMETRY", srid: int = GEOMETRY_SRID) -> None:
        self.geometry_type = geometry_type
        self.srid = srid

    def get_col_spec(self, **kw: object) -> str:
        return f"GEOMETRY({self.geometry_type}, {self.srid})"

    def bind_expression(self, bindvalue: sa.BindParameter) -> sa.Function:
        return sa.func.ST_GeomFromText(bindvalue, self.srid)

    def column_expression(self, col: sa.Column) -> sa.Column:
        return col


class Base(DeclarativeBase):
    pass


class Park(Base):
    """A park polygon sourced from OpenStreetMap."""

    __tablename__ = "parks"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    osm_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)
    osm_type: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    geometry: Mapped[str] = mapped_column(Geometry("GEOMETRY", GEOMETRY_SRID), nullable=False)
    area: Mapped[Optional[float]] = mapped_column(sa.Double, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


class DistancePair(Base):
    """A computed distance/duration between a park and a Zensus 100m grid cell."""

    __tablename__ = "distance_pairs"
    __table_args__ = (
        sa.UniqueConstraint("park_id", "gitter_id", name="uq_park_gitter_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    park_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey(f"{SCHEMA_NAME}.parks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gitter_id: Mapped[str] = mapped_column(sa.String(100), nullable=False, index=True)
    distance_meters: Mapped[Optional[float]] = mapped_column(sa.Double, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(sa.Double, nullable=True)
    route: Mapped[Optional[str]] = mapped_column(Geometry("LINESTRING", 4326), nullable=True)
    computed_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )

    park: Mapped[Park] = relationship()
